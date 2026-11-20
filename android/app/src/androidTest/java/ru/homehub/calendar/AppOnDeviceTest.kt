package ru.homehub.calendar

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Проверки на эмуляторе (GitHub Actions, android-device.yml, v0.21): запуск, уведомления с кнопками, разбор напоминаний.
 * Код Kotlin здесь не запускается нигде, кроме этого прогона, — поэтому проверяем то, что ломалось или легко сломать.
 */
@RunWith(AndroidJUnit4::class)
class AppOnDeviceTest {
    private val ctx: Context = InstrumentationRegistry.getInstrumentation().targetContext
    private val nm get() = ctx.getSystemService(NotificationManager::class.java)

    @Before
    fun clean() {
        if (android.os.Build.VERSION.SDK_INT >= 33) {   // выдать разрешение и дождаться (иначе уведомление молча не покажется)
            InstrumentationRegistry.getInstrumentation().uiAutomation
                .grantRuntimePermission(ctx.packageName, android.Manifest.permission.POST_NOTIFICATIONS)
        }
        nm.cancelAll()
    }

    /** Уведомления публикуются асинхронно — ждём до 5 с, а не фиксированные полсекунды. */
    private fun waitFor(id: String): android.service.notification.StatusBarNotification? {
        repeat(25) {
            nm.activeNotifications.firstOrNull { it.id == id.hashCode() }?.let { return it }
            Thread.sleep(200)
        }
        return null
    }

    @Test
    fun appStartsWithoutCrash() {
        // Первый запуск без сервера: открывается (основной или экран настройки) и не падает — падение провалит прогон.
        ActivityScenario.launch<MainActivity>(Intent(ctx, MainActivity::class.java)).use { Thread.sleep(4000) }
    }

    @Test
    fun goReminderHasRouteAndTakeButtons() {
        val p = Prefs(ctx)
        p.cloudKey = "test-key"; p.cloudToken = "test-token"   // «Всё взял» — только при настроенном облаке
        Reminders.show(ctx, "go:test", "Пора выезжать — бассейн", "Взять: очки", null, "ул. Ленина, 1", "[11,12]")
        val n = waitFor("go:test")
        assertNotNull("уведомление не показано", n)
        val titles = n!!.notification.actions.orEmpty().map { it.title.toString() }
        assertTrue("нет «Маршрут»: $titles", "Маршрут" in titles)
        assertTrue("нет «Всё взял»: $titles", "Всё взял" in titles)
    }

    @Test
    fun noTakeButtonWithoutCloud() {
        val p = Prefs(ctx)
        p.cloudKey = null; p.cloudToken = null
        Reminders.show(ctx, "ev:test2", "Бассейн — в 17:00", "Взять: очки", null, null, "[11]")
        val n = waitFor("ev:test2")
        assertNotNull(n)
        assertTrue(n!!.notification.actions.orEmpty().none { it.title.toString() == "Всё взял" })
    }

    @Test
    fun applyShowsDueReminderAndSkipsFuture() {
        val now = System.currentTimeMillis()
        fun iso(ms: Long) = java.time.OffsetDateTime.ofInstant(java.time.Instant.ofEpochMilli(ms), java.time.ZoneId.systemDefault()).toString()
        Prefs(ctx).shownReminders = emptySet()
        val items = JSONArray()
            .put(JSONObject().put("id", "chg:abc").put("kind", "event").put("people", JSONArray())
                .put("at", iso(now - 60_000)).put("start", iso(now - 60_000)).put("title", "Изменено: Бассейн").put("text", "17:00 → 18:00"))
            .put(JSONObject().put("id", "ev:later").put("kind", "event").put("people", JSONArray())
                .put("at", iso(now + 3_600_000)).put("start", iso(now + 3_600_000)).put("title", "Позже").put("text", ""))
        Reminders.apply(ctx, items)
        assertNotNull("«Изменено» не показано", waitFor("chg:abc"))
        val ids = nm.activeNotifications.map { it.id }
        assertTrue("будущее показано раньше времени", "ev:later".hashCode() !in ids)
        assertTrue("показанное не запомнено", "chg:abc" in Prefs(ctx).shownReminders)
        Reminders.apply(ctx, items)   // повторно — не дублирует
        assertEquals(1, nm.activeNotifications.count { it.id == "chg:abc".hashCode() })
    }

    @Test
    fun offlineScreenAssetsPresent() {
        val names = ctx.assets.list("offline")!!.toSet()
        assertTrue("нет офлайн-экрана: $names", "index.html" in names && "app.js" in names)
        val js = ctx.assets.open("offline/app.js").bufferedReader().readText()
        assertTrue("офлайн-экран не знает «не идёт»", "absent" in js)
    }
}
