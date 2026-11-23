"""Devices (maxxing/devices + api/devices): pairing, confirmation, the app's websocket (protocol v2, a fake device here),
Claude's tools, rights and access, the person taking over, ask_human, the live view, the runner, the CLI."""
from __future__ import annotations

import asyncio
import base64
import json
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import wait_for
from maxxing import security
from maxxing.api import devices as devices_api
from maxxing.devices import asks, dist, store, turns

T = "projects/acme/topics/blog"
A = "projects/acme/topics/blog/agents/writer"
CAPS_PHONE = ["screen", "input", "tree", "apps"]
CAPS_PC = ["screen", "input", "apps"]


@pytest.fixture
def dv(client, mx, monkeypatch, tmp_path):
    bins = tmp_path / "bins"
    bins.mkdir()
    for name in dist.TARGETS.values():
        (bins / name).write_bytes(b"APP-" + name.encode())
    monkeypatch.setenv("MAXXING_LINK_BIN_DIR", str(bins))
    monkeypatch.setattr(devices_api, "loopback", lambda conn: True)
    monkeypatch.setattr(devices_api, "_fails", {})
    monkeypatch.setattr("maxxing.devices.tools.SETTLE_S", 0.0)
    assert client.put("/api/settings", json={"devices_feature": True}).status_code == 200
    return client


class FakeDevice:
    """Harness Link on the other end of WS /api/devices/ws (protocol v2), in a thread."""

    def __init__(self, ws, os_name="android", caps=None, screen=(1080, 2400), screens=None) -> None:
        self.ws, self.os, self.caps, self.screen = ws, os_name, caps or CAPS_PHONE, screen
        self.screens, self.display = screens or [], 0          # several screens: [(w, h)], the first is the main one
        self.got: list[dict] = []
        self.errors: dict[str, tuple[str, str]] = {}
        self.unpaired = False
        self.closed = False
        self.t = threading.Thread(target=self.run, daemon=True)

    def start(self) -> "FakeDevice":
        self.t.start()
        return self

    def of(self, t: str) -> list[dict]:
        return [m for m in self.got if m.get("t") == t]

    def run(self) -> None:
        ws = self.ws
        self.hello()
        while True:
            try:
                m = ws.receive_json()
            except Exception:  # noqa: BLE001 - the server closed it
                self.closed = True
                return
            self.got.append(m)
            t, rid = m.get("t"), m.get("id")
            if t == "unpair":
                self.unpaired = True
                continue
            if t == "display" and self.screens:              # as Harness Link: switch, then hello again
                i = m.get("i")
                self.display = i if isinstance(i, int) and 0 <= i < len(self.screens) else 0
                self.screen = self.screens[self.display]
                self.hello()
                continue
            if t in ("state", "access", "display", "watch"):
                continue
            w, h = self.screen
            if t in self.errors:
                code, msg = self.errors[t]
                ws.send_json({"t": "err", "id": rid, "code": code, "message": msg})
                continue
            if t == "shot":
                sw = min(int(m.get("max_w") or w), w)
                sh = round(h * sw / w)
                if m.get("crop"):
                    sw, sh = m["crop"]["w"] * 2, m["crop"]["h"] * 2
                ws.send_json({"t": "ok", "id": rid, "jpeg": base64.b64encode(b"\xff\xd8JPEG" + bytes([len(self.got) % 250])).decode(),
                              "w": sw, "h": sh, "sw_screen": w, "sh_screen": h})
            elif t == "tree":
                ws.send_json({"t": "ok", "id": rid, "sw": m.get("sw"), "sh": m.get("sh"), "nodes": [
                    {"id": "n1", "role": "button", "text": "Send", "desc": "", "b": [10, 20, 100, 40], "click": True},
                    {"id": "n2", "role": "edit", "text": "", "desc": "Message", "b": [10, 80, 300, 40], "edit": True}]})
            elif t == "apps":
                ws.send_json({"t": "ok", "id": rid, "apps": [{"id": "com.android.settings", "name": "Settings"},
                                                             {"id": "com.whatsapp", "name": "WhatsApp"}]})
            else:
                ws.send_json({"t": "ok", "id": rid})


    def hello(self) -> None:
        w, h = self.screens[self.display] if self.screens else self.screen
        self.screen = (w, h)
        m = {"t": "hello", "v": "0.1.0", "os": self.os, "arch": "arm64", "name": "fake", "caps": self.caps,
             "screen": {"w": w, "h": h, "scale": 1}, "note": ""}
        if self.screens:
            m["screens"] = [{"i": i, "name": f"Display {i + 1}", "w": a, "h": b, "main": i == 0}
                            for i, (a, b) in enumerate(self.screens)]
            m["display"] = self.display
        self.ws.send_json(m)


def _pair(c, os_name="android", name="Pixel 7", caps=None, confirm=True) -> dict:
    inv = c.post("/api/devices/invites", json={"os": os_name}).json()
    r = c.post("/api/devices/pair", json={"code": inv["code"], "name": name, "os": os_name, "arch": "arm64",
                                          "version": "0.1.0", "caps": caps or CAPS_PHONE})
    assert r.status_code == 200, r.text
    out = {**r.json(), "code": inv["code"]}
    if confirm:
        assert c.post(f"/api/devices/{out['device_id']}/confirm", json={"ok": True}).json()["ok"]
    return out


def _ws(c, token):
    return c.websocket_connect("/api/devices/ws", headers={"Authorization": f"Bearer {token}"})


def _online(c, did):
    wait_for(lambda: next((d for d in c.get("/api/devices").json()["devices"] if d["id"] == did), {}).get("online")
             and next(d for d in c.get("/api/devices").json()["devices"] if d["id"] == did).get("hello"), 5)


def _call(c, sid, name, args=None, token=None) -> dict:
    token = token or turns.write_turn(sid, T)
    r = c.post(f"/api/devices/mcp/{sid}", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                 "params": {"name": name, "arguments": args or {}}},
               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def _text(res: dict) -> str:
    return " ".join(x.get("text", "") for x in res.get("content") or [] if x.get("type") == "text")


