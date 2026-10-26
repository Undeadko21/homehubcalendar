package ru.homehub.calendar

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.view.View
import android.widget.RemoteViews
import android.widget.RemoteViewsService
import org.json.JSONObject
import java.time.OffsetDateTime

class WidgetService : RemoteViewsService() {
    override fun onGetViewFactory(intent: Intent): RemoteViewsFactory = Factory(applicationContext)
}

/** Строка списка: заголовок дня или событие. */
private sealed class Row {
    data class Day(val label: String) : Row()
    data class Ev(val j: JSONObject) : Row()
}

private class Factory(private val context: Context) : RemoteViewsService.RemoteViewsFactory {
    private var rows: List<Row> = emptyList()

    override fun onCreate() {}
    override fun onDestroy() {}
    override fun getCount() = rows.size
    override fun getLoadingView(): RemoteViews? = null
    override fun getViewTypeCount() = 2
    override fun getItemId(position: Int) = position.toLong()
    override fun hasStableIds() = false

    override fun onDataSetChanged() {
        val json = Prefs(context).widgetJson ?: run { rows = emptyList(); return }
        val out = mutableListOf<Row>()
        val now = OffsetDateTime.now()
        try {
            val days = JSONObject(json).getJSONArray("days")
            for (i in 0 until days.length()) {
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

        rv.setTextViewText(R.id.i_title, e.optString("title"))
        val sub = listOf(e.optString("who"), e.optString("location")).filter { it.isNotBlank() }.joinToString(" · ")
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
