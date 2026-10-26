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

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == Widgets.ACTION_REFRESH) {
            Widgets.renderAll(context)
            Widgets.refreshNow(context)
        }
    }
}