# ---- feature, pairing ----------------------------------------------------------------------------------------------
def test_off_by_default(client, mx):
    assert client.get("/api/settings").json()["devices_feature"] is False
    assert client.post("/api/devices/invites", json={}).status_code == 409
    assert client.post("/api/devices/pair", json={"code": "ABCDEFGH", "os": "linux"}).status_code == 404
    assert client.get("/api/devices/install/ABCDEFGH.sh").status_code == 404
    assert client.get("/link/ABCDEFGH").status_code == 410
    from maxxing import devices
    assert devices.visible(T) == []


def test_invite_install_download_pair_and_confirm(dv):
    inv = dv.post("/api/devices/invites", json={"os": "linux"}).json()
    code = inv["code"]
    assert len(code) == 8 and inv["expires_in"] == 900
    assert inv["commands"]["sh"] == f"curl -fsSL http://testserver/api/devices/install/{code}.sh | sh"
    assert inv["commands"]["ps1"] == f"irm http://testserver/api/devices/install/{code}.ps1 | iex"
    assert inv["deeplink"] == f"harnesslink://pair?s=http%3A%2F%2Ftestserver&c={code}"
    assert inv["link"] == f"http://testserver/link/{code}"
    sh = dv.get(f"/api/devices/install/{code}.sh")
    assert sh.status_code == 200 and "~/.local/bin" not in sh.text and '$HOME/.local/bin' in sh.text
    assert f"/api/devices/download/$os-$arch?code={code}" in sh.text and "com.apple.quarantine" in sh.text
    # runs in the foreground of the terminal (live log), nothing started in the background or at login
    assert "nohup" not in sh.text and 'exec "$f" </dev/tty' in sh.text
    assert "LaunchAgents/com.harnessmaxxing.link.plist" in sh.text and "autostart/harness-link.desktop" in sh.text
    assert subprocess.run(["sh", "-n"], input=sh.text, text=True).returncode == 0
    # the first "Harness PC" is stopped and unregistered too
    assert "pkill -x harness-pc" in sh.text and "LaunchAgents/com.harnessmaxxing.pc.plist" in sh.text
    ps = dv.get(f"/api/devices/install/{code.lower()}.ps1").text
    assert "LOCALAPPDATA" in ps and "harness-link.exe" in ps and f"windows-${{arch}}?code={code}" in ps
    assert "HarnessPC" in ps and "Invoke-WebRequest" in ps
    assert "Start-Process" not in ps and "try { & $exe }" in ps.splitlines()[-1] and "H A R N E S S" in ps and "'Path', 'User'" in ps
    assert "H A R N E S S" in sh.text and "HARNESS_LINK_NO_LOGO=1" in sh.text
    # the desktop app carries its pairing trailer
    d = dv.get(f"/api/devices/download/linux-amd64?code={code}")
    assert d.status_code == 200 and 'filename="harness-link"' in d.headers["content-disposition"]
    data = d.content
    assert int(d.headers["content-length"]) == len(data)
    assert data.startswith(b"APP-harness-link-linux-amd64") and data.endswith(b"HMLINK01")
    n = struct.unpack(">I", data[-12:-8])[0]
    assert json.loads(data[-12 - n:-12]) == {"server": "http://testserver", "code": code}
    # the APK is sent as it is
    apk = dv.get(f"/api/devices/download/android?code={code}")
    assert apk.content == b"APP-harness-link.apk" and "android.package-archive" in apk.headers["content-type"]
    assert dv.get(f"/api/devices/download/plan9-mips?code={code}").status_code == 404
    assert dv.get("/api/devices/download/linux-amd64?code=WRONGCOD").status_code == 400
    assert dv.post("/api/devices/pair", json={"code": "WRONGCOD", "os": "linux"}).json()["error"] == "bad_code"
    r = dv.post("/api/devices/pair", json={"code": code.lower(), "name": "laptop", "os": "linux", "arch": "amd64",
                                           "version": "0.1.0", "caps": CAPS_PC})
    assert r.status_code == 200 and r.json()["token"] and r.json()["device_id"].startswith("dev_")
    st = dv.get("/api/devices").json()
    dev = st["devices"][0]
    assert dev["confirmed"] is False and dev["name"] == "laptop" and dev["kind"] == "desktop"
    assert "token_hash" not in json.dumps(st) and st["invites"] == []
    from maxxing import devices
    assert devices.visible(T) == []                                  # waits for the user's yes
    assert dv.post("/api/devices/pair", json={"code": code, "os": "linux"}).status_code == 410   # one use
    # pasting the install command again: the reason in plain words, and the shell stops
    again = dv.get(f"/api/devices/install/{code}.sh")
    assert again.status_code == 200 and "already used" in again.text
    run = subprocess.run(["sh"], input=again.text, text=True, capture_output=True)
    assert run.returncode == 1 and "Add the computer again" in run.stderr
    assert "already used" in dv.get(f"/api/devices/install/{code}.ps1").text
    assert dv.post(f"/api/devices/{dev['id']}/confirm", json={"ok": True}).json()["ok"]
    assert [d["id"] for d in devices.visible(T)] == [dev["id"]]
    assert not dv.post(f"/api/devices/{dev['id']}/confirm", json={"ok": True}).json()["ok"]   # nothing waits


def test_the_app_is_told_when_it_is_accepted_and_its_mode(dv):
    p = _pair(dv, os_name="darwin", name="mac", caps=CAPS_PC, confirm=False)
    with _ws(dv, p["token"]) as ws:
        fd = FakeDevice(ws, os_name="darwin", caps=CAPS_PC).start()
        wait_for(lambda: fd.of("access"), 5)
        assert fd.of("access")[0] == {"t": "access", "ok": False, "mode": "control"}   # waits for the user's OK
        assert dv.post(f"/api/devices/{p['device_id']}/confirm", json={"ok": True}).json()["ok"]
        wait_for(lambda: len(fd.of("access")) == 2, 5)
        assert fd.of("access")[1] == {"t": "access", "ok": True, "mode": "control"}
        assert dv.put(f"/api/devices/{p['device_id']}", json={"mode": "view"}).status_code == 200
        wait_for(lambda: len(fd.of("access")) == 3, 5)
        assert fd.of("access")[2]["mode"] == "view"
        dv.put(f"/api/devices/{p['device_id']}", json={"name": "mac 2"})              # nothing new to tell
        time.sleep(0.3)
        assert len(fd.of("access")) == 3


