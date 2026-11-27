package ru.homehub.calendar

import android.content.Context
import android.system.Os
import android.util.Base64
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileNotFoundException
import java.util.UUID
import java.security.MessageDigest

/**
 * Очередь команд, сделанных вне дома. Команда живёт в очереди, пока сервер не подтвердит её в снимке
 * (поле applied); весь список шифруется и выгружается в облако файлом ops-<телефон>.bin.
 */
object Outbox {
    private const val SEND = "cloud-outbox"
    private fun file(context: Context) = File(context.filesDir, "ops.json")
    private fun snapshotFile(context: Context) = File(context.filesDir, "snapshot.json")

    private fun read(file: File): String? = try {
        file.readText()
    } catch (e: FileNotFoundException) {
        if (file.exists()) throw e
        null
    }

    private fun write(file: File, text: String) {
        val staged = File(file.parentFile, "${file.name}.new")
        try {
            staged.outputStream().use { stream ->
                stream.write(text.encodeToByteArray())
                stream.fd.sync()
            }
            Os.rename(staged.path, file.path)
        } finally {
            staged.delete()
        }
    }

    @Synchronized
    fun pending(context: Context): JSONArray =
        read(file(context))?.let(::JSONArray) ?: JSONArray()

    private fun save(context: Context, list: JSONArray) = write(file(context), list.toString())

    /** Добавляет команду и возвращает её id. */
    fun add(context: Context, op: JSONObject): String = addAll(context, listOf(op)).single()

    @Synchronized
    fun addAll(context: Context, ops: List<JSONObject>): List<String> {
        if (ops.isEmpty()) return emptyList()
        val device = Prefs(context).deviceId
        val list = pending(context)
        val ids = ops.map { op ->
            val now = System.currentTimeMillis()
            val id = "$device-$now-${UUID.randomUUID().toString().take(8)}"
            list.put(op.put("id", id).put("t", now))
            id
        }
        save(context, list)
        schedule(context, afterCurrent = true)
        return ids
    }

    /** Убирает из очереди команды, которые сервер уже применил. */
    @Synchronized
    fun dropApplied(context: Context, applied: Set<String>): Boolean {
        val list = pending(context)
        val keep = JSONArray()
        for (i in 0 until list.length()) {
            val o = list.getJSONObject(i)
            if (o.optString("id") !in applied) keep.put(o)
        }
        if (keep.length() == list.length()) return false
        save(context, keep)
        return true
    }

    /** Все отправки используют одну цепочку. После новой команды нужен следующий запуск, даже если текущий уже начался. */
    fun schedule(context: Context, afterCurrent: Boolean = false) {
        val request = OneTimeWorkRequestBuilder<OutboxWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        val policy = if (afterCurrent) ExistingWorkPolicy.APPEND_OR_REPLACE else ExistingWorkPolicy.KEEP
        WorkManager.getInstance(context).enqueueUniqueWork(SEND, policy, request)
    }

    internal data class Batch(val json: String, val revision: String)

    @Synchronized
    internal fun pendingBatch(context: Context, destination: String): Batch? {
        val json = read(file(context)) ?: return null
        // Проверяем формат, чтобы не отправить повреждённую локальную очередь.
        JSONArray(json)
        val revision = Base64.encodeToString(
            MessageDigest.getInstance("SHA-256").digest((destination + "\u0000" + json).encodeToByteArray()),
            Base64.NO_WRAP,
        )
        return if (revision == Prefs(context).outboxSentRevision) null else Batch(json, revision)
    }

    internal fun markUploaded(context: Context, batch: Batch) {
        // Подтверждается только отправленный пакет. Команда, добавленная во время сети, меняет ревизию файла.
        Prefs(context).outboxSentRevision = batch.revision
    }

    /** Вызывается только OutboxWorker из последовательной цепочки WorkManager. */
    internal fun upload(context: Context): Boolean {
        val prefs = Prefs(context)
        val token = prefs.cloudToken ?: return false
        val key = prefs.cloudKey ?: return false
        val name = prefs.opsFile
        val batch = pendingBatch(context, "$name\u0000$token\u0000$key") ?: return false
        val bytes = Cloud.encrypt(Base64.decode(key, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP), batch.json)
        Cloud.upload(token, name, bytes)
        markUploaded(context, batch)
        if (!prefs.legacyOpsRemoved) {
            val oldName = "ops-${prefs.deviceId}.bin"
            if (oldName == name || runCatching { Cloud.delete(token, oldName) }.isSuccess) {
                prefs.legacyOpsRemoved = true
            }
        }
        return true
    }

    @Synchronized
    fun saveSnapshot(context: Context, json: String) = write(snapshotFile(context), json)

    @Synchronized
    fun snapshot(context: Context): String? = read(snapshotFile(context))
}

class OutboxWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val sent = try {
            Outbox.upload(applicationContext)
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            return@withContext Result.retry()
        }
        if (sent) Widgets.refreshLater(applicationContext, 90)
        Result.success()
    }
}
