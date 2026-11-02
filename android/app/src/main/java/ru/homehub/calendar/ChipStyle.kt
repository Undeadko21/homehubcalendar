package ru.homehub.calendar

import android.content.Context
import android.content.res.Configuration
import android.graphics.Color

/** Цвета плашки события как в «Календаре» Apple: тонированная заливка, полоса и текст цвета календаря (в тёмной теме светлее). */
object ChipStyle {
    data class Colors(val text: Int, val time: Int, val sub: Int, val bar: Int, val fillAlpha: Int)

    fun dark(context: Context): Boolean =
        (context.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES

    fun colors(context: Context, hex: String?, strong: Boolean = false, dark: Boolean = dark(context)): Colors {
        val base = runCatching { Color.parseColor(hex) }.getOrDefault(Color.rgb(142, 142, 147))
        val target = if (dark) 255 else 0
        val k = if (dark) 0.32f else 0.30f
        fun mix(c: Int) = (c + (target - c) * k).toInt().coerceIn(0, 255)
        val r = mix(Color.red(base)); val g = mix(Color.green(base)); val b = mix(Color.blue(base))
        val alpha = if (dark) (if (strong) 85 else 56) else (if (strong) 66 else 43)
        return Colors(Color.rgb(r, g, b), Color.argb(217, r, g, b), Color.argb(179, r, g, b), base, alpha)
    }

    /** «21:20–21:40» → «21:20 — 21:40», как у Apple. */
    fun timeText(time: String) = time.replace("–", " — ")
}
