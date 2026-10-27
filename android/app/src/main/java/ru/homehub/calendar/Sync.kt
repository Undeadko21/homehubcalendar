package ru.homehub.calendar

import android.content.Context
import org.json.JSONObject

/**
 * Единый путь обновления данных: сначала домашний сервер (быстро и всегда свежо), если не отвечает —
 * облачный снимок. Из снимка обновляются виджет и напоминания.
 */
object Sync {
    fun run(context: Context): Boolean {
        val prefs = Prefs(context)
        var json: String? = null
        var source = "home"
        var error: String? = null

        prefs.server?.let { base ->
            try {
                json = Api.get(base, "/api/snapshot", 6000)
            } catch (e: ApiException) {
                error = e.message
                // Сервер старой версии без /api/snapshot: обновляем хотя бы виджет.
                if (e.message?.contains("404") == true) runCatching {
                    prefs.widgetJson = Api.get(base, "/api/widget?days=2")
                    prefs.lastOk = System.currentTimeMillis(); prefs.lastError = null; prefs.dataSource = "home"
                    Widgets.renderAll(context)
                    return true
                }
            } catch (e: Exception) {
                error = "Нет связи с календарём"
            }
        }
        if (json == null) {
            val url = prefs.cloudUrl
            val key = prefs.cloudKey
            if (url != null && key != null) {
                try {
                    json = Cloud.fetch(url, key)
                    source = "cloud"
                } catch (e: Exception) {
                    error = (error ?: "Нет связи с календарём") + "; облако: " + (e.message ?: "недоступно")
                }
            }
        }
        val text = json
        if (text == null) {
            prefs.lastError = error ?: "Нет связи с календарём"
            Widgets.renderAll(context)
            return false
        }
        return try {
            val root = JSONObject(text)
            prefs.widgetJson = root.getJSONObject("widget").toString()
            prefs.lastOk = System.currentTimeMillis()
            prefs.lastError = null
            prefs.dataSource = source
            if (prefs.notifyEnabled) Reminders.apply(context, root.getJSONArray("reminders"))
            Widgets.renderAll(context)
            true
        } catch (e: Exception) {
            prefs.lastError = "Не удалось разобрать данные"
            Widgets.renderAll(context)
            false
        }
    }
}
