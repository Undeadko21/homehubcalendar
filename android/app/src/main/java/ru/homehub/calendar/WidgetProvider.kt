package ru.homehub.calendar

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent

class WidgetProvider : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        Widgets.renderAll(context)
        Widgets.schedule(context)
        Widgets.refreshNow(context)
    }

    override fun onAppWidgetOptionsChanged(context: Context, manager: AppWidgetManager, id: Int, newOptions: android.os.Bundle) {
        Widgets.renderAll(context)   // размер изменили — перестраиваем шапку под него
    }

    override fun onDeleted(context: Context, ids: IntArray) {
        val prefs = WidgetPrefs(context)
        ids.forEach { prefs.remove(it) }
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == Widgets.ACTION_REFRESH) {
            Widgets.renderAll(context)
            Widgets.refreshNow(context)
        }
    }
}
