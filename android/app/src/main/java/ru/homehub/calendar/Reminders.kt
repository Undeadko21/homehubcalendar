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
import android.graphics.drawable.Icon
import org.json.JSONArray
import org.json.JSONObject
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

    fun show(context: Context, id: String, title: String, text: String, trip: String? = null) {
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
        tripActions(context, id, trip).forEach { n.addAction(it) }
        context.getSystemService(NotificationManager::class.java)?.notify(id.hashCode(), n.build())
    }

    /**
     * Кнопки в уведомлении «поездка без водителя / водитель занят» (сервер кладёт в напоминание поле trip).
     * «Отвезу я / Заберу я» — если на телефоне выбран один человек и он свободен; иначе — по имени свободных взрослых.
     * «Не могу» — снимает назначение с человека этого телефона (тогда остальные увидят «некому отвезти»), иначе просто скрывает.
     * Команда уходит в облако (как с офлайн-экрана), сервер применит её за минуту; без облака кнопка открывает приложение.
     */
    private fun tripActions(context: Context, id: String, tripJson: String?): List<Notification.Action> {
        val trip = tripJson?.let { runCatching { JSONObject(it) }.getOrNull() } ?: return emptyList()
        val prefs = Prefs(context)
        val wanted = prefs.notifyPeople.split(",").filter { it.isNotBlank() }
        val me = wanted.singleOrNull()
        val names = trip.optJSONObject("names") ?: JSONObject()
        val need = trip.optJSONArray("need") ?: return emptyList()
        val cloud = prefs.cloudToken != null && prefs.cloudKey != null
        val icon = Icon.createWithResource(context, R.drawable.ic_notify)
        val out = mutableListOf<Notification.Action>()
        fun act(label: String, role: String, person: String?, done: String) {
            if (out.size >= 2) return
            val pi = if (cloud) {
                val i = Intent(context, TripActionReceiver::class.java).setAction(TripActionReceiver.ACTION)
                    .setData(Uri.parse("homehub://trip/" + Uri.encode(id) + "/" + role + "/" + Uri.encode(person ?: "")))
                    .putExtra("nid", id.hashCode()).putExtra("uid", trip.optString("uid"))
                    .putExtra("occurrence", trip.optString("occurrence").takeIf { it.isNotEmpty() && it != "null" })
                    .putExtra("role", role).putExtra("person", person).putExtra("done", done)
                PendingIntent.getBroadcast(context, (id + role + person).hashCode(), i, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            } else {
                PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            }
            out += Notification.Action.Builder(icon, label, pi).build()
        }
        var cant: Pair<String, String>? = null
        for (k in 0 until need.length()) {
            val n = need.getJSONObject(k)
            val role = n.optString("role")
            val drop = role == "dropoff"
            val free = n.optJSONArray("free")?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()
            val assigned = n.optString("person").takeIf { it.isNotEmpty() && it != "null" }
            if (me != null && assigned == me) cant = cant ?: (role to me)
            if (me != null && me in free && assigned != me) {
                act(if (drop) "Отвезу я" else "Заберу я", role, me, if (drop) "Отвезёте вы" else "Заберёте вы")
            } else if (me == null) {
                free.firstOrNull { it != assigned }?.let { p ->
                    val name = names.optString(p, p)
                    act(if (drop) "Отвезёт $name" else "Заберёт $name", role, p, if (drop) "Отвезёт $name" else "Заберёт $name")
                }
            }
        }
        if (cloud && out.size < 3) {
            val i = Intent(context, TripActionReceiver::class.java).setAction(TripActionReceiver.ACTION)
                .setData(Uri.parse("homehub://trip/" + Uri.encode(id) + "/cant"))
                .putExtra("nid", id.hashCode()).putExtra("uid", trip.optString("uid"))
                .putExtra("occurrence", trip.optString("occurrence").takeIf { it.isNotEmpty() && it != "null" })
                .putExtra("role", cant?.first).putExtra("cant", true)
                .putExtra("done", if (cant != null) "Назначение снято — остальные увидят, что везти некому" else "Скрыто")
            val pi = PendingIntent.getBroadcast(context, (id + "cant").hashCode(), i, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            out += Notification.Action.Builder(icon, "Не могу", pi).build()
        }
        return out
    }

    private fun pending(context: Context, id: String, title: String = "", text: String = "", trip: String? = null): PendingIntent {
        val i = Intent(context, ReminderReceiver::class.java).setAction(ACTION)
            .setData(Uri.parse("homehub://reminder/" + Uri.encode(id)))
            .putExtra("id", id).putExtra("title", title).putExtra("text", text).putExtra("trip", trip)
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
            } else {
                if (r.optString("kind") == "event" && wanted.isNotEmpty()) {
                    // время считает сервер по настройкам человека; здесь только «чьи»
                    val who = r.optJSONArray("people")
                    if (who == null || (0 until who.length()).none { who.getString(it) in wanted }) continue
                }
                parse(r.optString("at"))
            }
            // Срочные предупреждения (поездка без водителя, дайджест) приходят, когда «пора» уже наступило, — им даём сутки.
            val urgent = r.optString("kind") in setOf("alert", "digest")
            if (at == null || now - at > (if (urgent) 24 else 3) * 3_600_000L) continue  // давно прошло или не разобрали
            val title = r.optString("title")
            val text = r.optString("text")
            val trip = r.optJSONObject("trip")?.toString()
            if (at <= now) {
                show(context, id, title, text, trip)
                shown += id
            } else {
                alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pending(context, id, title, text, trip))
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
        Reminders.show(context, id, intent.getStringExtra("title").orEmpty(), intent.getStringExtra("text").orEmpty(),
            intent.getStringExtra("trip"))
        prefs.shownReminders = prefs.shownReminders + id
        prefs.scheduledReminders = prefs.scheduledReminders - id
    }
}

/** Кнопка в уведомлении о поездке: команда escort в очередь облака и сразу отправка (в фоне, без открытия приложения). */
class TripActionReceiver : BroadcastReceiver() {
    companion object { const val ACTION = "ru.homehub.calendar.TRIP" }

    override fun onReceive(context: Context, intent: Intent) {
        val nm = context.getSystemService(NotificationManager::class.java)
        val nid = intent.getIntExtra("nid", 0)
        val uid = intent.getStringExtra("uid")
        val role = intent.getStringExtra("role")
        val cant = intent.getBooleanExtra("cant", false)
        val done = intent.getStringExtra("done") ?: "Готово"
        if (uid.isNullOrEmpty() || (cant && role == null)) {     // «Не могу», но это не назначение этого телефона — просто убрать
            nm?.cancel(nid)
            return
        }
        val op = JSONObject().put("type", "escort").put("uid", uid).put("role", role)
            .put("occurrence", intent.getStringExtra("occurrence") ?: JSONObject.NULL)
            .put("person", if (cant) JSONObject.NULL else (intent.getStringExtra("person") ?: JSONObject.NULL))
        Outbox.add(context, op)
        val result = goAsync()
        Thread {
            val sent = runCatching { Outbox.push(context) }.getOrDefault(false)
            val n = Notification.Builder(context, "reminders")
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle(done)
                .setContentText(if (sent) "Отправлено, календарь обновится в течение минуты" else "Нет связи — отправлю при следующем обновлении")
                .setColor(context.getColor(R.color.red))
                .setTimeoutAfter(15_000)
                .setAutoCancel(true)
                .build()
            nm?.notify(nid, n)
            if (sent) Widgets.refreshLater(context, 90)
            result.finish()
        }.start()
    }
}
