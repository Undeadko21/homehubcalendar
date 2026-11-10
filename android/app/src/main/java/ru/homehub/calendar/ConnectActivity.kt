package ru.homehub.calendar

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.os.Bundle

/**
 * Подключение по QR-коду: страница /connect на сервере открывает homehub://connect?c=hhc1.…
 * Код тот же, что вставляется вручную, поэтому уже подключённым устройствам ничего не нужно делать.
 * Новое устройство получает облако, публичный адрес и токен чтения; если адреса сервера ещё нет — берём публичный.
 */
class ConnectActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val code = intent?.data?.getQueryParameter("c").orEmpty()
        val parsed = Cloud.parseCode(code)
        if (parsed == null) {
            AlertDialog.Builder(this)
                .setTitle("Не удалось подключиться")
                .setMessage("Код подключения не распознан. Отсканируйте QR-код заново в настройках календаря.")
                .setPositiveButton("Понятно") { _, _ -> finish() }
                .setOnCancelListener { finish() }
                .show()
            return
        }
        val p = Prefs(this)
        p.cloudUrl = parsed.url
        p.cloudKey = parsed.key
        p.cloudToken = parsed.token
        p.publicUrl = parsed.publicUrl
        p.widgetToken = parsed.widgetToken
        if (p.server == null && parsed.publicUrl != null) p.server = parsed.publicUrl
        Widgets.refreshNow(this)
        val next = if (p.server == null) SetupActivity::class.java else MainActivity::class.java
        startActivity(Intent(this, next).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP))
        finish()
    }
}
