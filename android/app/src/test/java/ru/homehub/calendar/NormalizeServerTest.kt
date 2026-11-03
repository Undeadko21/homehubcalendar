package ru.homehub.calendar

import org.junit.Assert.assertEquals
import org.junit.Test

class NormalizeServerTest {
    @Test fun lanAddressGetsHttpAndPort() = assertEquals("http://192.168.0.188:8080", normalizeServer("192.168.0.188"))
    @Test fun explicitPortKept() = assertEquals("http://192.168.0.188:80", normalizeServer("192.168.0.188:80/"))
    @Test fun httpsKeepsDefaultPort() = assertEquals("https://168-113-183-46.sslip.io", normalizeServer("https://168-113-183-46.sslip.io/"))
    @Test fun httpsWithPortKept() = assertEquals("https://example.ru:8443", normalizeServer("https://example.ru:8443"))
}
