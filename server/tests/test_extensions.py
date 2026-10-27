import json
import shutil
import sys
from pathlib import Path

from _org_helpers import client, org  # noqa: F401
from maxxing import config, extensions

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "extensions"


def _ext(org, eid, manifest, api=None, page=None):
    d = org.ws / "extensions" / eid
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(manifest if isinstance(manifest, str) else json.dumps(manifest))
    if api is not None:
        (d / "api.py").write_text(api)
    if page is not None:
        (d / "page.js").write_text(page)
    return d


def test_scan_isolates_errors(client, org):
    _ext(org, "good", {"name": "Good", "type": "widget", "icon": "star", "version": "1", "span": 5},
         "def card(ctx):\n    return {'blocks': []}\n")
    _ext(org, "broken-json", "{not json")
    _ext(org, "boom", {"type": "widget"}, "raise RuntimeError('import failed')\n")
    _ext(org, "nocard", {"type": "widget"}, "x = 1\n")
    _ext(org, "tasks", {"type": "widget"}, "def card(ctx): return {}\n")                # reserved id
    _ext(org, "mismatch", {"id": "other", "type": "page"}, page="export function mount(){}")
    _ext(org, "nopage", {"type": "page"})
    (org.ws / "extensions" / "Bad_Name").mkdir()
    lst = {e["id"]: e for e in client.get("/api/extensions").json()}
    assert lst["good"]["error"] is None and lst["good"]["span"] == 3 and lst["good"]["has_api"]
    assert lst["good"]["name"] == "Good" and lst["good"]["enabled"] is True
    assert "not valid JSON" in lst["broken-json"]["error"]
    assert "import failed" in lst["boom"]["error"]
    assert "card(ctx)" in lst["nocard"]["error"]
    assert "built-in" in lst["tasks"]["error"]
    assert "differs" in lst["mismatch"]["error"]
    assert "page.js" in lst["nopage"]["error"]
    assert "slug" in lst["Bad_Name"]["error"]
    assert "mx_ext_boom" not in sys.modules and "mx_ext_good" in sys.modules


def test_enable_disable_reload(client, org):
    _ext(org, "w", {"type": "widget"}, "def card(ctx):\n    return {'title': 'v1', 'blocks': []}\n")
    assert client.get("/api/extensions").json()[0]["enabled"] is True
    assert client.patch("/api/extensions/w", json={"enabled": False}).json() == {"ok": True}
    assert config.load_config()["extensions"]["disabled"] == ["w"]
    assert client.get("/api/extensions").json()[0]["enabled"] is False
    assert client.get("/api/ext/w/x").status_code == 404
    assert client.patch("/api/extensions/w", json={"enabled": True}).json() == {"ok": True}
    assert config.load_config()["extensions"]["disabled"] == []
    assert client.patch("/api/extensions/nope", json={"enabled": True}).status_code == 404

    _ext(org, "later", {"type": "widget"}, "def card(ctx):\n    return {'blocks': []}\n")
    assert len(client.get("/api/extensions").json()) == 2                 # new folders are picked up
    assert {e["id"] for e in client.post("/api/extensions/reload").json()} == {"w", "later"}


def test_forwarding(client, org):
    api = '''
import json
def handle(ctx, method, path, query, body):
    if path == "echo":
        return {"method": method, "path": path, "query": query, "body": body, "ws": ctx["workspace"],
                "secret": ctx["secret"]("API_TOKEN"), "tz": ctx["config"]["timezone"]}
    if path == "created":
        return 201, {"ok": True}
    if path == "bad":
        raise ValueError("bad input")
    if path == "none":
        return None
    if path == "crash":
        1 / 0
    if path == "nonjson":
        return {"x": object()}
    raise LookupError("unknown " + path)
'''
    _ext(org, "svc", {"type": "page"}, api, "export function mount(el){ el.textContent='hi' }")
    from maxxing import vault
    vault.put("API_TOKEN", "tok-123456")
    r = client.post("/api/ext/svc/echo?a=1", json={"x": 2}).json()
    assert r == {"method": "POST", "path": "echo", "query": {"a": "1"}, "body": {"x": 2}, "ws": str(org.ws),
                 "secret": "tok-123456", "tz": "UTC"}
    assert client.get("/api/ext/svc/echo").json()["body"] is None
    r = client.get("/api/ext/svc/created")
    assert r.status_code == 201
    assert client.get("/api/ext/svc/bad").json() == {"error": "bad_request", "message": "bad input"}
    assert client.get("/api/ext/svc/none").json() == {"ok": True}
    assert client.get("/api/ext/svc/crash").json()["error"] == "extension_error"
    assert client.get("/api/ext/svc/nonjson").status_code == 500
    assert client.get("/api/ext/svc/missing").status_code == 404
    assert client.get("/api/ext/svc").status_code == 404                      # path "" -> LookupError
    assert client.get("/api/ext/nope/x").status_code == 404
    assert client.post("/api/ext/svc/echo", json={}, headers={"X-Maxxing": ""}).status_code == 403
    assert (Path(org.state) / "extensions" / "svc").is_dir()

    r = client.get("/ext/svc/page.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"] and "mount" in r.text
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/ext/nope/page.js").status_code == 404
    client.cookies.clear()
    assert client.get("/ext/svc/page.js").status_code == 401
    assert client.get("/api/ext/svc/echo").status_code == 401


