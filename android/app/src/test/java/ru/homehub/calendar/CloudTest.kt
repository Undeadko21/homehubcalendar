package ru.homehub.calendar

import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.Base64

/** Файл зашифрован сервером (backend/app/cloud.py), приложение должно прочитать его так же. */
class CloudTest {
    private val key = ByteArray(32) { it.toByte() }
    private val blob = Base64.getDecoder().decode("ZbIsMSxT+9RYcbSvhqumWc7XEJB6M07Mvizsw9CWLawfo8stjuibTk8Qj1+E+UZAz6DDak6d89JNgwNc2fhnp+z/Ow==")

    @Test
    fun decryptsServerSnapshot() {
        assertEquals("{\"v\":1,\"текст\":\"проверка\"}", Cloud.decrypt(key, blob))
    }
}
