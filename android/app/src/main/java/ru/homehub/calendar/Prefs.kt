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

    /** Облачный снимок на Яндекс.Диске: публичная ссылка и ключ шифрования (base64url). */
    var cloudUrl: String?
        get() = sp.getString("cloud_url", null)
        set(v) = sp.edit().putString("cloud_url", v).apply()

    var cloudKey: String?
        get() = sp.getString("cloud_key", null)
        set(v) = sp.edit().putString("cloud_key", v).apply()

    /** Токен записи в папку приложения на Диске (из кода подключения): для команд вне дома. */
    var cloudToken: String?
        get() = sp.getString("cloud_token", null)
        set(v) = sp.edit().putString("cloud_token", v).apply()

    /** Случайное имя этого телефона для файла команд ops-<id>.bin. */
    val deviceId: String
        get() = sp.getString("device_id", null) ?: java.util.UUID.randomUUID().toString().take(8)
            .also { sp.edit().putString("device_id", it).apply() }

    /** Очередь команд изменилась и ещё не выгружена в облако. */
    var outboxDirty: Boolean
        get() = sp.getBoolean("outbox_dirty", false)
        set(v) = sp.edit().putBoolean("outbox_dirty", v).apply()

    /** Откуда взяты последние данные: "home" или "cloud". */
    var dataSource: String
        get() = sp.getString("data_source", "home") ?: "home"
        set(v) = sp.edit().putString("data_source", v).apply()

    /** Версия, о которой уже напомнили (чтобы не спрашивать при каждом запуске). */
    var dismissedUpdate: Int
        get() = sp.getInt("dismissed_update", 0)
        set(v) = sp.edit().putInt("dismissed_update", v).apply()
}

/** Настройки одного виджета на рабочем столе (у каждого свои). */
data class WidgetCfg(
    val scale: Int = 100,       // размер текста, %
    val opacity: Int = 100,     // непрозрачность фона, %
    val days: Int = 2,          // сколько дней показывать (1–3)
    val details: Boolean = true, // кто и где под названием
    val header: Int = 0,        // 0 — по размеру виджета, 1 — всегда, 2 — скрыть
)

class WidgetPrefs(context: Context) {
    private val sp = context.getSharedPreferences("widgets", Context.MODE_PRIVATE)

    fun get(id: Int) = WidgetCfg(
        scale = sp.getInt("$id.scale", 100), opacity = sp.getInt("$id.opacity", 100),
        days = sp.getInt("$id.days", 2), details = sp.getBoolean("$id.details", true),
        header = sp.getInt("$id.header", 0),
    )

    fun put(id: Int, c: WidgetCfg) {
        sp.edit().putInt("$id.scale", c.scale).putInt("$id.opacity", c.opacity).putInt("$id.days", c.days)
            .putBoolean("$id.details", c.details).putInt("$id.header", c.header).apply()
    }

    fun remove(id: Int) {
        sp.edit().apply { listOf("scale", "opacity", "days", "details", "header").forEach { remove("$id.$it") } }.apply()
    }
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