def test_examples(client, org):
    for name in ("hello-widget", "notes-page"):
        shutil.copytree(EXAMPLES / name, org.ws / "extensions" / name)
    (org.ws / "projects" / "acme").mkdir(parents=True)
    lst = {e["id"]: e for e in client.post("/api/extensions/reload").json()}
    assert lst["hello-widget"]["error"] is None and lst["notes-page"]["error"] is None
    assert lst["notes-page"]["type"] == "page" and lst["notes-page"]["has_page"]
    page = org.ws / "extensions" / "notes-page" / "page.js"
    assert lst["notes-page"]["page_v"] == page.stat().st_mtime_ns // 1_000_000 and lst["hello-widget"]["page_v"] is None

    w = client.get("/api/dashboard/widgets/hello-widget").json()
    assert w["error"] is None and w["source"] == "extension"
    types_ = [b["type"] for b in w["card"]["blocks"]]
    assert types_ == ["stats", "list", "chart"] and w["card"]["blocks"][1]["items"][0]["title"] == "acme"

    assert client.get("/api/ext/notes-page/notes").json() == {"text": "", "saved": None}
    saved = client.put("/api/ext/notes-page/notes", json={"text": "hello"}).json()
    assert saved["text"] == "hello" and client.get("/api/ext/notes-page/notes").json()["text"] == "hello"
    assert client.put("/api/ext/notes-page/notes", json={"nope": 1}).status_code == 400
    assert client.delete("/api/ext/notes-page/notes").status_code == 405
    assert "export function mount" in client.get("/ext/notes-page/page.js").text


def test_clean_card():
    import pytest
    with pytest.raises(ValueError):
        extensions.clean_card([1])
    with pytest.raises(ValueError):
        extensions.clean_card({"blocks": "x"})
    c = extensions.clean_card({"title": "t", "status": "purple", "junk": 1,
                               "blocks": [{"type": "stat", "label": "a", "value": 1}, {"type": "iframe"}, 3]})
    assert c == {"title": "t", "blocks": [{"type": "stat", "label": "a", "value": 1}]}


def test_pin_page_in_sidebar(client, org):
    _ext(org, "notes", {"type": "page"}, page="export function mount(el){}")
    _ext(org, "w", {"type": "widget"}, "def card(ctx):\n    return {'blocks': []}\n")
    lst = {e["id"]: e for e in client.get("/api/extensions").json()}
    assert lst["notes"]["pinned"] is False and lst["w"]["pinned"] is False       # default: under "Extensions"
    assert client.patch("/api/extensions/notes", json={"pinned": True}).json() == {"ok": True}
    assert config.load_config()["extensions"]["pinned"] == ["notes"]
    assert {e["id"]: e for e in client.get("/api/extensions").json()}["notes"]["pinned"] is True
    assert client.patch("/api/extensions/w", json={"pinned": True}).json()["error"] == "not_a_page"
    assert client.patch("/api/extensions/nope", json={"pinned": True}).status_code == 404
    assert client.patch("/api/extensions/notes", json={"pinned": False}).json() == {"ok": True}
    assert config.load_config()["extensions"]["pinned"] == []