def test_several_screens_the_one_used_is_chosen(dv):
    p = _pair(dv, os_name="windows", name="pc", caps=CAPS_PC)
    did = p["device_id"]
    with _ws(dv, p["token"]) as ws:
        ws.send_json({"t": "hello", "v": "0.1.0", "os": "windows", "arch": "amd64", "name": "pc", "caps": CAPS_PC,
                      "screen": {"w": 1920, "h": 1080, "scale": 1}, "display": 0,
                      "screens": [{"i": 0, "name": "Display 1", "w": 1920, "h": 1080, "main": True},
                                  {"i": 1, "name": "Display 2", "w": 2560, "h": 1440, "main": False}, "junk"]})
        wait_for(lambda: (next(iter(dv.get("/api/devices").json()["devices"]), {}).get("hello") or {}).get("screens"), 5)
        h = dv.get("/api/devices").json()["devices"][0]["hello"]
        assert [x["name"] for x in h["screens"]] == ["Display 1", "Display 2"] and h["display"] == 0
        assert ws.receive_json()["t"] == "access"
        r = dv.put(f"/api/devices/{did}", json={"display": 1})
        assert r.status_code == 200 and r.json()["display"] == 1
        assert ws.receive_json() == {"t": "display", "i": 1}
        assert dv.put(f"/api/devices/{did}", json={"display": 99}).status_code == 422
    with _ws(dv, p["token"]) as ws:                      # on the next connection the choice is sent again
        ws.send_json({"t": "hello", "v": "0.1.0", "os": "windows", "arch": "amd64", "name": "pc", "caps": CAPS_PC})
        got = [ws.receive_json(), ws.receive_json()]
        assert {"t": "display", "i": 1} in got


def test_codes_expire_and_wrong_codes_are_throttled(dv, monkeypatch):
    inv = dv.post("/api/devices/invites", json={}).json()
    real = time.time
    monkeypatch.setattr(store.time, "time", lambda: real() + 901)
    r = dv.post("/api/devices/pair", json={"code": inv["code"], "os": "android"})
    assert r.status_code == 410 and r.json()["error"] == "expired"
    monkeypatch.setattr(store.time, "time", real)
    for _ in range(devices_api.FAIL_MAX - 1):
        assert dv.post("/api/devices/pair", json={"code": "ZZZZZZZZ", "os": "android"}).status_code == 400
    assert dv.post("/api/devices/pair", json={"code": "ZZZZZZZZ", "os": "android"}).status_code == 429
    assert dv.get("/link/ZZZZZZZZ").status_code == 429


def test_phone_link_page(dv):
    code = dv.post("/api/devices/invites", json={"os": "android"}).json()["code"]
    r = dv.get(f"/link/{code}")
    assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
    assert "script-src" not in r.headers["content-security-policy"] and "<script" not in r.text
    assert f"/api/devices/download/android?code={code}" in r.text
    assert f"harnesslink://pair?s=http%3A%2F%2Ftestserver&amp;c={code}" in r.text and code in r.text
    assert dv.get("/link/NOTACODE").status_code == 410


def test_refused_device_is_told_to_forget_the_server(dv):
    p = _pair(dv, confirm=False)
    with _ws(dv, p["token"]) as ws:
        assert ws.receive_json() == {"t": "access", "ok": False, "mode": "control"}      # waits for the OK
        assert dv.post(f"/api/devices/{p['device_id']}/confirm", json={"ok": False}).json()["ok"]
        assert ws.receive_json() == {"t": "unpair"}
    assert dv.get("/api/devices").json()["devices"] == []
    with pytest.raises(Exception):
        with _ws(dv, p["token"]) as ws:                             # its token is gone: refused (HTTP 403)
            ws.receive_json()


def test_held_until_confirmed_then_online(dv):
    p = _pair(dv, confirm=False)
    with _ws(dv, p["token"]) as ws:
        dev = FakeDevice(ws).start()
        time.sleep(0.3)
        assert not dv.get("/api/devices").json()["devices"][0]["online"]
        dv.post(f"/api/devices/{p['device_id']}/confirm", json={"ok": True})
        _online(dv, p["device_id"])
        d = dv.get("/api/devices").json()["devices"][0]
        assert d["hello"]["screen"] == {"w": 1080, "h": 2400, "scale": 1} and d["version"] == "0.1.0"
        assert dev.of("state") == []                                  # nobody uses it: nothing said yet


def test_removed_device_is_revoked_at_once(dv):
    p = _pair(dv)
    with _ws(dv, p["token"]) as ws:
        dev = FakeDevice(ws).start()
        _online(dv, p["device_id"])
        assert dv.delete(f"/api/devices/{p['device_id']}").json()["ok"]
        wait_for(lambda: dev.unpaired and dev.closed, 5)
    with pytest.raises(Exception):
        with _ws(dv, p["token"]) as ws:
            ws.receive_json()
    assert dv.get("/api/devices").json()["devices"] == []


def test_removed_from_the_cli_the_app_is_told_too(dv):
    from maxxing import cli
    p = _pair(dv)
    with _ws(dv, p["token"]) as ws:
        dev = FakeDevice(ws).start()
        _online(dv, p["device_id"])
        assert cli.main(["devices", "remove", "Pixel 7"]) == 0
        wait_for(lambda: dev.unpaired, 8)


@pytest.mark.parametrize("name,args", [("zoom", {"x": 10, "y": 10, "w": float("nan"), "h": 50}),
                                       ("zoom", {"x": 10, "y": 10, "w": 50, "h": float("nan")}),
                                       ("screen", {"screen": float("inf")})])
