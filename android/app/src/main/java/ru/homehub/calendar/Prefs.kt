package ru.homehub.calendar

import android.content.Context

/** Настройки приложения и кэш данных для виджета. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("homehub", Context.MODE_PRIVATE)

    /** Адрес календаря, например http://192.168.0.188:8080 (без слеша в конце). */
    var server: String?
        get() = sp.getString("server", null)
        set(v) = sp.edit().putString("server", v).apply()

    /** Последний ответ /api/widget (JSON). */
    var widgetJson: String?
        get() = sp.getString("widget_json", null)
        set(v) = sp.edit().putString("widget_json", v).apply()

    /** Когда данные виджета последний раз удалось обновить (мс). */
    var lastOk: Long
        get() = sp.getLong("last_ok", 0)
        set(v) = sp.edit().putLong("last_ok", v).apply()

    /** Текст последней ошибки обновления или null. */
    var lastError: String?
        get() = sp.getString("last_error", null)
        set(v) = sp.edit().putString("last_error", v).apply()

    /** Версия, о которой уже напомнили (чтобы не спрашивать при каждом запуске). */
    var dismissedUpdate: Int
        get() = sp.getInt("dismissed_update", 0)
        set(v) = sp.edit().putInt("dismissed_update", v).apply()
}

/** Приводит ввод пользователя к адресу: «192.168.0.188» → «http://192.168.0.188:8080». */
fun normalizeServer(input: String): String? {
    var s = input.trim().trimEnd('/')
    if (s.isEmpty()) return null
    if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://$s"
    val hostPart = s.substringAfter("://").substringBefore("/")
    if (!hostPart.contains(":")) s = s.replaceFirst(hostPart, "$hostPart:8080")
    return s
}
