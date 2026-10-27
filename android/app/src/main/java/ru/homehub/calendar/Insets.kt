package ru.homehub.calendar

import android.os.Build
import android.view.View
import android.view.WindowInsets

/** Android 15 рисует приложения под системными панелями — сдвигаем содержимое на их высоту. */
@Suppress("DEPRECATION")
fun View.padForSystemBars() {
    setOnApplyWindowInsetsListener { v, insets ->
        if (Build.VERSION.SDK_INT >= 30) {
            val b = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout() or WindowInsets.Type.ime())
            v.setPadding(b.left, b.top, b.right, b.bottom)
        } else {
            v.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
        }
        WindowInsets.CONSUMED
    }
    requestApplyInsets()
}
