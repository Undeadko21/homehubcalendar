package ru.homehub.calendar

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.core.content.FileProvider
import java.io.File
import android.view.Gravity
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Мост для веб-интерфейса: window.HomeHubApp.* */
class AppBridge(private val activity: MainActivity) {
    @JavascriptInterface
    fun changeServer() = activity.runOnUiThread { activity.openSetup() }

    @JavascriptInterface
    fun refreshWidget() = Widgets.refreshNow(activity)

    @JavascriptInterface
    fun version(): String = BuildConfig.VERSION_NAME

    /** Можно ли поставить виджет из приложения (зависит от лаунчера). */
    @JavascriptInterface
    fun canPinWidget(): Boolean = Widgets.canPin(activity)

    @JavascriptInterface
    fun hasWidget(): Boolean = Widgets.ids(activity).isNotEmpty()

    @JavascriptInterface
    fun pinWidget(): Boolean = Widgets.pin(activity)
}

/** Основной экран: веб-интерфейс календаря с сервера в домашней сети. */
class MainActivity : Activity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var web: WebView
    private lateinit var errorView: LinearLayout
    private lateinit var errorText: TextView
    private var server: String? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        server = Prefs(this).server
        if (server == null) { openSetup(); finish(); return }

        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.userAgentString = settings.userAgentString + " HomeHubApp/" + BuildConfig.VERSION_NAME
            setBackgroundColor(Color.TRANSPARENT)
            addJavascriptInterface(AppBridge(this@MainActivity), "HomeHubApp")
            webViewClient = object : WebViewClient() {
                override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                    if (request.isForMainFrame) showError()
                }

                override fun onPageFinished(view: WebView, url: String) {
                    // После входа по PIN у виджета появляется доступ — обновим его.
                    Widgets.refreshNow(this@MainActivity)
                }

                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val u = request.url
                    // Внешние ссылки (карты, сайты) — в браузер; свои страницы — здесь.
                    return if (server != null && u.toString().startsWith(server!!)) false
                    else { startActivity(Intent(Intent.ACTION_VIEW, u)); true }
                }
            }
        }
        errorText = TextView(this).apply {
            setTextColor(getColor(R.color.ink2)); textSize = 15f; gravity = Gravity.CENTER
            setPadding(48, 0, 48, 32)
        }
        errorView = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; visibility = View.GONE
            setBackgroundColor(getColor(R.color.bg))
            addView(errorText)
            addView(button("Повторить") { load() })
            addView(button("Сменить сервер") { openSetup() })
        }
        setContentView(FrameLayout(this).apply {
            setBackgroundColor(getColor(R.color.bg))
            addView(web); addView(errorView); padForSystemBars()
        })
        load()
        Widgets.schedule(this)
        checkUpdate()
        offerWidget()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (::web.isInitialized) web.reload()
    }

    override fun onResume() {
        super.onResume()
        val now = Prefs(this).server
        if (now != null && now != server) { server = now; load() }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (::web.isInitialized && web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    fun openSetup() = startActivity(Intent(this, SetupActivity::class.java))

    private fun load() {
        errorView.visibility = View.GONE
        web.visibility = View.VISIBLE
        web.loadUrl(server!! + "/")
    }

    private fun showError() {
        web.visibility = View.INVISIBLE
        errorView.visibility = View.VISIBLE
        errorText.text = "Календарь ${server?.removePrefix("http://")} не отвечает.\n" +
            "Приложение работает в домашней Wi-Fi сети — проверьте подключение."
    }

    private fun button(text: String, onClick: () -> Unit) = TextView(this).apply {
        this.text = text
        setTextColor(getColor(R.color.red)); textSize = 17f; gravity = Gravity.CENTER
        setPadding(32, 28, 32, 28)
        setOnClickListener { onClick() }
    }

    /** Один раз после установки предложим поставить виджет на рабочий стол. */
    private fun offerWidget() {
        val sp = getSharedPreferences("homehub", MODE_PRIVATE)
        if (sp.getBoolean("widget_offered", false) || Widgets.ids(this).isNotEmpty() || !Widgets.canPin(this)) return
        sp.edit().putBoolean("widget_offered", true).apply()
        AlertDialog.Builder(this)
            .setTitle("Виджет на рабочий стол")
            .setMessage("Показывать события семьи на сегодня и завтра прямо на рабочем столе?")
            .setPositiveButton("Добавить") { _, _ -> Widgets.pin(this) }
            .setNegativeButton("Не сейчас", null)
            .show()
    }

    /** Если на сервере лежит более новая версия приложения — предложим обновиться. */
    private fun checkUpdate() {
        val base = server ?: return
        scope.launch {
            val v = withContext(Dispatchers.IO) { Api.appVersion(base) } ?: return@launch
            val prefs = Prefs(this@MainActivity)
            if (v.first <= BuildConfig.VERSION_CODE || prefs.dismissedUpdate == v.first) return@launch
            AlertDialog.Builder(this@MainActivity)
                .setTitle("Доступна версия ${v.second}")
                .setMessage("Скачать и установить обновление приложения?")
                .setPositiveButton("Обновить") { _, _ ->
                    installUpdate(base)
                }
                .setNegativeButton("Позже") { _, _ -> prefs.dismissedUpdate = v.first }
                .show()
        }
    }

    /** Скачивает APK во внутренний кэш и открывает системный установщик. */
    private fun installUpdate(base: String) {
        if (Build.VERSION.SDK_INT >= 26 && !packageManager.canRequestPackageInstalls()) {
            Toast.makeText(this, "Разрешите установку из этого приложения и нажмите «Обновить» ещё раз", Toast.LENGTH_LONG).show()
            startActivity(Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")))
            return
        }
        Toast.makeText(this, "Скачиваю обновление…", Toast.LENGTH_SHORT).show()
        scope.launch {
            val file = withContext(Dispatchers.IO) {
                try {
                    val dir = File(cacheDir, "update").apply { mkdirs() }
                    val out = File(dir, "homehub-calendar.apk")
                    java.net.URL("$base/app.apk").openStream().use { i -> out.outputStream().use { i.copyTo(it) } }
                    out
                } catch (e: Exception) { null }
            }
            if (file == null || file.length() < 10_000) {
                Toast.makeText(this@MainActivity, "Не удалось скачать обновление", Toast.LENGTH_LONG).show()
                return@launch
            }
            val uri = FileProvider.getUriForFile(this@MainActivity, "$packageName.files", file)
            startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }
}