def test_a_number_that_is_not_finite_is_refused(dv, name, args):
    p = _pair(dv, "linux", "laptop", CAPS_PC)
    did = p["device_id"]
    with _ws(dv, p["token"]) as ws:
        FakeDevice(ws, "linux", CAPS_PC, screens=[(1280, 720), (800, 600)]).start()
        _online(dv, did)
        tok = turns.write_turn("sessnf", T)
        _call(dv, "sessnf", "screenshot", {"device": did}, tok)
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {"device": did, **args}}}
        r = dv.post("/api/devices/mcp/sessnf", content=json.dumps(body),        # NaN / Infinity, as Python's json reads them
                    headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        assert r.status_code == 200, r.text
        assert r.json()["result"]["isError"] and "must be a number" in _text(r.json()["result"])


def test_claude_switches_the_screen_itself(dv, capsys):
    from maxxing import cli
    p = _pair(dv, "darwin", "mac", CAPS_PC)
    did = p["device_id"]
    with _ws(dv, p["token"]) as ws:
        dev = FakeDevice(ws, "darwin", CAPS_PC, screens=[(1512, 982), (2560, 1440)]).start()
        _online(dv, did)
        tok = turns.write_turn("sess0s", T)
        listed = _text(_call(dv, "sess0s", "devices", token=tok))
        assert "0 Display 1 1512x982 main" in listed and "1 Display 2 2560x1440" in listed and "you see 0" in listed
        _call(dv, "sess0s", "screenshot", {"device": did}, tok)
        assert "outside" in _text(_call(dv, "sess0s", "click", {"device": did, "x": 1300, "y": 10}, tok))
        r = _call(dv, "sess0s", "screen", {"device": did, "screen": 1}, tok)
        assert not r.get("isError"), r
        assert dev.display == 1 and "Now on screen 1 (Display 2)" in _text(r) and "1280x720 picture" in _text(r)
        assert dv.get("/api/devices").json()["devices"][0]["display"] == 1          # the menus follow
        assert not _call(dv, "sess0s", "click", {"device": did, "x": 1270, "y": 10}, tok).get("isError")
        assert "no screen 5" in _text(_call(dv, "sess0s", "screen", {"device": did, "screen": 5}, tok))
        store.update(did, mode="view")                                              # looking: allowed in view only
        assert not _call(dv, "sess0s", "screen", {"device": did, "screen": -1}, tok).get("isError")
        assert dev.display == 0
        capsys.readouterr()
        assert cli.main(["devices", "list"]) == 0
        out = capsys.readouterr().out
        assert "* screen 0  Display 1  1512x982  main" in out and "  screen 1  Display 2" in out
        assert cli.main(["devices", "screen", "mac", "1"]) == 0 and "screen 1" in capsys.readouterr().out
        wait_for(lambda: dev.display == 1, 6)                                       # told by the ticker
        assert cli.main(["devices", "screen", "mac", "main"]) == 0 and store.get(did)["display"] == -1
        assert cli.main(["devices", "screen", "mac", "x"]) == 1


# ---- tools -------------------------------------------------------------------------------------------------------------
def test_screenshot_scales_and_actions_use_its_pixels(dv):
    p = _pair(dv, "linux", "laptop", CAPS_PC)
    with _ws(dv, p["token"]) as ws:
        dev = FakeDevice(ws, "linux", CAPS_PC, (2560, 1440)).start()
        _online(dv, p["device_id"])
        did = p["device_id"]
        tok = turns.write_turn("sess01", T)
        listed = _text(_call(dv, "sess01", "devices", token=tok))
        assert "laptop" in listed and did in listed and "control" in listed and "2560x1440" in listed
        # a click before any screenshot: the screen scaled to 1280 wide
        r = _call(dv, "sess01", "click", {"device": "laptop", "x": 640, "y": 360}, tok)
        assert not r.get("isError"), r
        inp = dev.of("input")[-1]
        assert inp == {"t": "input", "id": inp["id"], "sw": 1280, "sh": 720, "a": "click", "x": 640, "y": 360,
                       "button": "left", "double": False}
        assert r["content"][0]["type"] == "image" and r["content"][0]["mimeType"] == "image/jpeg"
        r = _call(dv, "sess01", "screenshot", {"device": did}, tok)
        shot = dev.of("shot")[-1]
        assert shot["max_w"] == 1280 and "1280x720 picture" in _text(r)
        assert base64.b64decode(r["content"][0]["data"]).startswith(b"\xff\xd8")
        assert _call(dv, "sess01", "click", {"device": did, "x": 2000, "y": 10}, tok)["isError"]   # outside
        _call(dv, "sess01", "drag", {"device": did, "x1": 1, "y1": 2, "x2": 300, "y2": 400, "ms": 200}, tok)
        assert {k: dev.of("input")[-1][k] for k in ("a", "x", "y", "x2", "y2", "ms")} == \
            {"a": "drag", "x": 1, "y": 2, "x2": 300, "y2": 400, "ms": 200}
        _call(dv, "sess01", "scroll", {"device": did, "x": 10, "y": 10, "dy": 3}, tok)
        assert dev.of("input")[-1]["a"] == "scroll" and dev.of("input")[-1]["dy"] == 3
        _call(dv, "sess01", "type", {"device": did, "text": "hello"}, tok)
        assert dev.of("input")[-1]["text"] == "hello"
        _call(dv, "sess01", "key", {"device": did, "keys": "Ctrl+S"}, tok)
        assert dev.of("input")[-1]["keys"] == "ctrl+s"
        _call(dv, "sess01", "long_press", {"device": did, "x": 5, "y": 5}, tok)
        _call(dv, "sess01", "move", {"device": did, "x": 5, "y": 5}, tok)
        assert [m["a"] for m in dev.of("input")[-2:]] == ["long_press", "move"]
        z = _call(dv, "sess01", "zoom", {"device": did, "x": 100, "y": 100, "w": 200, "h": 50}, tok)
        assert dev.of("shot")[-1]["crop"] == {"x": 100, "y": 100, "w": 200, "h": 50} and "400x100" in _text(z)
        assert "ui_tree" not in [m["t"] for m in dev.got]
        t = _call(dv, "sess01", "ui_tree", {"device": did}, tok)
        assert t["isError"] and "no element tree" in _text(t) and not dev.of("tree")
        r = _call(dv, "sess01", "open_app", {"device": did, "name": "whats"}, tok)
        assert dev.of("open")[-1]["app"] == "com.whatsapp" and "Opened WhatsApp" in _text(r)
        assert _call(dv, "sess01", "open_app", {"device": did, "name": "nothing"}, tok)["isError"]
        assert "Settings (com.android.settings)" in _text(_call(dv, "sess01", "apps", {"device": did}, tok))
        assert _call(dv, "sess01", "click", {"device": "unknown", "x": 1, "y": 1}, tok)["isError"]
        acts = dv.get("/api/devices").json()["actions"]
        assert acts[0]["device"] == did and any(a["tool"] == "type" and a["args"]["text"] == "<5 chars>" for a in acts)
        assert "hello" not in json.dumps(acts)
        # while Claude acts, the device is told (and the session line knows)
        assert dev.of("state")[-1] == {"t": "state", "busy": True, "by": "claude"}
        u = dv.get("/api/devices/session/sess01").json()
        assert u["using"][0]["id"] == did and u["using"][0]["name"] == "laptop"


def test_phone_tree_elements_and_errors(dv):
    p = _pair(dv)
    with _ws(dv, p["token"]) as ws:
        dev = FakeDevice(ws).start()
        _online(dv, p["device_id"])
        did = p["device_id"]
        tok = turns.write_turn("sess02", T)
        _call(dv, "sess02", "screenshot", {"device": did}, tok)
        r = _call(dv, "sess02", "ui_tree", {"device": did}, tok)
        assert dev.of("tree")[-1]["sw"] == 1080 and dev.of("tree")[-1]["sh"] == 2400
        assert '[n1] button "Send" @10,20,100,40 click' in _text(r) and "(Message)" in _text(r)
        _call(dv, "sess02", "tap_element", {"device": did, "element": "n1"}, tok)
        assert dev.of("tap_node")[-1]["node"] == "n1"
        _call(dv, "sess02", "set_text", {"device": did, "element": "n2", "text": "hi"}, tok)
        assert dev.of("set_text")[-1] == {"t": "set_text", "id": dev.of("set_text")[-1]["id"], "node": "n2", "text": "hi"}
        _call(dv, "sess02", "key", {"device": did, "keys": "back"}, tok)
        dev.errors["shot"] = ("protected", "FLAG_SECURE")
        r = _call(dv, "sess02", "screenshot", {"device": did}, tok)
        assert r["isError"] and "protected screen" in _text(r)
        dev.errors["shot"] = ("locked", "")
        assert "is locked" in _text(_call(dv, "sess02", "screenshot", {"device": did}, tok))
        del dev.errors["shot"]
        ws.send_json({"t": "paused", "on": True})
        wait_for(lambda: dv.get("/api/devices").json()["devices"][0]["paused"], 5)
        r = _call(dv, "sess02", "screenshot", {"device": did}, tok)
        assert r["isError"] and "paused" in _text(r)
        ws.send_json({"t": "paused", "on": False})
        wait_for(lambda: not dv.get("/api/devices").json()["devices"][0]["paused"], 5)
        assert not _call(dv, "sess02", "screenshot", {"device": did}, tok).get("isError")
    r = _call(dv, "sess02", "screenshot", {"device": did}, tok)
    assert r["isError"] and "offline" in _text(r) and "open the Harness Link app" in _text(r)


def test_view_only_device(dv):
    p = _pair(dv)
    did = p["device_id"]
    assert dv.put(f"/api/devices/{did}", json={"mode": "view"}).json()["mode"] == "view"
    with _ws(dv, p["token"]) as ws:
        dev = FakeDevice(ws).start()
        _online(dv, did)
        tok = turns.write_turn("sess03", T)
        assert not _call(dv, "sess03", "screenshot", {"device": did}, tok).get("isError")
        for name, args in (("click", {"x": 1, "y": 1}), ("type", {"text": "x"}), ("open_app", {"name": "x"}),
                           ("tap_element", {"element": "n1"}), ("apps", {})):
            r = _call(dv, "sess03", name, {"device": did, **args}, tok)
            assert r["isError"] and "view only" in _text(r), name
        assert not dev.of("input") and not dev.of("open")
        assert not _call(dv, "sess03", "ui_tree", {"device": did}, tok).get("isError")


def test_scope_of_projects_and_agents(dv, topic):
    from maxxing import agents, approvals, devices
    p = _pair(dv)
    did = p["device_id"]
    assert dv.put(f"/api/devices/{did}", json={"scope": ["bad scope"]}).status_code == 400
    dv.put(f"/api/devices/{did}", json={"scope": ["project:other"]})
    assert devices.visible(T) == []
    r = _call(dv, "sess04", "screenshot", {"device": did})
    assert r["isError"] and "No device" in _text(r)
    assert "No device is available" in _text(_call(dv, "sess04", "devices"))
    dv.put(f"/api/devices/{did}", json={"scope": ["project:acme"]})
    assert [d["id"] for d in devices.visible(T)] == [did]
    # agents: only once their owner turned the device on
    assert dv.put("/api/settings", json={"agents_page": True}).status_code == 200
    assert dv.post("/api/agents", json={"topic_path": T, "name": "writer"}).status_code == 200
    assert devices.visible(A) == []
    r = agents.request_change(A, {"devices": [did]}, session="sess-mgr")
    assert r["asked"] == ["devices"] and agents.load(A)["devices"] == []
    assert f"devices: + {did}" in approvals.get(r["request"])["input"]["description"]
    approvals.decide(r["request"], "allow")
    assert agents.load(A)["devices"] == [did] and [d["id"] for d in devices.visible(A)] == [did]
    assert agents.request_change(A, {"devices": []}, session="sess-mgr")["applied"] == ["devices"]
    assert devices.visible(A) == []
    with pytest.raises(agents.AgentError):
        agents.update(A, {"devices": ["not-an-id"]})
    # a free agent named in the device's access; a sandboxed one also needs it in its agent.json
    dv.put(f"/api/devices/{did}", json={"scope": [f"agent:{A}"]})
    agents.update(A, {"sandbox": False})
    assert [d["id"] for d in devices.visible(A)] == [did] and devices.visible(T) == []
    agents.update(A, {"sandbox": True})
    assert devices.visible(A) == []
    agents.update(A, {"devices": [did]})
    assert [d["id"] for d in devices.visible(A)] == [did]


def test_the_person_takes_over_and_hands_back(dv):
    p = _pair(dv)
    did = p["device_id"]
    with _ws(dv, p["token"]) as ws:
        dev = FakeDevice(ws).start()
        _online(dv, did)
        tok = turns.write_turn("sess05", T)
        _call(dv, "sess05", "screenshot", {"device": did}, tok)
        with pytest.raises(Exception):
            with dv.websocket_connect(f"/api/devices/{did}/live?t=nope") as lv:
                lv.receive_text()
        t = dv.post("/api/devices/live-token").json()["token"]
        with dv.websocket_connect(f"/api/devices/{did}/live?t={t}") as lv:
            first = lv.receive()
            got = [first]
            while not (any(m.get("bytes") for m in got) and any(m.get("text") for m in got)):
                got.append(lv.receive())
            assert any((m.get("bytes") or b"").startswith(b"\xff\xd8") for m in got)
            assert any(json.loads(m["text"]).get("t") == "state" for m in got if m.get("text"))
            lv.send_json({"t": "take"})
            wait_for(lambda: dv.get("/api/devices").json()["devices"][0]["human"], 5)
            r = _call(dv, "sess05", "click", {"device": did, "x": 10, "y": 10}, tok)
            assert r["isError"] and "using" in _text(r)
            assert not _call(dv, "sess05", "screenshot", {"device": did}, tok).get("isError")   # looking is fine
            n = len(dev.of("input"))
            lv.send_json({"t": "input", "a": "click", "x": 50, "y": 60, "sw": 1080, "sh": 2400, "evil": 1})
            wait_for(lambda: len(dev.of("input")) > n, 5)
            hm = dev.of("input")[-1]
            assert hm["x"] == 50 and hm["sw"] == 1080 and "evil" not in hm
            wait_for(lambda: {"t": "state", "busy": True, "by": "human"} in dev.got, 5)
            lv.send_json({"t": "release"})
            wait_for(lambda: not dv.get("/api/devices").json()["devices"][0]["human"], 5)
            assert not _call(dv, "sess05", "click", {"device": did, "x": 10, "y": 10}, tok).get("isError")
        wait_for(lambda: not dv.get("/api/devices").json()["devices"][0]["watched"], 5)
        # the app is told the live view opened and closed; its pictures are marked live (not in its terminal log)
        wait_for(lambda: dev.of("watch") == [{"t": "watch", "on": True}, {"t": "watch", "on": False}], 5)
        assert any(m.get("live") for m in dev.of("shot")) and not all(m.get("live") for m in dev.of("shot"))


def _ask_in_thread(dv, sid, did, tok, out):
    def run():
        out.append(_call(dv, sid, "ask_human", {"device": did, "message": "Type the SMS code"}, tok))
    th = threading.Thread(target=run, daemon=True)
    th.start()
    wait_for(lambda: asks.pending(session=sid), 5)
    return th


def test_ask_human_done_skip_timeout(dv, monkeypatch):
    monkeypatch.setattr(turns, "turn_alive", lambda sid: True)
    p = _pair(dv)
    did = p["device_id"]
    with _ws(dv, p["token"]) as ws:
        FakeDevice(ws).start()
        _online(dv, did)
        tok = turns.write_turn("sess06", T)
        # done: handed back from the live view, with a word
        out: list = []
        th = _ask_in_thread(dv, "sess06", did, tok, out)
        a = dv.get("/api/devices/session/sess06").json()["asks"][0]
        assert a["message"] == "Type the SMS code" and a["device_name"] == "Pixel 7"
        s = dv.get("/api/sessions").json()
        assert isinstance(s, list)
        t = dv.post("/api/devices/live-token").json()["token"]
        with dv.websocket_connect(f"/api/devices/{did}/live?t={t}") as lv:
            lv.send_json({"t": "take"})
            lv.send_json({"t": "release", "done": True, "note": "code typed"})
            th.join(10)
        res = out[0]
        assert "handed Pixel 7 back" in _text(res) and "code typed" in _text(res)
        assert any(x["type"] == "image" for x in res["content"])
        # skip, from the session's card
        out = []
        th = _ask_in_thread(dv, "sess06", did, tok, out)
        rid = asks.pending(session="sess06")[0]["id"]
        assert dv.post(f"/api/devices/asks/{rid}", json={"action": "skip"}).json()["status"] == "skip"
        assert dv.post(f"/api/devices/asks/{rid}", json={"action": "done"}).status_code == 409
        th.join(10)
        assert "skipped" in _text(out[0])
        # nobody answers
        monkeypatch.setattr(asks, "ASK_WAIT_S", 0.5)
        out = []
        th = _ask_in_thread(dv, "sess06", did, tok, out)
        th.join(10)
        assert "Nobody answered" in _text(out[0])
        # the turn stops
        monkeypatch.setattr(asks, "ASK_WAIT_S", 600)
        monkeypatch.setattr(turns, "turn_alive", lambda sid: False)
        out = []
        th = _ask_in_thread(dv, "sess06", did, tok, out)
        th.join(10)
        assert "cancelled" in _text(out[0]) and asks.pending() == []


def test_mcp_route_needs_loopback_and_the_turns_token(dv, monkeypatch):
    tok = turns.write_turn("sess07", T)
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert dv.post("/api/devices/mcp/sess07", json=body, headers={"Authorization": "Bearer nope"}).status_code == 403
    r = dv.post("/api/devices/mcp/sess07", json=body, headers={"Authorization": f"Bearer {tok}"}).json()
    names = {t["name"] for t in r["result"]["tools"]}
    assert {"devices", "screenshot", "click", "ui_tree", "ask_human", "open_app"} <= names
    monkeypatch.setattr(devices_api, "loopback", lambda conn: False)
    assert dv.post("/api/devices/mcp/sess07", json=body, headers={"Authorization": f"Bearer {tok}"}).status_code == 403
    turns.end_turn("sess07")
    assert turns.read_turn("sess07") is None


def test_the_mcp_script_answers_alone(mx):
    script = Path(__file__).resolve().parent.parent / "maxxing" / "devices_mcp.py"
    lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    r = subprocess.run([sys.executable, "-I", str(script)], input="\n".join(json.dumps(x) for x in lines) + "\n",
                       capture_output=True, text=True, timeout=20,
                       env={"MAXXING_DEVICES_URL": "http://127.0.0.1:9/api/devices/mcp/x", "PATH": "/usr/bin:/bin"})
    out = [json.loads(x) for x in r.stdout.splitlines()]
    assert out[0]["result"]["serverInfo"]["name"] == "harness-devices"
    assert any(o.get("id") == 2 and o["result"]["tools"] == [] for o in out)


# ---- runner, CLI, guards, doctor -----------------------------------------------------------------------------------------
def test_a_turn_gets_the_devices_only_when_one_is_visible(dv):
    from maxxing.sessions import runner
    assert runner.devices_args("sess08", T, {}) == []
    p = _pair(dv, confirm=False)
    assert runner.devices_args("sess08", T, {}) == []                 # not accepted yet
    dv.post(f"/api/devices/{p['device_id']}/confirm", json={"ok": True})
    args = runner.devices_args("sess08", T, {})
    assert args[0] == "--mcp-config" and args[2:] == ["--allowedTools", "mcp__harness-devices"]
    spec = json.loads(Path(args[1]).read_text())["mcpServers"]["harness-devices"]
    assert oct(Path(args[1]).stat().st_mode & 0o777) == "0o600"
    assert spec["env"]["MAXXING_DEVICES_URL"].endswith("/api/devices/mcp/sess08")
    assert turns.check_turn("sess08", spec["env"]["MAXXING_DEVICES_TOKEN"])["path"] == T
    web = ["--mcp-config", "/x.json", "--allowedTools", "mcp__maxxing-browser"]
    assert runner.devices_args("sess09", T, {}, web)[2:] == [] and web[-1] == "mcp__maxxing-browser,mcp__harness-devices"
    agent = {"args": ["--allowedTools", "Read"]}
    runner.devices_args("sess10", T, agent)
    assert agent["args"] == ["--allowedTools", "Read,mcp__harness-devices"]
    assert "--allowedTools" not in runner.devices_args("sess11", T, {"approvals_forced": True})
    runner.devices_done("sess08")
    assert not Path(args[1]).exists() and turns.read_turn("sess08") is None
    dv.put("/api/settings", json={"devices_feature": False})
    assert runner.devices_args("sess12", T, {}) == []


def test_a_session_turn_lists_the_device_tools(dv, topic, mx):
    from conftest import wait_idle
    _pair(dv)
    sid = dv.post("/api/sessions", json={"path": T, "message": "NOTOOL hi"}).json()["id"]
    wait_idle(dv, sid)
    calls = [json.loads(ln) for ln in (mx["fake_dir"] / "calls.jsonl").read_text().splitlines()]
    argv = calls[-1]["argv"]
    assert any(a.endswith(f"{sid}.mcp.json") and "devices" in a for a in argv)
    assert "Harness Link" in argv[argv.index("--append-system-prompt") + 1]
    assert turns.read_turn(sid) is None


def test_cli(dv, capsys):
    from maxxing import cli
    assert cli.main(["devices", "add", "--os", "linux"]) == 0
    out = capsys.readouterr().out
    assert "curl -fsSL" in out and "/api/devices/install/" in out and "PowerShell" not in out
    code = out.split("Code ", 1)[1].split()[0]
    did = dv.post("/api/devices/pair", json={"code": code, "os": "linux", "name": "box"}).json()["device_id"]
    assert cli.main(["devices", "list"]) == 0 and "waiting for your OK" in capsys.readouterr().out
    assert cli.main(["devices", "confirm", "box"]) == 0
    assert cli.main(["devices", "rename", did, "Office PC"]) == 0
    assert cli.main(["devices", "mode", "Office PC", "view"]) == 0
    assert cli.main(["devices", "access", did, "--project", "acme", "--agent", A]) == 0
    d = store.get(did)
    assert d["name"] == "Office PC" and d["mode"] == "view" and d["scope"] == ["project:acme", f"agent:{A}"]
    assert cli.main(["devices", "access", did, "--all"]) == 0 and store.get(did)["scope"] == ["*"]
    assert cli.main(["devices", "remove", "nothing"]) == 1
    assert cli.main(["devices", "disable"]) == 0
    assert cli.main(["devices", "add"]) == 1


def test_an_agent_turn_cannot_manage_devices(mx, monkeypatch):
    from maxxing import agent_guard
    monkeypatch.setattr(agent_guard, "agent_turn", lambda: {"path": A, "tampered": False})
    assert "not allowed" in agent_guard.check_cli(["devices", "confirm", "dev_12345678"])
    assert "not allowed" in agent_guard.check_cli(["devices", "access", "dev_12345678", "--all"])
    assert agent_guard.check_cli(["devices", "list"]) is None


def test_an_agent_turn_cannot_switch_the_screen_of_a_device(mx, monkeypatch):
    from maxxing import agent_guard                              # the CLI does not check the device's scope: the MCP tool does
    monkeypatch.setattr(agent_guard, "agent_turn", lambda: {"path": A, "tampered": False})
    assert "not allowed" in agent_guard.check_cli(["devices", "screen", "dev_12345678", "2"])


def test_doctor(dv, monkeypatch):
    from maxxing import cmd_core
    assert cmd_core.check_devices()["level"] == "ok"
    p = _pair(dv, confirm=False)
    c = cmd_core.check_devices()
    assert c["level"] == "warn" and "Pixel 7" in c["title"]
    dv.post(f"/api/devices/{p['device_id']}/confirm", json={"ok": True})
    monkeypatch.setattr(dist, "latest_version", lambda: "0.2.0")
    assert "out of date" in cmd_core.check_devices()["title"]
    dv.put("/api/settings", json={"devices_feature": False})
    assert cmd_core.check_devices() is None


def test_unconfirmed_devices_expire(dv, monkeypatch):
    _pair(dv, confirm=False)
    real = time.time
    monkeypatch.setattr(store.time, "time", lambda: real() + store.CANDIDATE_TTL + 1)
    assert store.devices() == []


def test_security_loopback_helper(mx):
    from types import SimpleNamespace
    assert security.loopback(SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={}))
    assert not security.loopback(SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"),
                                                 headers={"x-forwarded-for": "1.2.3.4"}))
    assert not security.loopback(SimpleNamespace(client=SimpleNamespace(host="100.101.102.104"), headers={}))


