package ru.homehub.calendar

import android.content.Context
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Очередь команд, сделанных вне дома. Команда живёт в очереди, пока сервер не подтвердит её в снимке
 * (поле applied); весь список шифруется и выгружается в облако файлом ops-<телефон>.bin.
 */
object Outbox {
    private fun file(context: Context) = File(context.filesDir, "ops.json")
    private fun snapshotFile(context: Context) = File(context.filesDir, "snapshot.json")

    @Synchronized
    fun pending(context: Context): JSONArray =
        runCatching { JSONArray(file(context).readText()) }.getOrDefault(JSONArray())

    @Synchronized
    private fun save(context: Context, list: JSONArray) = file(context).writeText(list.toString())

    /** Добавляет команду и возвращает её id. */
    @Synchronized
    fun add(context: Context, op: JSONObject): String {
        val id = Prefs(context).deviceId + "-" + System.currentTimeMillis() + "-" + (Math.random() * 1000).toInt()
        op.put("id", id).put("t", System.currentTimeMillis())
        val list = pending(context)
        list.put(op)
        save(context, list)
        Prefs(context).outboxDirty = true
        return id
    }

    /** Убирает из очереди команды, которые сервер уже применил. */
    @Synchronized
    fun dropApplied(context: Context, applied: Set<String>) {
        val list = pending(context)
        val keep = JSONArray()
        for (i in 0 until list.length()) {
            val o = list.getJSONObject(i)
            if (o.optString("id") !in applied) keep.put(o)
        }
        if (keep.length() != list.length()) save(context, keep)
    }

    /** Выгружает очередь в облако, если она менялась и есть токен записи. Возвращает true, если выгрузили. */
    fun push(context: Context): Boolean {
        val prefs = Prefs(context)
        val token = prefs.cloudToken
        val key = prefs.cloudKey
        if (!prefs.outboxDirty || token == null || key == null) return false
        val bytes = Cloud.encrypt(Base64.decode(key, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP), pending(context).toString())
        Cloud.upload(token, "ops-${prefs.deviceId}.bin", bytes)
        prefs.outboxDirty = false
        return true
    }

    fun saveSnapshot(context: Context, json: String) = snapshotFile(context).writeText(json)
    fun snapshot(context: Context): String? = snapshotFile(context).takeIf { it.exists() }?.readText()
}
