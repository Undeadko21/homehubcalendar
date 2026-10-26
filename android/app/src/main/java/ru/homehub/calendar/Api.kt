package ru.homehub.calendar

import android.content.Context
import android.net.ConnectivityManager
import android.webkit.CookieManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.URL

class ApiException(message: String, val needLogin: Boolean = false) : Exception(message)

object Api {
    /** GET-запрос к календарю. Куки (PIN) берём из WebView — вход один на приложение. */
    fun get(base: String, path: String, timeoutMs: Int = 8000): String {
        val url = URL(base + path)
        val c = url.openConnection() as HttpURLConnection
        c.connectTimeout = timeoutMs
        c.readTimeout = timeoutMs
        c.setRequestProperty("Accept", "application/json")
        CookieManager.getInstance().getCookie(base)?.let { c.setRequestProperty("Cookie", it) }
        try {
            val code = c.responseCode
            if (code == 401) throw ApiException("Нужен PIN — откройте приложение и войдите", needLogin = true)
            if (code !in 200..299) throw ApiException("Сервер ответил $code")
            return c.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            c.disconnect()
        }
    }

    /** Проверка, что по адресу отвечает именно наш календарь. Возвращает версию сервера или null. */
    fun probe(base: String, timeoutMs: Int = 700): String? = try {
        val j = JSONObject(get(base, "/api/health", timeoutMs))
        if (j.optBoolean("ok")) j.optString("version", "?") else null
    } catch (e: Exception) {
        null
    }

    /** Информация о свежей версии приложения на сервере: (versionCode, versionName) или null. */
    fun appVersion(base: String): Pair<Int, String>? = try {
        val j = JSONObject(get(base, "/api/app", 5000))
        if (j.optBoolean("available")) j.getInt("versionCode") to j.optString("versionName") else null
    } catch (e: Exception) {
        null
    }

    /** Префикс локальной сети телефона, например «192.168.0.» — из активного подключения. */
    fun localPrefix(context: Context): String? {
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return null
        val lp = cm.getLinkProperties(cm.activeNetwork) ?: return null
        val addr = lp.linkAddresses.map { it.address }.firstOrNull { it is Inet4Address && !it.isLoopbackAddress }
            ?: return null
        val ip = addr.hostAddress ?: return null
        return ip.substringBeforeLast('.') + "."
    }

    /** Ищет календарь в /24-подсети телефона на портах 8080 и 80. */
    suspend fun discover(context: Context, onProgress: (Int, Int) -> Unit): List<Pair<String, String>> =
        withContext(Dispatchers.IO) {
            val prefix = localPrefix(context) ?: throw ApiException("Нет подключения к Wi-Fi")
            val candidates = (1..254).flatMap { listOf("http://$prefix$it:8080", "http://$prefix$it") }
            val sem = Semaphore(48)
            var done = 0
            coroutineScope {
                candidates.map { base ->
                    async {
                        sem.withPermit {
                            val v = probe(base)
                            synchronized(this@Api) { done++; onProgress(done, candidates.size) }
                            if (v != null) base to v else null
                        }
                    }
                }.awaitAll().filterNotNull()
            }
        }
}
