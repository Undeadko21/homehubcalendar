package ru.homehub.calendar

import android.app.Activity
import android.content.Intent
import android.graphics.Typeface
import android.os.Bundle
import android.util.TypedValue
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Первый запуск или смена сервера: поиск календаря в сети или ввод адреса. */
class SetupActivity : Activity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var status: TextView
    private lateinit var progress: ProgressBar
    private lateinit var found: LinearLayout
    private lateinit var url: EditText

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_setup)
        status = findViewById(R.id.s_status)
        progress = findViewById(R.id.s_progress)
        found = findViewById(R.id.s_found)
        url = findViewById(R.id.s_url)
        Prefs(this).server?.let { url.setText(it.removePrefix("http://")) }

        findViewById<View>(R.id.s_search).setOnClickListener { search() }
        findViewById<View>(R.id.s_connect).setOnClickListener { connect(url.text.toString()) }
        if (Prefs(this).server == null) search()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun search() {
        found.removeAllViews()
        progress.visibility = View.VISIBLE
        progress.progress = 0
        status.text = "Ищу календарь в сети…"
        scope.launch {
            try {
                val list = Api.discover(this@SetupActivity) { done, total ->
                    runOnUiThread { progress.max = total; progress.progress = done }
                }
                progress.visibility = View.GONE
                when {
                    list.isEmpty() -> status.text =
                        "Не нашёл. Проверьте, что телефон в домашней Wi-Fi сети, или введите адрес ниже — его видно в адресной строке браузера, где открыт календарь."
                    list.size == 1 -> { status.text = "Нашёл: ${list[0].first.removePrefix("http://")}"; save(list[0].first) }
                    else -> {
                        status.text = "Нашлось несколько — выберите:"
                        list.forEach { (base, _) -> found.addView(choice(base)) }
                    }
                }
            } catch (e: ApiException) {
                progress.visibility = View.GONE
                status.text = e.message
            }
        }
    }

    private fun choice(base: String) = TextView(this).apply {
        text = base.removePrefix("http://")
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 17f)
        setTextColor(getColor(R.color.red))
        typeface = Typeface.DEFAULT_BOLD
        setPadding(0, 28, 0, 28)
        setOnClickListener { save(base) }
    }

    private fun connect(input: String) {
        val base = normalizeServer(input) ?: run { status.text = "Введите адрес, например 192.168.0.188:8080"; return }
        status.text = "Проверяю ${base.removePrefix("http://")}…"
        scope.launch {
            val ok = withContext(Dispatchers.IO) { Api.probe(base, 4000) }
            if (ok != null) save(base)
            else status.text = "По адресу ${base.removePrefix("http://")} календарь не отвечает. Проверьте адрес и что телефон в домашней сети."
        }
    }

    private fun save(base: String) {
        Prefs(this).server = base
        Widgets.refreshNow(this)
        startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP))
        finish()
    }
}
