package ru.homehub.calendar

import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.app.Notification
import org.json.JSONArray
import java.time.OffsetDateTime

/**
 * Напоминания: сервер считает, что и когда напомнить (снимок), приложение раз в 15 минут (Sync)
 * забирает список и ставит локальные уведомления через AlarmManager. Дома — с сервера, вне дома — из облака.
 */
object Reminders {
    private const val CHANNEL = "reminders"
    const val ACTION = "ru.homehub.calendar.REMIND"

    /** Выключили напоминания — снимаем уже поставленные. Проверка идёт в общем обновлении (Sync). */
    fun schedule(context: Context) {
        if (!Prefs(context).notifyEnabled) cancelAll(context)
    }

    fun checkNow(context: Context) {
        if (Prefs(context).notifyEnabled) Widgets.refreshNow(context)
    }

    fun notificationsAllowed(context: Context): Boolean =
        context.getSystemService(NotificationManager::class.java)?.areNotificationsEnabled() ?: true

    private fun channel(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java) ?: return
        if (nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, "Напоминания", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "Поездки, конфликты и дни рождения"
                },
            )
        }
    }

    fun show(context: Context, id: String, title: String, text: String) {
        channel(context)
        val open = PendingIntent.getActivity(
            context, 0, Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val n = Notification.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(title)
            .setContentText(text.lineSequence().firstOrNull().orEmpty())
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setColor(context.getColor(R.color.red))
            .build()
        context.getSystemService(NotificationManager::class.java)?.notify(id.hashCode(), n)
    }

    private fun pending(context: Context, id: String, title: String = "", text: String = ""): PendingIntent {
        val i = Intent(context, ReminderReceiver::class.java).setAction(ACTION)
            .setData(Uri.parse("homehub://reminder/" + Uri.encode(id)))
            .putExtra("id", id).putExtra("title", title).putExtra("text", text)
        return PendingIntent.getBroadcast(context, 0, i, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private fun cancel(context: Context, id: String) {
        context.getSystemService(AlarmManager::class.java)?.cancel(pending(context, id))
    }

    fun cancelAll(context: Context) {
        val prefs = Prefs(context)
        prefs.scheduledReminders.forEach { cancel(context, it) }
        prefs.scheduledReminders = emptySet()
    }

    /**
     * Разбирает напоминания из снимка. У поездок (duty) время «за N минут» и чьи они — настройки этого телефона,
     * остальные виды приходят с готовым временем. Недавно прошедшие показывает сразу, будущие ставит в будильник.
     */
    fun apply(context: Context, items: JSONArray) {
        val prefs = Prefs(context)
        val alarms = context.getSystemService(AlarmManager::class.java) ?: return
        val now = System.currentTimeMillis()
        val wanted = prefs.notifyPeople.split(",").filter { it.isNotBlank() }.toSet()
        val shown = prefs.shownReminders.toMutableSet()
        val scheduled = mutableSetOf<String>()
        for (k in 0 until items.length()) {
            val r = items.getJSONObject(k)
            val id = r.getString("id")
            if (id in shown) continue
            val at: Long? = if (r.optString("kind") == "duty") {
                if (wanted.isNotEmpty()) {
                    val who = r.optJSONArray("people")
                    if (who == null || (0 until who.length()).none { who.getString(it) in wanted }) continue
                }
                parse(r.optString("start"))?.minus(prefs.notifyLead * 60_000L)
            } else parse(r.optString("at"))
            if (at == null || now - at > 3 * 3_600_000L) continue  // давно прошло или не разобрали
            val title = r.optString("title")
            val text = r.optString("text")
            if (at <= now) {
                show(context, id, title, text)
                shown += id
            } else {
                alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pending(context, id, title, text))
                scheduled += id
            }
        }
        // Напоминания, которые снимок больше не содержит (отменили поездку), снимаем.
        (prefs.scheduledReminders - scheduled).forEach { cancel(context, it) }
        prefs.scheduledReminders = scheduled
        prefs.shownReminders = shown
    }

    private fun parse(s: String): Long? =
        runCatching { OffsetDateTime.parse(s).toInstant().toEpochMilli() }.getOrNull()
}

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getStringExtra("id") ?: return
        val prefs = Prefs(context)
        if (!prefs.notifyEnabled || id in prefs.shownReminders) return
        Reminders.show(context, id, intent.getStringExtra("title").orEmpty(), intent.getStringExtra("text").orEmpty())
        prefs.shownReminders = prefs.shownReminders + id
        prefs.scheduledReminders = prefs.scheduledReminders - id
    }
}
