package ru.homehub.calendar

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.content.Intent
import android.os.Bundle
import android.view.ViewGroup
import android.widget.Button
import android.widget.CheckBox
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.TextView

/** Настройки одного виджета: размер текста, прозрачность, дни, подробности, шапка. Открывается при добавлении и из меню виджета. */
class WidgetConfigActivity : Activity() {
    private var widgetId = AppWidgetManager.INVALID_APPWIDGET_ID

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        widgetId = intent?.extras?.getInt(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
            ?: AppWidgetManager.INVALID_APPWIDGET_ID
        setResult(RESULT_CANCELED, Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId))
        if (widgetId == AppWidgetManager.INVALID_APPWIDGET_ID) { finish(); return }

        val prefs = WidgetPrefs(this)
        val cur = prefs.get(widgetId)
        val dp = resources.displayMetrics.density
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val p = (18 * dp).toInt()
            setPadding(p, p, p, p)
        }
        fun title(t: String) = TextView(this).apply {
            text = t; textSize = 13f; setPadding(0, (14 * dp).toInt(), 0, (2 * dp).toInt()); setTextColor(0xFF8E8E93.toInt())
        }
        fun group(items: List<Pair<String, Int>>, selected: Int): RadioGroup {
            val g = RadioGroup(this).apply { orientation = RadioGroup.VERTICAL }
            items.forEachIndexed { i, (label, value) ->
                g.addView(RadioButton(this).apply { id = 1000 + i; text = label; tag = value; isChecked = value == selected })
            }
            return g
        }
        fun RadioGroup.value(): Int = findViewById<RadioButton>(checkedRadioButtonId)?.tag as? Int ?: 0

        box.addView(TextView(this).apply { text = "Виджет «Семейный день»"; textSize = 20f })
        box.addView(title("Размер текста"))
        val scale = group(listOf("Мелкий" to 85, "Обычный" to 100, "Крупный" to 120, "Очень крупный" to 145), cur.scale)
        box.addView(scale)
        box.addView(title("Фон"))
        val opacity = group(listOf("Непрозрачный" to 100, "Слегка прозрачный" to 80, "Прозрачный" to 55, "Почти прозрачный" to 30), cur.opacity)
        box.addView(opacity)
        box.addView(title("Сколько дней показывать"))
        val days = group(listOf("Только сегодня" to 1, "Сегодня и завтра" to 2, "Три дня" to 3), cur.days)
        box.addView(days)
        box.addView(title("Шапка с датой"))
        val header = group(listOf("По размеру виджета" to 0, "Всегда показывать" to 1, "Скрыть" to 2), cur.header)
        box.addView(header)
        val details = CheckBox(this).apply { text = "Подробности: кто и где (под названием)"; isChecked = cur.details }
        box.addView(title("Строки событий"))
        box.addView(details)
        box.addView(Button(this).apply {
            text = "Готово"
            setOnClickListener {
                prefs.put(widgetId, WidgetCfg(scale.value(), opacity.value(), days.value(), details.isChecked, header.value()))
                Widgets.renderAll(this@WidgetConfigActivity)
                setResult(RESULT_OK, Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId))
                finish()
            }
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = (18 * dp).toInt() })

        setContentView(ScrollView(this).apply { addView(box) })
    }
}
