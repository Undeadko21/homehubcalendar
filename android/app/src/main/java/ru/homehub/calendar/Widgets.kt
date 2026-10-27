package ru.homehub.calendar

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.view.View
import android.widget.RemoteViews
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
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

object Widgets {
    private const val PERIODIC = "widget-periodic"
    private const val NOW = "widget-now"
    const val ACTION_REFRESH = "ru.homehub.calendar.REFRESH"

    /** Фоновое обновление каждые 15 минут (минимум, который разрешает Android). */
    fun schedule(context: Context) {
        val req = PeriodicWorkRequestBuilder<RefreshWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.UPDATE, req)
    }

    fun refreshNow(context: Context) {
        WorkManager.getInstance(context)
            .enqueueUniqueWork(NOW, ExistingWorkPolicy.REPLACE, OneTimeWorkRequestBuilder<RefreshWorker>().build())
    }

    /** Повторная проверка через некоторое время (например, подтверждение отправленных команд). */
    fun refreshLater(context: Context, seconds: Long) {
        WorkManager.getInstance(context).enqueueUniqueWork(
            "widget-later", ExistingWorkPolicy.REPLACE,
            OneTimeWorkRequestBuilder<RefreshWorker>().setInitialDelay(seconds, TimeUnit.SECONDS)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build(),
        )
    }

    fun canPin(context: Context): Boolean =
        AppWidgetManager.getInstance(context).isRequestPinAppWidgetSupported

    /** Просит лаунчер поставить виджет на рабочий стол (Android 8+, если лаунчер умеет). */
    fun pin(context: Context): Boolean {
        val mgr = AppWidgetManager.getInstance(context)
        if (!mgr.isRequestPinAppWidgetSupported) return false
        return mgr.requestPinAppWidget(ComponentName(context, WidgetProvider::class.java), null, null)
    }

    fun ids(context: Context): IntArray =
        AppWidgetManager.getInstance(context).getAppWidgetIds(ComponentName(context, WidgetProvider::class.java))

    /** Перерисовать все виджеты из кэша. */
    fun renderAll(context: Context) {
        val mgr = AppWidgetManager.getInstance(context)
        val ids = ids(context)
        ids.forEach { mgr.updateAppWidget(it, build(context, it)) }
        mgr.notifyAppWidgetViewDataChanged(ids, R.id.w_list)
    }

    private fun build(context: Context, id: Int): RemoteViews {
        val prefs = Prefs(context)
        val rv = RemoteViews(context.packageName, R.layout.widget)
        val now = Date()
        val ru = Locale("ru")
        rv.setTextViewText(R.id.w_weekday, SimpleDateFormat("EEEE", ru).format(now).uppercase(ru))
        rv.setTextViewText(R.id.w_date, SimpleDateFormat("d MMMM", ru).format(now))

        val status = when {
            prefs.server == null -> "не подключено"
            prefs.lastOk == 0L -> prefs.lastError?.let { "нет связи" } ?: "загрузка…"
            prefs.lastError != null && now.time - prefs.lastOk > 45 * 60_000 ->
                "нет связи с " + SimpleDateFormat("HH:mm", ru).format(Date(prefs.lastOk))
            prefs.dataSource == "cloud" -> "облако " + SimpleDateFormat("HH:mm", ru).format(Date(prefs.lastOk))
            else -> SimpleDateFormat("HH:mm", ru).format(Date(prefs.lastOk))
        }
        rv.setTextViewText(R.id.w_status, status)

        // Список событий
        val svc = Intent(context, WidgetService::class.java).apply {
            putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id)
            data = Uri.parse(toUri(Intent.URI_INTENT_SCHEME))
        }
        rv.setRemoteAdapter(R.id.w_list, svc)
        rv.setEmptyView(R.id.w_list, R.id.w_empty)
        rv.setTextViewText(
            R.id.w_empty,
            when {
                prefs.server == null -> "Откройте приложение, чтобы подключиться к календарю"
                prefs.widgetJson == null -> prefs.lastError ?: "Загружаю…"
                else -> "Сегодня и завтра свободно"
            },
        )

        val open = PendingIntent.getActivity(
            context, 0, Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        rv.setOnClickPendingIntent(R.id.w_head, open)
        rv.setOnClickPendingIntent(R.id.w_empty, open)
        rv.setPendingIntentTemplate(
            R.id.w_list,
            PendingIntent.getActivity(
                context, 1, Intent(context, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
            ),
        )
        val refresh = PendingIntent.getBroadcast(
            context, 2, Intent(context, WidgetProvider::class.java).setAction(ACTION_REFRESH),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        rv.setOnClickPendingIntent(R.id.w_refresh, refresh)
        rv.setViewVisibility(R.id.w_refresh, if (prefs.server == null) View.GONE else View.VISIBLE)
        return rv
    }
}

/** Обновляет данные (дом или облако), виджет и напоминания. */
class RefreshWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        withContext(Dispatchers.IO) { Sync.run(applicationContext) }
        return Result.success()
    }
}
