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

    /** Напоминания о поездках и делах (локальные уведомления). */
    var notifyEnabled: Boolean
        get() = sp.getBoolean("notify_enabled", false)
        set(v) = sp.edit().putBoolean("notify_enabled", v).apply()

    /** Чьи поездки напоминать (id через запятую); пусто — всех. */
    var notifyPeople: String
        get() = sp.getString("notify_people", "") ?: ""
        set(v) = sp.edit().putString("notify_people", v).apply()

    /** За сколько минут напоминать о выезде. */
    var notifyLead: Int
        get() = sp.getInt("notify_lead", 30)
        set(v) = sp.edit().putInt("notify_lead", v).apply()

    /** Уже показанные напоминания (чтобы не повторять), последние 300. */
    var shownReminders: Set<String>
        get() = sp.getStringSet("shown_reminders", emptySet()) ?: emptySet()
        set(v) = sp.edit().putStringSet("shown_reminders", v.toList().takeLast(300).toSet()).apply()

    /** Напоминания, поставленные в будильник (чтобы снять устаревшие). */
    var scheduledReminders: Set<String>
        get() = sp.getStringSet("scheduled_reminders", emptySet()) ?: emptySet()
        set(v) = sp.edit().putStringSet("scheduled_reminders", v).apply()

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