def test_an_action_with_a_line_separator_stays_in_the_log(dv):
    store.log_action("d1", "type", {"keys": "a b"}, True, 5)
    store.log_action("d1", "click", {"x": 1}, True, 5)
    assert [a["tool"] for a in store.actions()] == ["click", "type"]


def test_an_action_log_with_invalid_utf8_is_still_read(dv):
    store.log_action("d1", "click", {"x": 1}, True, 5)
    f = store.home() / "actions.jsonl"
    f.write_bytes(b"\xff{}\n" + f.read_bytes())
    assert [a["tool"] for a in store.actions(30)] == ["click"]


def test_device_turn_ids_reject_a_trailing_newline():
    from maxxing.devices import turns
    assert turns.SID_RE.match("abcdef")
    assert not turns.SID_RE.match("abcdef\n")


def test_a_device_ask_whose_alive_check_raises_is_not_left_pending(monkeypatch):
    import asyncio
    from maxxing.devices import asks
    monkeypatch.setattr(asks, "_announce", lambda d: None)
    monkeypatch.setattr(asks, "ASK_WAIT_S", 0.3)

    async def alive():
        raise RuntimeError("boom")

    async def go():
        with pytest.raises(RuntimeError):
            await asks.ask("sess09", "web", {"id": "dev1", "name": "x"}, "go", alive=alive)
    asyncio.run(go())
    assert asks.pending(session="sess09") == [] and not asks._futs


