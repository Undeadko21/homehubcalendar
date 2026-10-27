package ru.homehub.calendar

import android.util.Base64
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * Снимок на Яндекс.Диске: зашифрованный файл, который сервер кладёт по публичной ссылке.
 * Читаем без аккаунта и без кук (в сторонние сервисы куки календаря не отправляем).
 */
object Cloud {
    private const val API = "https://cloud-api.yandex.net/v1/disk/public/resources/download"

    data class Code(val url: String, val key: String, val token: String?)

    /** Код подключения «hhc1.…» → ссылка, ключ base64url и (необязательно) токен записи, или null. */
    fun parseCode(code: String): Code? = runCatching {
        val body = code.trim().removePrefix("hhc1.")
        val j = JSONObject(String(Base64.decode(body, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP), Charsets.UTF_8))
        val url = j.getString("u")
        val key = j.getString("k")
        if (url.startsWith("https://") && key.isNotEmpty()) Code(url, key, j.optString("t").ifEmpty { null }) else null
    }.getOrNull()

    private fun download(url: String, timeoutMs: Int = 12000): ByteArray {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = timeoutMs
        c.readTimeout = timeoutMs
        try {
            if (c.responseCode !in 200..299) throw ApiException("Облако ответило ${c.responseCode}")
            return c.inputStream.use { it.readBytes() }
        } finally {
            c.disconnect()
        }
    }

    fun decrypt(key: ByteArray, blob: ByteArray): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, blob, 0, 12))
        cipher.updateAAD("homehub-v1".toByteArray())
        return String(cipher.doFinal(blob, 12, blob.size - 12), Charsets.UTF_8)
    }

    /** Шифрование как на сервере: nonce(12) + AES-256-GCM, AAD «homehub-v1». */
    fun encrypt(key: ByteArray, plain: String, nonce: ByteArray = ByteArray(12).also { java.security.SecureRandom().nextBytes(it) }): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
        cipher.updateAAD("homehub-v1".toByteArray())
        return nonce + cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
    }

    /** Кладёт файл в папку приложения на Диске (перезаписывает). Нужен токен записи. */
    fun upload(token: String, name: String, data: ByteArray) {
        val q = URLEncoder.encode("app:/$name", "UTF-8")
        val c = URL("https://cloud-api.yandex.net/v1/disk/resources/upload?path=$q&overwrite=true").openConnection() as HttpURLConnection
        c.connectTimeout = 12000; c.readTimeout = 12000
        c.setRequestProperty("Authorization", "OAuth $token")
        val href = try {
            when (c.responseCode) {
                401, 403 -> throw ApiException("Токен записи в облако не подошёл")
                !in 200..299 -> throw ApiException("Облако ответило ${c.responseCode}")
            }
            JSONObject(c.inputStream.use { String(it.readBytes(), Charsets.UTF_8) }).getString("href")
        } finally { c.disconnect() }
        val put = URL(href).openConnection() as HttpURLConnection
        try {
            put.requestMethod = "PUT"; put.doOutput = true; put.connectTimeout = 15000; put.readTimeout = 15000
            put.outputStream.use { it.write(data) }
            if (put.responseCode !in 200..299) throw ApiException("Не удалось загрузить файл: ${put.responseCode}")
        } finally { put.disconnect() }
    }

    /** Скачивает и расшифровывает снимок. Бросает исключение, если облако недоступно или ключ не подошёл. */
    fun fetch(publicUrl: String, keyB64: String): String {
        val meta = String(download(API + "?public_key=" + URLEncoder.encode(publicUrl, "UTF-8")), Charsets.UTF_8)
        val href = JSONObject(meta).getString("href")
        val key = Base64.decode(keyB64, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
        return decrypt(key, download(href))
    }
}
