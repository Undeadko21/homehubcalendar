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
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.time.OffsetDateTime
import java.util.concurrent.TimeUnit

/**
 * Напоминания: сервер считает, что и когда напомнить (/api/reminders), приложение раз в 15 минут
 * забирает список и ставит локальные уведомления через AlarmManager. Интернет снаружи не нужен.
 */
object Reminders {
    private const val CHANNEL = "reminders"
    private const val PERIODIC = "reminders-periodic"
    private const val NOW = "reminders-now"
    const val ACTION = "ru.homehub.calendar.REMIND"

    /** Включить или выключить периодическую проверку согласно настройке. */
    fun schedule(context: Context) {
        val wm = WorkManager.getInstance(context)
        if (!Prefs(context).notifyEnabled) {
            wm.cancelUniqueWork(PERIODIC)
            cancelAll(context)
            return
        }
        val req = PeriodicWorkRequestBuilder<ReminderWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        wm.enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.UPDATE, req)
    }

    fun checkNow(context: Context) {
        if (!Prefs(context).notifyEnabled) return
        WorkManager.getInstance(context)
            .enqueueUniqueWork(NOW, ExistingWorkPolicy.REPLACE, OneTimeWorkRequestBuilder<ReminderWorker>().build())
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

    /** Разбирает ответ сервера: прошедшие недавно показывает сразу, будущие ставит в будильник. */
    fun apply(context: Context, json: String) {
        val prefs = Prefs(context)
        val alarms = context.getSystemService(AlarmManager::class.java) ?: return
        val items = JSONObject(json).getJSONArray("items")
        val now = System.currentTimeMillis()
        val shown = prefs.shownReminders.toMutableSet()
        val scheduled = mutableSetOf<String>()
        for (k in 0 until items.length()) {
            val r = items.getJSONObject(k)
            val id = r.getString("id")
            if (id in shown) continue
            val at = runCatching { OffsetDateTime.parse(r.getString("at")).toInstant().toEpochMilli() }.getOrNull() ?: continue
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
        // Напоминания, которые сервер больше не присылает (отменили поездку), снимаем.
        (prefs.scheduledReminders - scheduled).forEach { cancel(context, it) }
        prefs.scheduledReminders = scheduled
        prefs.shownReminders = shown
    }
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

class ReminderWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val prefs = Prefs(applicationContext)
        if (!prefs.notifyEnabled) return Result.success()
        val base = prefs.server ?: return Result.success()
        withContext(Dispatchers.IO) {
            try {
                val people = Uri.encode(prefs.notifyPeople)
                Reminders.apply(applicationContext, Api.get(base, "/api/reminders?hours=36&lead=${prefs.notifyLead}&people=$people"))
            } catch (_: Exception) {
                // Нет связи с домом — попробуем в следующий раз; уже поставленные напоминания остаются.
            }
        }
        return Result.success()
    }
}