def test_a_device_ask_survives_a_lone_surrogate_and_a_cancel_during_the_announce(monkeypatch):
    import asyncio
    from maxxing.devices import asks

    def slow(d):
        time.sleep(0.3)

    monkeypatch.setattr(asks, "_announce", slow)

    async def go():
        t = asyncio.create_task(asks.ask("sess07", "web", {"id": "dev1", "name": "x"}, "code \ud83d sent\x00"))
        await asyncio.sleep(0.05)
        p = asks.pending(session="sess07")
        json.dumps(p).encode("utf-8")
        assert p[0]["message"] == "code ? sent"
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    asyncio.run(go())
    assert asks.pending() == [] and not asks._futs


def test_a_hello_with_nan_in_the_screen_stays_listable(dv):
    import asyncio
    from maxxing.devices import hub as hubmod
    c = hubmod.Conn(None, "d1")
    asyncio.run(hubmod.hub()._on(c, {"t": "hello", "screen": {"w": float("nan"), "h": 100, "scale": float("inf")}}))
    assert c.hello["screen"] == {"h": 100}


def test_an_action_with_a_lone_surrogate_enters_the_log(dv):
    store.log_action("d1", "click", {"name": "a\ud83db"}, False, 5, error="bad \ud83d")
    assert [a["tool"] for a in store.actions()] == ["click"]


