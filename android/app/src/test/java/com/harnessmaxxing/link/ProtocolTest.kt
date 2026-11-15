package com.harnessmaxxing.link

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ProtocolTest {
    @Test fun parsesCommandsAndKeepsTheServerId() {
        val f = Protocol.parse("""{"t":"input","id":"r17","a":"click","x":10.5,"y":"20","sw":640,"sh":1387,"double":true}""")!!
        assertEquals("input", f.t)
        assertEquals("r17", f.id)
        assertEquals("click", f.str("a"))
        assertEquals(10.5, f.num("x")!!, 0.0)
        assertEquals(20.0, f.num("y")!!, 0.0)
        assertEquals(640, f.int("sw"))
        assertTrue(f.bool("double"))
        assertFalse(f.bool("missing"))
        assertNull(f.num("dx"))
    }

    @Test fun numericIdsAreEchoedAsNumbers() {
        val f = Protocol.parse("""{"t":"shot","id":42,"max_w":800}""")!!
        val reply = JSONObject(Protocol.ok(f.id, JSONObject().put("w", 800)))
        assertEquals("ok", reply.getString("t"))
        assertEquals(42, reply.getInt("id"))
        assertEquals(800, reply.getInt("w"))
    }

    @Test fun rejectsFramesWithoutType() {
        assertNull(Protocol.parse("not json"))
        assertNull(Protocol.parse("""{"id":1}"""))
        assertNull(Protocol.parse("[1,2]"))
    }

    @Test fun keysAreCombosSeparatedBySpacesOrAList() {
        assertEquals(listOf("enter"), Protocol.parse("""{"t":"input","a":"key","keys":"enter"}""")!!.keys())
        assertEquals(listOf("ctrl+a", "delete"), Protocol.parse("""{"t":"input","a":"key","keys":" ctrl+a  delete "}""")!!.keys())
        assertEquals(listOf("back", "home"), Protocol.parse("""{"t":"input","a":"key","keys":["back","home"]}""")!!.keys())
        assertEquals(emptyList<String>(), Protocol.parse("""{"t":"input","a":"key"}""")!!.keys())
    }

    @Test fun cropObject() {
        val f = Protocol.parse("""{"t":"shot","id":1,"crop":{"x":1,"y":2,"w":3,"h":4},"sw":540,"sh":1170}""")!!
        assertEquals(3, f.obj("crop")!!.getInt("w"))
        assertNull(Protocol.parse("""{"t":"shot","id":1}""")!!.obj("crop"))
    }

    @Test fun errorFrame() {
        val e = JSONObject(Protocol.err("a1", Protocol.Err.PAUSED, "paused by the person"))
        assertEquals("err", e.getString("t"))
        assertEquals("a1", e.getString("id"))
        assertEquals("paused", e.getString("code"))
        assertEquals("paused by the person", e.getString("message"))
    }

    @Test fun helloMatchesTheContract() {
        val h = JSONObject(Protocol.hello("Pixel 7", "arm64-v8a", "1.0.0", "Google Pixel 7", 35, Protocol.CAPS, 1080, 2400, 2.625, "", false))
        assertEquals("hello", h.getString("t"))
        assertEquals("1.0.0", h.getString("v"))
        assertEquals("android", h.getString("os"))
        assertEquals("android", h.getString("kind"))
        assertEquals("arm64-v8a", h.getString("arch"))
        assertEquals("Pixel 7", h.getString("name"))
        assertEquals(listOf("screen", "input", "tree", "apps"), h.getJSONArray("caps").let { a -> (0 until a.length()).map { a.getString(it) } })
        val s = h.getJSONObject("screen")
        assertEquals(1080, s.getInt("w")); assertEquals(2400, s.getInt("h")); assertEquals(2.625, s.getDouble("scale"), 0.0)
        assertFalse(h.has("note"))
    }

    @Test fun helloWithoutAccessibilityHasNoScreen() {
        val h = JSONObject(Protocol.hello("P", "x86_64", "1.0.0", "M", 35, listOf("apps"), 1080, 2400, 2.0, "Accessibility is off", false))
        assertFalse(h.has("screen"))
        assertEquals(1, h.getJSONArray("caps").length())
        assertEquals("Accessibility is off", h.getString("note"))
    }

    @Test fun pairBodyAndReply() {
        val b = JSONObject(Protocol.pairBody("AB12CD34", "Pixel 7", "x86_64", "1.0.0"))
        assertEquals("AB12CD34", b.getString("code"))
        assertEquals("android", b.getString("os"))
        assertEquals(4, b.getJSONArray("caps").length())
        assertEquals(Protocol.PairResult("d_1", "tok"), Protocol.parsePairReply("""{"device_id":"d_1","token":"tok"}"""))
        assertNull(Protocol.parsePairReply("""{"device_id":"d_1"}"""))
        assertNull(Protocol.parsePairReply("<html>"))
        assertEquals("expired", Protocol.pairError("""{"error":"expired","message":"..."}"""))
        assertEquals("", Protocol.pairError("<html>"))
    }

    @Test fun pausedFrame() {
        val p = JSONObject(Protocol.paused(true))
        assertEquals("paused", p.getString("t")); assertTrue(p.getBoolean("on"))
    }
}
