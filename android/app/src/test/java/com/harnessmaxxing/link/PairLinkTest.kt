package com.harnessmaxxing.link

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class PairLinkTest {
    @Test fun parsesThePairingLink() {
        assertEquals(PairLink.Link("https://ui.example.com", "AB12CD34"),
            PairLink.parse("harnesslink://pair?s=https%3A%2F%2Fui.example.com&c=AB12CD34"))
        assertEquals(PairLink.Link("https://ui.example.com/hm", "AB12CD34"),
            PairLink.parse("harnesslink://pair?c=AB12-CD34&s=https://ui.example.com/hm"))
        assertNull(PairLink.parse("https://ui.example.com/link/AB12CD34"))
        assertNull(PairLink.parse("harnesslink://pair?s=https://ui.example.com"))
        assertNull(PairLink.parse("harnesslink://other?s=https://ui.example.com&c=X"))
    }

    @Test fun serverMustBeHttps() {
        assertEquals("https://ui.example.com", PairLink.normalizeServer("ui.example.com/", false))
        assertEquals("https://ui.example.com:8443/hm", PairLink.normalizeServer(" https://UI.example.com:8443/hm/ ", false))
        assertThrows(PairLink.BadServer::class.java) { PairLink.normalizeServer("http://ui.example.com", false) }
        assertThrows(PairLink.BadServer::class.java) { PairLink.normalizeServer("http://10.0.2.2:8801", false) }
        assertThrows(PairLink.BadServer::class.java) { PairLink.normalizeServer("ftp://ui.example.com", false) }
        assertThrows(PairLink.BadServer::class.java) { PairLink.normalizeServer("https://user:pw@ui.example.com", false) }
        assertThrows(PairLink.BadServer::class.java) { PairLink.normalizeServer("", false) }
    }

    @Test fun debugBuildsAllowHttpToTheEmulatorHostOnly() {
        assertEquals("http://10.0.2.2:8801", PairLink.normalizeServer("http://10.0.2.2:8801", true))
        assertEquals("http://localhost:8801", PairLink.normalizeServer("http://localhost:8801/", true))
        assertThrows(PairLink.BadServer::class.java) { PairLink.normalizeServer("http://ui.example.com", true) }
    }

    @Test fun urls() {
        assertEquals("wss://ui.example.com/api/devices/ws", PairLink.wsUrl("https://ui.example.com"))
        assertEquals("ws://10.0.2.2:8801/api/devices/ws", PairLink.wsUrl("http://10.0.2.2:8801"))
        assertEquals("https://ui.example.com/hm/api/devices/pair", PairLink.pairUrl("https://ui.example.com/hm"))
        assertEquals("ui.example.com", PairLink.host("https://ui.example.com:8443/x"))
    }
}