def test_a_hello_with_a_lone_surrogate_in_caps_is_still_recorded(dv):
    p = _pair(dv, os_name="windows", name="pc", caps=CAPS_PC)
    with _ws(dv, p["token"]) as ws:
        ws.send_json({"t": "hello", "v": "9.9.9", "os": "windows", "arch": "amd64", "name": "pc",
                      "caps": ["screen", "\ud800abc"], "screen": {"w": 1920, "h": 1080, "scale": 1}})
        wait_for(lambda: (dv.get("/api/devices").json()["devices"][0].get("hello") or {}).get("v") == "9.9.9", 5)
        assert ws.receive_json()["t"] == "access"


def test_a_device_ask_answered_with_a_lone_surrogate_note_stays_encodable(monkeypatch):
    import asyncio
    from maxxing.devices import asks
    monkeypatch.setattr(asks, "_announce", lambda d: None)

    async def go():
        t = asyncio.create_task(asks.ask("sess08", "web", {"id": "dev1", "name": "x"}, "go"))
        await asyncio.sleep(0.05)
        rid = asks.pending(session="sess08")[0]["id"]
        done = asks.decide(rid, "done", "x\ud800")
        json.dumps(done).encode("utf-8")
        assert done["note"] == "x?"
        await t
    asyncio.run(go())