def test_html_widget(client, org):
    d = org.ws / "extensions" / "snake"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"type": "widget", "name": "Snake", "height": 5000}))
    (d / "widget.html").write_text("<canvas id=c></canvas><script>maxxing.resize(300)</script>")
    e = {x["id"]: x for x in client.post("/api/extensions/reload").json()}["snake"]
    assert e["error"] is None and e["has_html"] and e["height"] == 800 and not e["has_api"]
    w = {x["id"]: x for x in client.get("/api/dashboard").json()["widgets"]}["snake"]
    assert w["error"] is None and w["card"]["html"] == "/ext/snake/widget.html" and w["card"]["blocks"] == []
    # `updated` is the file's mtime (the UI reloads the frame only when it changes), now when forced
    assert w["card"]["updated"] == (d / "widget.html").stat().st_mtime
    assert next(x for x in client.get("/api/dashboard").json()["widgets"] if x["id"] == "snake")["card"]["updated"] == w["card"]["updated"]
    assert client.get("/api/dashboard/widgets/snake?force=1").json()["card"]["updated"] > w["card"]["updated"]
    r = client.get("/ext/snake/widget.html")
    assert r.status_code == 200 and "<canvas" in r.text
    assert r.headers["content-type"].startswith("text/plain")        # never runs with the app's origin
    f = client.get("/ext/snake/widget-frame")                     # the frame: bridge + widget, its own sandbox
    assert f.status_code == 200 and f.headers["content-type"].startswith("text/html")
    assert f.text.index("window.maxxing=") < f.text.index("<canvas")
    assert f.headers["content-security-policy"].startswith("sandbox allow-scripts")
    # the UI kit is inlined before the widget, scoped to <html data-mx-kit>: an attribute, never a class, so a widget's
    # own <html class="..."> is kept (the parser ignores attributes of a 2nd <html> tag that the bridge already set)
    bridge = f.text[:f.text.index("</script>")]
    assert "setAttribute('data-mx-kit'" in bridge and "classList" not in bridge and "className" not in bridge
    assert "[data-mx-kit]" in f.text and ".mx-kit" not in f.text and f.text.index(".ui-card") < f.text.index("<canvas")
    k = client.get("/ext/ui-kit.css")
    assert k.status_code == 200 and k.headers["content-type"].startswith("text/css") and ".ui-btn" in k.text
    client.patch("/api/extensions/snake", json={"enabled": False})
    assert client.get("/ext/snake/widget.html").status_code == 404
    assert client.get("/ext/snake/widget-frame").status_code == 404
    # a widget with neither card nor html is an error
    (org.ws / "extensions" / "empty").mkdir()
    (org.ws / "extensions" / "empty" / "manifest.json").write_text('{"type": "widget"}')
    assert "widget.html" in {x["id"]: x for x in client.post("/api/extensions/reload").json()}["empty"]["error"]


def test_html_widget_needs_sign_in(org):
    from fastapi.testclient import TestClient
    from maxxing.app import create_app
    with TestClient(create_app()) as anon:
        assert anon.get("/ext/snake/widget.html").status_code == 401


def test_bad_import_never_blocks_startup(client, org, monkeypatch):
    """An api.py that calls sys.exit() or blocks while loading only marks its own extension (C1)."""
    monkeypatch.setattr(extensions, "IMPORT_TIMEOUT_S", 0.5)
    _ext(org, "quits", {"type": "widget"}, "import sys\nsys.exit(3)\n")
    _ext(org, "hangs", {"type": "widget"}, "import threading\nthreading.Event().wait(5)\ndef card(ctx): return {}\n")
    _ext(org, "fine", {"type": "widget"}, "def card(ctx):\n    return {'blocks': []}\n")
    lst = {e["id"]: e for e in client.get("/api/extensions").json()}
    assert "stopped while loading" in lst["quits"]["error"]
    assert "to load" in lst["hangs"]["error"]
    assert lst["fine"]["error"] is None


def test_stuck_extension_never_takes_the_shared_pool(client, org, monkeypatch):
    """handle() that never returns: 504, then 503 at once while it has not returned, so it holds one extension
    thread and the other extensions keep answering; the rest of the API (shared thread pool) too (C2)."""
    import threading
    from maxxing.api import extensions as api_ext
    monkeypatch.setattr(api_ext, "HANDLE_TIMEOUT_S", 0.2)
    release = threading.Event()
    _ext(org, "stuck", {"type": "page"}, "def handle(ctx, method, path, query, body):\n    ctx['wait']()\n    return {}\n",
         "export function mount(){}")
    _ext(org, "fine", {"type": "page"}, "def handle(ctx, method, path, query, body):\n    return {'ok': 1}\n",
         "export function mount(){}")
    real = extensions.make_ctx
    monkeypatch.setattr(extensions, "make_ctx", lambda ext: {**real(ext), "wait": lambda: release.wait(10)})
    try:
        codes = [client.get("/api/ext/stuck/x").status_code for _ in range(extensions.EXT_WORKERS + 2)]
        assert codes == [504] + [503] * (extensions.EXT_WORKERS + 1)
        assert extensions._stuck == 1
        assert client.get("/api/ext/fine/x").json() == {"ok": 1}
        assert client.get("/api/extensions").status_code == 200
        assert client.get("/api/dashboard").status_code == 200
    finally:
        release.set()
    import time
    for _ in range(50):                                # threads free again once the code returns
        if extensions._stuck == 0:
            break
        time.sleep(0.05)
    assert extensions._stuck == 0


