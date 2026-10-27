package ru.homehub.calendar

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import org.json.JSONArray
import org.json.JSONObject
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
    fun refreshWidget() { Widgets.refreshNow(activity); Reminders.checkNow(activity) }

    /** Настройки напоминаний на этом телефоне (JSON). */
    @JavascriptInterface
    fun getNotify(): String {
        val p = Prefs(activity)
        return JSONObject()
            .put("enabled", p.notifyEnabled)
            .put("people", JSONArray(p.notifyPeople.split(",").filter { it.isNotBlank() }))
            .put("lead", p.notifyLead)
            .put("granted", Reminders.notificationsAllowed(activity))
            .toString()
    }

    @JavascriptInterface
    fun setNotify(enabled: Boolean, people: String, lead: Int) {
        val p = Prefs(activity)
        p.notifyEnabled = enabled
        p.notifyPeople = people
        p.notifyLead = lead
        p.shownReminders = emptySet()  // после смены настроек считаем заново
        Reminders.cancelAll(activity)
        Reminders.schedule(activity)
        Reminders.checkNow(activity)
    }

    /** Android 13+ спрашивает разрешение на уведомления; на старых версиях оно уже есть. */
    @JavascriptInterface
    fun requestNotifications() = activity.runOnUiThread {
        if (Build.VERSION.SDK_INT >= 33 && !Reminders.notificationsAllowed(activity)) {
            activity.requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 11)
        }
    }

    /** Подключает облачный снимок по коду из настроек сервера. */
    @JavascriptInterface
    fun setCloud(code: String): Boolean {
        val parsed = Cloud.parseCode(code) ?: return false
        val p = Prefs(activity)
        p.cloudUrl = parsed.url
        p.cloudKey = parsed.key
        p.cloudToken = parsed.token
        Widgets.refreshNow(activity)
        return true
    }

    @JavascriptInterface
    fun cloudState(): String {
        val p = Prefs(activity)
        return JSONObject().put("connected", p.cloudUrl != null).put("source", p.dataSource).put("last_ok", p.lastOk).toString()
    }

    // ----- офлайн-экран (вне дома): данные из облачного снимка и очередь команд -----
    @JavascriptInterface
    fun getSnapshot(): String = Outbox.snapshot(activity) ?: ""

    @JavascriptInterface
    fun getPending(): String = Outbox.pending(activity).toString()

    /** Принимает команду (JSON), кладёт в очередь, сразу отправляет в облако. Возвращает id. */
    @JavascriptInterface
    fun queueOp(json: String): String {
        val id = Outbox.add(activity, JSONObject(json))
        Widgets.refreshNow(activity)
        return id
    }

    @JavascriptInterface
    fun syncNow() = Widgets.refreshNow(activity)

    /** Проверить, не появился ли дом в сети, и если да — открыть обычный интерфейс. */
    @JavascriptInterface
    fun retryHome() = activity.runOnUiThread { activity.tryHome(true) }

    @JavascriptInterface
    fun testNotification() {
        Reminders.show(activity, "test:" + System.currentTimeMillis(), "Проверка напоминаний",
            "Так выглядит напоминание: «Отвезти Марка — в 10:10»")
    }

    @JavascriptInterface
    fun version(): String = BuildConfig.VERSION_NAME

    @JavascriptInterface
    fun versionCode(): Int = BuildConfig.VERSION_CODE

    /** Скачать и установить свежую версию с сервера (кнопка «Обновить» в настройках). */
    @JavascriptInterface
    fun updateApp() = activity.runOnUiThread { activity.startUpdate() }

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
            // WebView сам файлы не скачивает: ссылку на APK превращаем в установку обновления.
            setDownloadListener { url, _, _, _, _ ->
                if (url.contains("/app.apk")) startUpdate() else startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            }
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
        Reminders.schedule(this)
        Reminders.checkNow(this)
        checkUpdate()
        offerWidget()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (::web.isInitialized) web.reload()
    }

    override fun onResume() {
        super.onResume()
        continueUpdateIfNeeded()
        val now = Prefs(this).server
        if (now != null && now != server) { server = now; load() }
        else if (offline) tryHome()
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
        val base = server!!
        scope.launch {
            // Быстрая проверка: если дом не отвечает, не ждём долгий таймаут WebView, а сразу показываем облако.
            val ok = withContext(Dispatchers.IO) { Api.probe(base, 2500) != null }
            if (!ok && showOffline()) return@launch
            offline = false
            web.loadUrl("$base/")
        }
    }

    /** Режим «вне дома»: показываем облачный снимок, если он есть и подключён. */
    private var offline = false

    private fun showOffline(): Boolean {
        val prefs = Prefs(this)
        if (prefs.cloudUrl == null || Outbox.snapshot(this) == null) return false
        offline = true
        errorView.visibility = View.GONE
        web.visibility = View.VISIBLE
        web.loadUrl("file:///android_asset/offline/index.html")
        Widgets.refreshNow(this)
        return true
    }

    /** Если дом снова доступен — вернуться к обычному интерфейсу. */
    fun tryHome(force: Boolean = false) {
        val base = server ?: return
        scope.launch {
            val ok = withContext(Dispatchers.IO) { Api.probe(base, 2500) != null }
            if (ok) { offline = false; load() }
            else if (force) Toast.makeText(this@MainActivity, "Дом по-прежнему не отвечает", Toast.LENGTH_SHORT).show()
        }
    }

    private fun showError() {
        if (showOffline()) return
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
    fun startUpdate() { server?.let { installUpdate(it) } }

    private var updateAfterPermission = false

    private fun updateFailed(msg: String, base: String) {
        AlertDialog.Builder(this)
            .setTitle("Не удалось обновить")
            .setMessage(msg)
            .setPositiveButton("Скачать через браузер") { _, _ ->
                try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("$base/app.apk"))) } catch (_: Exception) {}
            }
            .setNegativeButton("Закрыть", null)
            .show()
    }

    private fun installUpdate(base: String) {
        if (Build.VERSION.SDK_INT >= 26 && !packageManager.canRequestPackageInstalls()) {
            updateAfterPermission = true
            AlertDialog.Builder(this)
                .setTitle("Нужно разрешение")
                .setMessage("Android просит разрешить этому приложению устанавливать обновления. Включите переключатель на следующем экране и вернитесь назад — обновление продолжится само.")
                .setPositiveButton("Открыть настройки") { _, _ ->
                    startActivity(Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")))
                }
                .setNegativeButton("Отмена") { _, _ -> updateAfterPermission = false }
                .show()
            return
        }
        val progress = AlertDialog.Builder(this).setMessage("Скачиваю обновление…").setCancelable(false).show()
        scope.launch {
            var error: String? = null
            val file = withContext(Dispatchers.IO) {
                try {
                    val dir = File(cacheDir, "update").apply { mkdirs() }
                    val out = File(dir, "homehub-calendar.apk")
                    val c = java.net.URL("$base/app.apk").openConnection() as java.net.HttpURLConnection
                    c.connectTimeout = 8000; c.readTimeout = 30000
                    if (c.responseCode != 200) { error = "Сервер ответил ${c.responseCode}"; null }
                    else {
                        c.inputStream.use { i -> out.outputStream().use { i.copyTo(it) } }
                        out
                    }
                } catch (e: Exception) { error = e.javaClass.simpleName + ": " + (e.message ?: ""); null }
            }
            progress.dismiss()
            if (file == null || file.length() < 10_000) {
                updateFailed(error ?: "Файл обновления слишком мал или не найден на сервере.", base)
                return@launch
            }
            try {
                val uri = FileProvider.getUriForFile(this@MainActivity, "$packageName.files", file)
                startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
            } catch (e: Exception) {
                updateFailed("Не открылся установщик: " + e.javaClass.simpleName + " " + (e.message ?: ""), base)
            }
        }
    }

    /** Вернулись с экрана разрешений — продолжаем обновление. */
    private fun continueUpdateIfNeeded() {
        if (updateAfterPermission && Build.VERSION.SDK_INT >= 26 && packageManager.canRequestPackageInstalls()) {
            updateAfterPermission = false
            startUpdate()
        }
    }
}