def test_a_huge_number_from_the_app_or_a_tool_is_refused_not_a_crash(dv):
    from maxxing.devices import tools
    with pytest.raises(tools.Refused):
        tools._num({"x": 10 ** 400}, "x")
    p = _pair(dv, os_name="windows", name="pc", caps=CAPS_PC)
    with _ws(dv, p["token"]) as ws:
        ws.send_json({"t": "hello", "v": "0.1.0", "os": "windows", "arch": "amd64", "name": "pc", "caps": CAPS_PC,
                      "screen": {"w": 10 ** 400, "h": 1080, "scale": 1}})
        ws.send_json({"t": "paused", "on": True})
        wait_for(lambda: dv.get("/api/devices").json()["devices"][0]["paused"], 5)


def test_a_devices_file_that_does_not_parse_is_kept_before_it_is_rewritten(dv):
    store.new_invite()
    path = store._path()
    path.write_text(path.read_text()[:-4])              # cut: no longer JSON
    store.new_invite()
    assert list(path.parent.glob("devices.json.damaged-*"))


def test_a_strange_answer_from_a_device_is_an_error_not_a_crash(monkeypatch):
    from maxxing.devices import tools

    class H:
        def __init__(self, ans): self.ans = ans
        async def request(self, did, msg): return self.ans

    for ans in ({"jpeg": "x", "w": "abc", "h": 5}, {"jpeg": "x", "w": float("inf"), "h": 5}, {"jpeg": "x", "w": 10**400, "h": 5}):
        monkeypatch.setattr(tools, "hub", lambda ans=ans: H(ans))
        with pytest.raises(tools.DeviceError):
            asyncio.run(tools._shot("d"))
    assert tools._tree_text([{"id": "a", "b": [float("inf"), 1, 10**400, 2]}]).startswith("[a]")
    assert tools._list(5) == [] and tools._list([1]) == [1]
