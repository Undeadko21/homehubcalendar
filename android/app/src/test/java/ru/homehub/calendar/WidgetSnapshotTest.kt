package ru.homehub.calendar

import android.graphics.Color
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import com.android.resources.NightMode
import org.junit.Rule
import org.junit.Test

/** Снимок виджета с примером данных: шапка + строки, собранные из тех же макетов. */
class WidgetSnapshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_5, theme = "AppTheme")

    private data class Ev(val start: String, val end: String, val title: String, val sub: String,
                          val note: String = "", val color: String, val issue: String? = null, val now: Boolean = false)

    private fun widget(inflater: LayoutInflater): View {
        val frame = inflater.inflate(R.layout.widget, null)
        val root = frame.findViewById<LinearLayout>(R.id.w_content)
        root.findViewById<TextView>(R.id.w_weekday).text = "ПОНЕДЕЛЬНИК"
        root.findViewById<TextView>(R.id.w_date).text = "2"
        root.findViewById<TextView>(R.id.w_status).text = "12:41"
        val list = root.findViewById<View>(R.id.w_list)
        val idx = root.indexOfChild(list)
        root.removeView(list)
        root.findViewById<View>(R.id.w_empty).visibility = View.GONE
        val col = LinearLayout(root.context).apply { orientation = LinearLayout.VERTICAL }
        fun day(label: String) = (inflater.inflate(R.layout.widget_day, col, false) as TextView).also { it.text = label; col.addView(it) }
        val dark = paparazzi.resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK == android.content.res.Configuration.UI_MODE_NIGHT_YES
        fun ev(e: Ev) {
            val v = inflater.inflate(R.layout.widget_item, col, false)
            val chip = ChipStyle.colors(v.context, e.color, strong = e.now, dark = dark)
            v.findViewById<ImageView>(R.id.i_fill).apply { setColorFilter(chip.bar); imageAlpha = chip.fillAlpha }
            v.findViewById<ImageView>(R.id.i_bar).setColorFilter(chip.bar)
            v.findViewById<TextView>(R.id.i_title).apply { text = e.title; setTextColor(chip.text) }
            val time = v.findViewById<TextView>(R.id.i_time)
            time.text = ChipStyle.timeText(e.start + "–" + e.end).takeIf { e.start != "весь" } ?: ""
            time.setTextColor(chip.time)
            time.visibility = if (time.text.isBlank()) View.GONE else View.VISIBLE
            v.findViewById<TextView>(R.id.i_sub).apply { text = e.sub; setTextColor(chip.sub) }
            val note = v.findViewById<TextView>(R.id.i_note)
            val text = if (e.now) listOf("сейчас", e.note).filter { it.isNotBlank() }.joinToString("  ") else e.note
            note.text = text
            note.visibility = if (text.isBlank()) View.GONE else View.VISIBLE
            note.setTextColor(v.context.getColor(when (e.issue) { "conflict" -> R.color.red; "unassigned" -> R.color.warn; else -> if (e.now) R.color.red else R.color.ink2 }))
            v.findViewById<View>(R.id.i_badge).visibility = if (e.issue == "conflict") View.VISIBLE else View.GONE
            col.addView(v)
        }
        ev(Ev("21:20", "21:40", "Виза", "Оля", color = "#FF2D55", now = true))
        ev(Ev("13:00", "14:00", "Daily xVR (Команда)", "Толик · Собрание Microsoft Teams", color = "#34C759"))
        ev(Ev("17:30", "18:00", "Отвезти Марка: Ушу", "Оля", color = "#FF2D55", issue = "conflict"))
        ev(Ev("18:00", "19:00", "Ушу Марк", "Марк", "→ Оля  ← кто?", "#007AFF", "unassigned"))
        day("ЗАВТРА")
        ev(Ev("весь", "день", "ДР бабушки", "Оля, Толик, Марк", color = "#FF9500"))
        ev(Ev("10:40", "11:40", "Гитара", "Марк", color = "#34C759"))
        ev(Ev("14:00", "14:45", "Обсуждение итогов", "Оля", color = "#FF3B30"))
        root.addView(col, idx, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        return frame
    }

    /** Широкий виджет: две колонки, сегодня и завтра. */
    private fun cols(inflater: LayoutInflater): View {
        val frame = inflater.inflate(R.layout.widget_cols, null)
        frame.findViewById<TextView>(R.id.w_weekday).text = "ВТОРНИК"
        frame.findViewById<TextView>(R.id.w_date).text = "3"
        frame.findViewById<TextView>(R.id.w_title2).text = "ЗАВТРА"
        frame.findViewById<TextView>(R.id.w_status).text = "09:58"
        fun fill(listId: Int, emptyId: Int, items: List<Ev>) {
            val list = frame.findViewById<View>(listId)
            val parent = list.parent as LinearLayout
            val idx = parent.indexOfChild(list)
            parent.removeView(list)
            frame.findViewById<View>(emptyId).visibility = View.GONE
            val col = LinearLayout(parent.context).apply { orientation = LinearLayout.VERTICAL }
            items.forEach { e ->
                val v = inflater.inflate(R.layout.widget_item, col, false)
                val chip = ChipStyle.colors(v.context, e.color, dark = false)
                val allDay = e.start == "весь"
                v.findViewById<ImageView>(R.id.i_fill).apply { setImageResource(if (allDay) R.drawable.chip_pill else R.drawable.chip_bg); setColorFilter(chip.bar); imageAlpha = chip.fillAlpha }
                v.findViewById<ImageView>(R.id.i_bar).apply { setColorFilter(chip.bar); visibility = if (allDay) View.GONE else View.VISIBLE }
                v.findViewById<TextView>(R.id.i_title).apply { text = e.title; setTextColor(chip.text) }
                v.findViewById<TextView>(R.id.i_time).apply { text = if (allDay) "" else ChipStyle.timeText(e.start + "–" + e.end); setTextColor(chip.time); visibility = if (allDay) View.GONE else View.VISIBLE }
                v.findViewById<View>(R.id.i_sub).visibility = View.GONE
                v.findViewById<View>(R.id.i_note).visibility = View.GONE
                v.findViewById<View>(R.id.i_badge).visibility = View.GONE
                col.addView(v)
            }
            parent.addView(col, idx, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        }
        fill(R.id.w_list, R.id.w_empty, listOf(Ev("10:40", "11:40", "Гитара", "", color = "#34C759"), Ev("14:00", "14:45", "Обсуждение итогов", "", color = "#FF3B30")))
        fill(R.id.w_list2, R.id.w_empty2, listOf(Ev("весь", "день", "День рождения", "", color = "#FF2D55"), Ev("08:30", "09:30", "Отвезти в школу", "", color = "#007AFF"), Ev("09:00", "10:30", "Йога", "", color = "#AF52DE")))
        return frame
    }

    @Test
    fun wide() {
        paparazzi.snapshot(cols(paparazzi.layoutInflater))
    }

    @Test
    fun light() {
        paparazzi.snapshot(widget(paparazzi.layoutInflater))
    }

    @Test
    fun dark() {
        paparazzi.unsafeUpdateConfig(DeviceConfig.PIXEL_5.copy(nightMode = NightMode.NIGHT))
        paparazzi.snapshot(widget(paparazzi.layoutInflater))
    }

    @Test
    fun setup() {
        paparazzi.snapshot(paparazzi.inflate<View>(R.layout.activity_setup))
    }
}