def test_concurrent_extension_calls_wait_their_turn():
    """More calls at once than extension threads (the dashboard asks every widget together): they queue, none is
    refused."""
    import asyncio
    import time

    async def many():
        return await asyncio.gather(*(extensions.call(time.sleep, 0.2, timeout=5) for _ in range(extensions.EXT_WORKERS * 2 + 1)),
                                    return_exceptions=True)
    assert asyncio.run(many()) == [None] * (extensions.EXT_WORKERS * 2 + 1)


def test_extension_files_linked_outside_their_folder_are_not_served(client, org, tmp_path):
    secret = tmp_path / "credentials.json"
    secret.write_text('{"token": "SECRET"}')
    d = org.ws / "extensions" / "leak"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"type": "widget", "name": "Leak"}))
    (d / "widget.html").symlink_to(secret)
    p = _ext(org, "leakpage", {"type": "page", "name": "Leak page"})
    (p / "page.js").symlink_to(secret)
    client.post("/api/extensions/reload")
    for url in ("/ext/leak/widget.html", "/ext/leak/widget-frame", "/ext/leakpage/page.js"):
        r = client.get(url)
        assert r.status_code == 404 and "SECRET" not in r.text, url


def test_extension_in_error_serves_neither_page_nor_widget(client, org):
    # api.py that fails to import: the extension is in error, like /api/ext its page and widget are not served
    d = _ext(org, "broken", {"type": "widget", "name": "Broken"}, api="raise RuntimeError('boom')\n")
    (d / "widget.html").write_text("<p>widget</p>")
    p = _ext(org, "brokenpage", {"type": "page", "name": "Broken page"}, api="raise RuntimeError('boom')\n",
             page="console.log('page')")
    exts = {x["id"]: x for x in client.post("/api/extensions/reload").json()}
    assert exts["broken"]["error"] and exts["brokenpage"]["error"]
    for url in ("/ext/broken/widget.html", "/ext/broken/widget-frame", "/ext/brokenpage/page.js"):
        assert client.get(url).status_code == 404, url


def test_ui_kit_is_read_once_and_revalidated_with_an_etag(client, org, monkeypatch):
    from maxxing.api import extensions as ext_api
    k = client.get("/ext/ui-kit.css")
    assert k.status_code == 200 and k.headers.get("etag")
    assert client.get("/ext/ui-kit.css", headers={"If-None-Match": k.headers["etag"]}).status_code == 304
    reads = {"n": 0}
    real = Path.read_text

    def counting(self, *a, **kw):
        if self == ext_api.UI_KIT:
            reads["n"] += 1
        return real(self, *a, **kw)
    monkeypatch.setattr(Path, "read_text", counting)
    d = org.ws / "extensions" / "kitw"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"type": "widget", "name": "Kit"}))
    (d / "widget.html").write_text("<p>w</p>")
    client.post("/api/extensions/reload")
    for _ in range(3):
        assert ".ui-btn" in client.get("/ext/kitw/widget-frame").text
    assert reads["n"] == 0                                      # unchanged file: never read again


def test_ui_kit_tables_scroll_instead_of_overflowing():
    # a 4-column .ui-table overflowed a 360 px page: .ui-table-wrap scrolls, and on phones a bare table scrolls itself
    import re
    from pathlib import Path
    import maxxing
    css = (Path(maxxing.__file__).parent / "assets" / "ui-kit.css").read_text()
    assert re.search(r":where\(\.ui-table-wrap\) \{[^}]*overflow-x: auto", css)
    phone = css[css.index("@media (max-width: 639px)"):]
    phone = phone[:phone.index("\n}")]
    assert re.search(r"\.ui-table\) \{[^}]*display: block;[^}]*overflow-x: auto", phone)


def test_sys_exit_in_extension_code_never_escapes(client, org):
    """handle() / card() calling sys.exit: a 500 / a widget error, never a SystemExit in the server loop."""
    _ext(org, "ex", {"type": "page"}, "import sys\ndef handle(ctx, m, p, q, b):\n    sys.exit(3)\n", page="export function mount(){}")
    assert client.get("/api/ext/ex/x").status_code == 500
    _ext(org, "cx", {"type": "widget"}, "def card(ctx):\n    raise SystemExit(2)\n")
    r = client.get("/api/dashboard/widgets/cx")
    assert r.status_code == 200 and "SystemExit" in r.json()["error"]
