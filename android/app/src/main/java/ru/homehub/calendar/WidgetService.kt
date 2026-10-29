package ru.homehub.calendar

import android.content.Context
import android.content.Intent
import android.appwidget.AppWidgetManager
import android.graphics.Color
import android.util.TypedValue
import android.view.View
import android.widget.RemoteViews
import android.widget.RemoteViewsService
import org.json.JSONObject
import java.time.OffsetDateTime

class WidgetService : RemoteViewsService() {
    override fun onGetViewFactory(intent: Intent): RemoteViewsFactory = Factory(applicationContext, intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, 0))
}

/** Строка списка: заголовок дня или событие. */
private sealed class Row {
    data class Day(val label: String) : Row()
    data class Ev(val j: JSONObject) : Row()
}

private class Factory(private val context: Context, private val widgetId: Int) : RemoteViewsService.RemoteViewsFactory {
    private var rows: List<Row> = emptyList()
    private var cfg = WidgetCfg()

    override fun onCreate() {}
    override fun onDestroy() {}
    override fun getCount() = rows.size
    override fun getLoadingView(): RemoteViews? = null
    override fun getViewTypeCount() = 2
    override fun getItemId(position: Int) = position.toLong()
    override fun hasStableIds() = false

    override fun onDataSetChanged() {
        cfg = WidgetPrefs(context).get(widgetId)
        val json = Prefs(context).widgetJson ?: run { rows = emptyList(); return }
        val out = mutableListOf<Row>()
        val now = OffsetDateTime.now()
        try {
            val root = JSONObject(json)
            // Ближайшие дни рождения — строкой над списком.
            root.optJSONArray("birthdays")?.let { b ->
                for (i in 0 until b.length()) out += Row.Day(b.getJSONObject(i).optString("text"))
            }
            val days = root.getJSONArray("days")
            for (i in 0 until minOf(days.length(), cfg.days)) {
                val d = days.getJSONObject(i)
                val evs = d.getJSONArray("events")
                val list = (0 until evs.length()).map { evs.getJSONObject(it) }.filter { e ->
                    // Пока кэш не обновился, прячем уже закончившиеся события.
                    e.optBoolean("all_day") || runCatching { OffsetDateTime.parse(e.getString("end")).isAfter(now) }.getOrDefault(true)
                }
                if (list.isEmpty()) continue
                out += Row.Day(d.getString("label"))
                list.forEach { out += Row.Ev(it) }
            }
        } catch (_: Exception) {
        }
        // Если на сегодня ничего не осталось, первым будет «Завтра…» — это нормально.
        rows = out
    }

    override fun getViewAt(position: Int): RemoteViews {
        return when (val row = rows.getOrNull(position)) {
            is Row.Day -> RemoteViews(context.packageName, R.layout.widget_day).apply {
                setTextViewText(R.id.d_label, row.label)
                setTextViewTextSize(R.id.d_label, TypedValue.COMPLEX_UNIT_SP, 12f * cfg.scale / 100f)
            }
            is Row.Ev -> eventView(row.j)
            null -> RemoteViews(context.packageName, R.layout.widget_day)
        }
    }

    private fun eventView(e: JSONObject): RemoteViews {
        val rv = RemoteViews(context.packageName, R.layout.widget_item)
        val allDay = e.optBoolean("all_day")
        val time = e.optString("time")
        if (allDay) {
            rv.setTextViewText(R.id.i_start, "весь")
            rv.setTextViewText(R.id.i_end, "день")
        } else {
            rv.setTextViewText(R.id.i_start, time.substringBefore("–"))
            rv.setTextViewText(R.id.i_end, time.substringAfter("–", ""))
        }
        val colors = e.optJSONArray("colors")
        val color = runCatching { Color.parseColor(colors?.getString(0)) }.getOrDefault(Color.GRAY)
        rv.setInt(R.id.i_bar, "setColorFilter", color)

        val k = cfg.scale / 100f
        rv.setTextViewTextSize(R.id.i_start, TypedValue.COMPLEX_UNIT_SP, 13f * k)
        rv.setTextViewTextSize(R.id.i_end, TypedValue.COMPLEX_UNIT_SP, 12f * k)
        rv.setTextViewTextSize(R.id.i_title, TypedValue.COMPLEX_UNIT_SP, 14f * k)
        rv.setTextViewTextSize(R.id.i_sub, TypedValue.COMPLEX_UNIT_SP, 12f * k)
        rv.setTextViewTextSize(R.id.i_note, TypedValue.COMPLEX_UNIT_SP, 12f * k)
        rv.setTextViewText(R.id.i_title, e.optString("title"))
        val sub = if (!cfg.details) "" else
            listOf(e.optString("who"), e.optString("location")).filter { it.isNotBlank() }.joinToString(" · ")
        rv.setTextViewText(R.id.i_sub, sub)
        rv.setViewVisibility(R.id.i_sub, if (sub.isBlank()) View.GONE else View.VISIBLE)

        val note = e.optString("note")
        val issue = e.optString("issue").takeIf { it.isNotBlank() && it != "null" }
        rv.setTextViewText(R.id.i_note, if (e.optBoolean("now")) listOf("сейчас", note).filter { it.isNotBlank() }.joinToString("  ") else note)
        rv.setViewVisibility(R.id.i_note, if (note.isBlank() && !e.optBoolean("now")) View.GONE else View.VISIBLE)
        rv.setTextColor(
            R.id.i_note,
            context.getColor(
                when (issue) {
                    "conflict" -> R.color.red
                    "unassigned" -> R.color.warn
                    else -> if (e.optBoolean("now")) R.color.red else R.color.ink2
                },
            ),
        )
        rv.setViewVisibility(R.id.i_badge, if (issue == "conflict") View.VISIBLE else View.GONE)
        rv.setOnClickFillInIntent(R.id.item_root, Intent().putExtra("event", e.optString("id")))
        return rv
    }
}
