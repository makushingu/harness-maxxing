#!/usr/bin/env python3
"""UI check: a real browser clicks through the built interface (web/dist) served by the mock backend.

    scripts/ui-check.sh                      every journey, computer + phone, English + French (~3 min)
    scripts/ui-check.sh --only pages,login   some journeys (names: --list)
    scripts/ui-check.sh --shots DIR          a screenshot of every failure in DIR

Nothing real is touched: the script starts web/mock/server.mjs on a free port (fake data, no Claude, no state on
disk) and stops it at the end. Exit code 0 = every journey passed, 1 = at least one failed (each failure is printed
with the page, the size and what was expected), 2 = the check could not run (no browser, no build).

What every page must satisfy (`healthy`): no JavaScript error, no API answer 5xx, not the "page not found" screen,
something drawn in <main>, and on a phone nothing wider than the screen.
Journeys use roles, addresses and the mock's own data rather than interface wording where they can; the ones that
need a label run in English.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent
DESKTOP = {"width": 1280, "height": 900}
PHONE = {"width": 400, "height": 800}
PAGES = ["/", "/sessions", "/jarvis", "/agents", "/tasks", "/team", "/mail", "/infra", "/git", "/files", "/feed",
         "/docs", "/x/radar", "/settings"]
SESSION = "Draft: 5 ways to speed up checkout"          # a session of the mock (scenario "ready")
NOT_FOUND: list[str] = []                                # filled by main()
PASSWORD = "password123"                                 # the mock's password (scenario "login")


LOCALES = {"en": "en-US", "fr": "fr-FR", "es": "es-ES", "de": "de-DE", "zh": "zh-CN", "ja": "ja-JP"}
TRANSLATED = [f.stem for f in sorted((WEB / "src/i18n").glob("??.ts")) if f.stem not in ("en", "fr")]


def text_of(lang: str, key: str) -> str | None:
    """One text of a dictionary (src/i18n/<lang>.ts)."""
    m = re.search(r"""['"]%s['"]: (['"])(.+?)\1,""" % re.escape(key), (WEB / f"src/i18n/{lang}.ts").read_text())
    return m.group(2) if m else None


def settings_sections() -> list[str]:
    """The ids of pages/settings/sections.ts that are pages (the groups of the same file are not)."""
    src = (WEB / "src/pages/settings/sections.ts").read_text()
    return re.findall(r"\{ id: '([a-z-]+)', group:", src)


def not_found_titles() -> list[str]:
    """The title of the not-found screen in every language of the interface (src/i18n/*.ts, key error.notFound)."""
    out = []
    for f in (WEB / "src/i18n").glob("??.ts"):
        m = re.search(r"""['"]error\.notFound['"]: (['"])(.+?)\1,""", f.read_text())
        if m:
            out.append(m.group(2))
    return out


def chrome() -> str | None:
    """The Chromium to drive: MAXXING_E2E_CHROME, the one Harness installed, else Playwright's own cache."""
    if os.environ.get("MAXXING_E2E_CHROME"):
        return os.environ["MAXXING_E2E_CHROME"]
    state = Path(os.environ.get("MAXXING_STATE") or "/var/lib/claude-maxxing")
    cache = Path.home() / ".cache/ms-playwright"
    for pat in (state.glob("tools/browsers/chromium-*/chrome-linux64/chrome"),
                cache.glob("chromium-*/chrome-linux64/chrome"),
                cache.glob("chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")):
        found = sorted(pat)
        if found:
            return str(found[-1])
    return None                                           # Playwright's default (raises when it has none)


class Mock:
    """web/mock/server.mjs on a free port, every optional page on."""

    def __init__(self) -> None:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        env = {**os.environ, "MOCK_PORT": str(self.port), "MOCK_FEATURES": "all", "MOCK_METERS": "off"}
        if os.environ.get("MAXXING_E2E_DIST"):
            env["MOCK_DIST"] = os.environ["MAXXING_E2E_DIST"]
        self.proc = subprocess.Popen(["node", str(WEB / "mock/server.mjs")], env=env, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                urllib.request.urlopen(self.base + "/api/auth/state", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        self.stop()
        raise RuntimeError("the mock server did not start (node web/mock/server.mjs)")

    def call(self, method: str, path: str, body: dict | None = None):
        data = None if method == "GET" else json.dumps(body or {}).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "X-Maxxing": "1"})
        raw = urllib.request.urlopen(req, timeout=5).read()
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def scenario(self, name: str, lang: str = "en") -> None:
        """Back to a fresh state of `name` (setup | login | onboarding | ready), the start guide closed."""
        self.call("POST", "/__mock/scenario", {"name": name})
        if name == "ready":
            self.call("PUT", "/api/settings", {"language": lang})
            self.call("POST", "/api/guide/reset")

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class Failure(Exception):
    pass


class Run:
    def __init__(self, browser, mock: Mock, shots: Path | None) -> None:
        self.browser, self.mock, self.shots = browser, mock, shots
        self.least = 20
        self.errors: list[str] = []                       # JavaScript errors and API 5xx of the page in use

    def page(self, size: dict = DESKTOP, lang: str = "en"):
        self.least = 8 if lang in ("zh", "ja") else 20      # characters a drawn page has at least: fewer in Chinese or Japanese
        phone = size is PHONE
        ctx = self.browser.new_context(viewport=size, is_mobile=phone, has_touch=phone,
                                       locale=LOCALES.get(lang, "en-US"))
        pg = ctx.new_page()
        pg.set_default_timeout(15000)
        self.errors = []
        pg.on("pageerror", lambda e: self.errors.append(f"JavaScript error: {str(e)[:200]}"))
        pg.on("response", lambda r: r.status >= 500 and "/api/" in r.url
              and self.errors.append(f"{r.status} on {r.url.split('/api/', 1)[1][:80]}"))
        return pg

    def go(self, pg, path: str) -> None:
        pg.goto(self.mock.base + path, wait_until="load")
        self.settle(pg)

    def settle(self, pg) -> None:
        """The page is drawn: <main> exists and its loading skeletons are gone (or 4 s passed)."""
        try:
            pg.wait_for_selector("main", state="attached")
        except Exception:  # noqa: BLE001
            said = " ".join(pg.locator("body").inner_text().split())[:160]
            raise Failure(f"the page did not draw (the screen says: {said!r})") from None
        try:
            pg.wait_for_function("() => { const m = document.querySelector('main');"
                                 " return m && m.innerText.trim().length > 20"
                                 " && !m.querySelector('[data-slot=skeleton], .animate-pulse') }", timeout=4000)
        except Exception:  # noqa: BLE001 - judged by healthy()
            pass
        pg.wait_for_timeout(250)

    def healthy(self, pg, phone: bool = False) -> None:
        if self.errors:
            raise Failure("; ".join(dict.fromkeys(self.errors)))
        state = pg.evaluate("""titles => { const m = document.querySelector('main'); return {
            text: m ? m.innerText.trim().length : -1,
            lost: titles.some(t => document.title.includes(t)),
            wide: document.scrollingElement.scrollWidth - window.innerWidth } }""", NOT_FOUND)
        if state["text"] < self.least:
            raise Failure("nothing drawn in the page" if state["text"] >= 0 else "no <main> in the page")
        if state["lost"]:
            raise Failure("the page-not-found screen is shown")
        if phone and state["wide"] > 2:
            raise Failure(f"the page is {state['wide']} px wider than the phone screen")


# ---- journeys -------------------------------------------------------------------------------------------------------
def j_guide(r: Run) -> None:
    """A new installation offers the start guide once; closed, it stays closed."""
    r.mock.call("POST", "/__mock/scenario", {"name": "ready"})
    pg = r.page()
    r.go(pg, "/")
    dialog = pg.get_by_role("dialog")
    dialog.wait_for()
    dialog.get_by_role("button").nth(2).click()           # "Close, I don't need it"
    dialog.wait_for(state="hidden")
    r.go(pg, "/")
    pg.wait_for_timeout(800)
    if pg.get_by_role("dialog").count():
        raise Failure("the start guide came back after it was closed")
    r.healthy(pg)


def _pages(r: Run, size: dict, lang: str) -> None:
    r.mock.scenario("ready", lang)
    pg, bad = r.page(size, lang), []
    for path in PAGES + [f"/settings/{s}" for s in settings_sections()]:
        r.errors = []
        try:
            r.go(pg, path)
            r.healthy(pg, phone=size is PHONE)
        except Exception as e:  # noqa: BLE001 - every page is tried, the list is the result
            bad.append(f"{path}: {str(e).splitlines()[0][:220]}")
            shot(r, pg, f"pages-{lang}-{size['width']}-{path.strip('/').replace('/', '_') or 'home'}")
    if lang != "en":                                      # the language really changed
        r.go(pg, "/files" if size is DESKTOP else "/settings")
        word = text_of(lang, "nav.settings")
        if not word or word not in pg.content():
            bad.append(f"the interface is not in {lang} after the language was set to {lang}")
    if bad:
        raise Failure(f"{len(bad)} page(s) in {lang}:\n      " + "\n      ".join(bad))


def j_pages(r: Run) -> None:
    """Every page and every Settings section opens, on a computer, in English."""
    _pages(r, DESKTOP, "en")


def j_pages_phone(r: Run) -> None:
    """The same on a phone: nothing wider than the screen."""
    _pages(r, PHONE, "en")


def j_pages_fr(r: Run) -> None:
    """The same in French, on a computer."""
    _pages(r, DESKTOP, "fr")


def j_pages_fr_phone(r: Run) -> None:
    """The same in French, on a phone."""
    _pages(r, PHONE, "fr")


def j_pages_translated(r: Run) -> None:
    """The same in every other language of the interface (es, de, zh, ja...), on a computer."""
    for lang in TRANSLATED:
        _pages(r, DESKTOP, lang)


def j_pages_translated_phone(r: Run) -> None:
    """The same in every other language, on a phone: a longer word must not push the page wider."""
    for lang in TRANSLATED:
        _pages(r, PHONE, lang)


def j_not_found(r: Run) -> None:
    """An unknown address shows the not-found screen with a way back."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/no-such-page")
    if not any(t in pg.title() for t in NOT_FOUND):
        raise Failure(f"an unknown address does not show the not-found screen (title: {pg.title()!r})")
    pg.locator("main button").first.click()
    pg.wait_for_function("() => location.pathname === '/'")
    r.settle(pg)
    r.healthy(pg)


def j_setup(r: Run) -> None:
    """A server without a password sends every address to the setup form."""
    r.mock.scenario("setup")
    pg = r.page()
    r.go(pg, "/sessions")
    if "/setup" not in pg.url or pg.locator("input[type=password]").count() < 2:
        raise Failure(f"expected the setup form with two password fields, got {pg.url}")
    r.healthy(pg)


def j_login(r: Run) -> None:
    """Signed out: any page asks for the password, a wrong one is refused, the right one opens the page asked."""
    r.mock.scenario("login")
    pg = r.page()
    r.go(pg, "/sessions")
    if "/login" not in pg.url:
        raise Failure(f"a signed-out visitor reached {pg.url}")
    field = pg.locator("input[type=password]")
    field.fill("not-the-password")
    field.press("Enter")
    pg.wait_for_timeout(1200)
    if "/login" not in pg.url:
        raise Failure("a wrong password signed in")
    if not pg.locator("[role=alert], [aria-invalid=true]").count():
        raise Failure("a wrong password shows no error")
    field.fill(PASSWORD)
    field.press("Enter")
    pg.wait_for_url("**/sessions**")
    r.settle(pg)
    r.healthy(pg)


def j_onboarding(r: Run) -> None:
    """The first-run steps: the first one is shown and Continue moves to the second."""
    r.mock.scenario("onboarding")
    pg = r.page()
    r.go(pg, "/")
    if "/welcome" not in pg.url:
        raise Failure(f"expected the first-run steps, got {pg.url}")
    first = pg.locator("main h1").inner_text()
    pg.locator("main").get_by_role("button", name="Continue").click()
    pg.wait_for_function("t => document.querySelector('main h1')?.innerText !== t", arg=first)
    r.healthy(pg)


def _open_session(r: Run, pg) -> None:
    r.go(pg, "/sessions")
    pg.get_by_role("button", name="blog", exact=False).first.click()
    pg.get_by_text(SESSION).first.click()
    pg.wait_for_url("**session=**")
    pg.locator("main textarea").first.wait_for()


def j_session(r: Run) -> None:
    """Open a session from the list, send a message: it appears in the conversation and the box is emptied."""
    r.mock.scenario("ready")
    pg = r.page()
    _open_session(r, pg)
    box, text = pg.locator("main textarea").first, "ui-check: hello from the browser"
    box.fill(text)
    box.press("Enter")
    pg.locator("main").get_by_text(text).first.wait_for()
    if box.input_value():
        raise Failure("the message box still holds the message after it was sent")
    r.healthy(pg)


def j_session_reload(r: Run) -> None:
    """A draft typed in a session survives a reload of the page."""
    r.mock.scenario("ready")
    pg = r.page()
    _open_session(r, pg)
    pg.locator("main textarea").first.fill("ui-check: a draft kept")
    pg.wait_for_timeout(900)
    pg.reload()
    r.settle(pg)
    box = pg.locator("main textarea").first
    box.wait_for()
    pg.wait_for_timeout(600)
    if box.input_value() != "ui-check: a draft kept":
        raise Failure(f"the draft was lost by a reload (box: {box.input_value()!r})")


def j_new_session(r: Run) -> None:
    """New session opens a message box ready to type in."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/sessions")
    pg.locator("main").get_by_role("button", name="New session").first.click()
    pg.locator("textarea").first.wait_for()
    r.healthy(pg)


def j_session_phone(r: Run) -> None:
    """On a phone: the menu lists the sessions, one tapped opens with its message box and the menu closes."""
    r.mock.scenario("ready")
    pg = r.page(PHONE)
    r.go(pg, "/sessions")
    pg.get_by_role("button", name="Menu").first.click()
    drawer = pg.get_by_role("dialog")
    drawer.wait_for()
    topic = drawer.get_by_role("treeitem").filter(has_text="blog").last
    topic.wait_for()
    pg.wait_for_timeout(400)                              # the list settles (a topic unfolds by itself when it is open)
    if topic.get_attribute("aria-expanded") != "true":
        topic.locator("svg").first.click()                # its arrow unfolds it
    drawer.get_by_text(SESSION).first.click()
    drawer.wait_for(state="hidden")
    pg.locator("main textarea").first.wait_for()
    r.healthy(pg, phone=True)


def j_palette(r: Run) -> None:
    """Ctrl+K opens the command palette; a page typed and Enter goes there."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/")
    pg.keyboard.press("Control+k")
    box = pg.get_by_role("combobox")
    box.wait_for()
    box.fill("Appearance")
    pg.wait_for_timeout(500)
    pg.keyboard.press("Enter")
    pg.wait_for_url("**/settings/appearance**")
    r.settle(pg)
    r.healthy(pg)


def j_theme(r: Run) -> None:
    """The mode button of the sidebar switches between dark and light, and the choice survives a reload."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/")
    dark = "() => document.documentElement.classList.contains('dark')"
    before = pg.evaluate(dark)
    button = pg.get_by_role("button", name=re.compile(r"^Mode"))
    for _ in range(3):                                    # the button walks through dark / light / system
        button.click()
        pg.wait_for_timeout(300)
        if pg.evaluate(dark) != before:
            break
    else:
        raise Failure("the mode button never changed dark / light")
    pg.reload()
    r.settle(pg)
    if pg.evaluate(dark) == before:
        raise Failure("the dark / light choice was lost by a reload")


def j_setting_saved(r: Run) -> None:
    """A switch of Settings -> Features is saved: it is still changed after a reload."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/settings/features")
    switch = pg.locator("main [role=switch]:not([disabled])").first
    switch.wait_for()
    before = switch.get_attribute("aria-checked")
    switch.click()
    pg.wait_for_function("([b]) => document.querySelector('main [role=switch]:not([disabled])')"
                         "?.getAttribute('aria-checked') !== b", arg=[before])
    pg.wait_for_timeout(500)
    r.go(pg, "/settings/features")
    after = pg.locator("main [role=switch]:not([disabled])").first.get_attribute("aria-checked")
    if after == before:
        raise Failure("the switch went back to its old value after a reload")
    r.healthy(pg)


def j_settings_nav(r: Run) -> None:
    """Settings: a section clicked in the list opens it."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/settings")
    pg.locator('main nav a[href="/settings/security"]:visible').first.click()
    pg.wait_for_url("**/settings/security")
    r.settle(pg)
    if not pg.locator("main input[type=password]").count():
        raise Failure("Settings -> Security shows no password field")
    r.healthy(pg)


def j_files(r: Run) -> None:
    """Files: a file clicked in the list is shown in the viewer, with its content."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/files")
    empty = pg.locator("main h3").count()                 # the "select a file" screen
    pg.get_by_role("button", name=re.compile(r"^CLAUDE\.md")).first.click()
    pg.wait_for_function("n => document.querySelectorAll('main h3').length < n || /CLAUDE\\.md/.test(location.href)",
                         arg=max(empty, 1))
    r.settle(pg)
    if "CLAUDE.md" not in pg.locator("main").inner_text():
        raise Failure("the viewer does not show the file that was clicked")
    r.healthy(pg)


def j_team(r: Run) -> None:
    """Team: a message typed and sent appears in the conversation."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/team")
    box, text = pg.locator("main [role=textbox], main textarea").last, "ui-check: hello team"
    box.click()
    pg.keyboard.type(text)
    pg.keyboard.press("Enter")
    pg.locator("main").get_by_text(text).first.wait_for()
    r.healthy(pg)


def j_nav(r: Run) -> None:
    """Every link of the sidebar leads to its page without a full reload losing the shell."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/")
    hrefs = pg.eval_on_selector_all('nav a[href^="/"]', "els => [...new Set(els.map(a => a.getAttribute('href')))]")
    if len(hrefs) < 6:
        raise Failure(f"the sidebar has only {len(hrefs)} links")
    for href in hrefs:
        r.errors = []
        pg.locator(f'nav a[href="{href}"]').first.click()
        pg.wait_for_function("h => location.pathname === h || location.pathname.startsWith(h + '/')", arg=href)
        r.settle(pg)
        try:
            r.healthy(pg)
        except Failure as e:
            raise Failure(f"{href}: {e}") from None
        if not pg.locator(f'nav a[href="{href}"]').count():
            raise Failure(f"the sidebar disappeared on {href}")


def j_sign_out(r: Run) -> None:
    """Sign out (Settings -> Security) goes back to the sign-in form, and the pages are closed again."""
    r.mock.scenario("login")
    pg = r.page()
    r.go(pg, "/")
    pg.locator("input[type=password]").fill(PASSWORD)
    pg.keyboard.press("Enter")
    pg.wait_for_function("() => !location.pathname.startsWith('/login')")
    r.go(pg, "/settings/security")
    pg.locator("main").get_by_role("button", name="Sign out", exact=True).click()
    pg.wait_for_url("**/login**")
    r.go(pg, "/sessions")
    if "/login" not in pg.url:
        raise Failure("the pages are still open after a sign-out")


def j_usage_agents(r: Run) -> None:
    """Settings -> Usage counts each agent, and the table can be downloaded as it is shown."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/settings/usage")
    pg.locator("main").get_by_text("Agent", exact=True).first.click()
    table = pg.locator('[data-testid="usage-table"]')
    table.get_by_text("Blog Writer").first.wait_for()
    href = pg.locator('[data-testid="usage-export-csv"]').get_attribute("href") or ""
    if "group=agents" not in href or "format=csv" not in href:
        raise Failure(f"the CSV link does not download the agents shown: {href!r}")
    pg.locator('[data-testid="alert-errors"]').click()            # the alerts: a switch is saved and stays off
    pg.wait_for_function("""() => document.querySelector('[data-testid="alert-errors"]')?.getAttribute('aria-checked') === 'false'""")
    r.go(pg, "/settings/usage")
    if pg.locator('[data-testid="alert-errors"]').get_attribute("aria-checked") != "false":
        raise Failure("the alert switched off is on again after a reload")
    r.healthy(pg)


def j_logs_search(r: Run) -> None:
    """Settings -> System: a search in the logs says how many lines match; /metrics shows its token once."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/settings/system")
    pg.locator('main input[maxlength="200"]').fill("cron")
    pg.wait_for_function("""() => /\\d/.test(document.querySelector('[data-testid="logs-count"]')?.innerText || '')""")
    pg.locator('[data-testid="metrics-switch"]').click()
    pg.locator('[data-testid="metrics-url"]').wait_for()
    if "/metrics" not in pg.locator('[data-testid="metrics-url"]').inner_text():
        raise Failure("the metrics address is not shown once the switch is on")
    r.healthy(pg)


def j_community(r: Run) -> None:
    """Settings -> Community: three tabs, a listing shows what it would do, and installs only once that was read."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/settings/community")
    pg.locator('[data-testid="community-disclaimer"]').wait_for()   # who is responsible is said before any install
    box = pg.locator('[data-testid="community-list"]')
    box.get_by_text("Shopify stats").wait_for()
    if box.get_by_text("Neon sunset").count():
        raise Failure("a theme is listed under Extensions")
    box.get_by_role("button").first.click()
    rep = pg.locator('[data-testid="community-report"]')
    rep.get_by_text("starts a process on the server").wait_for()
    go = pg.locator('[data-testid="community-install"]')
    if go.is_enabled():
        raise Failure("a package with points in red can be installed before they are read")
    rep.locator('input[type="checkbox"]').check()
    go.click()
    rep.wait_for(state="detached")
    box.get_by_role("button").first.wait_for(state="detached")     # installed: no button any more
    pg.get_by_role("radio").nth(1).click()
    box.get_by_text("Neon sunset").wait_for()
    r.healthy(pg)


def j_turn_details(r: Run) -> None:
    """The line under an answer opens "Turn details": the steps of the turn, in English, with its failed tool."""
    r.mock.scenario("ready")
    pg = r.page()
    got = r.mock.call("GET", "/api/sessions")
    idle = next(x for x in (got["sessions"] if isinstance(got, dict) else got) if x.get("state") == "idle" and x.get("turns"))
    r.go(pg, f"/sessions?path={idle['path']}&session={idle['id']}")
    menu = pg.locator('[data-testid="result-line-menu"]').last
    menu.scroll_into_view_if_needed()
    menu.click()
    pg.locator('[data-testid="turn-details-open"]').click()
    box = pg.locator('[data-testid="turn-details"]')
    box.locator('[data-testid="turn-steps"] li').first.wait_for()
    text = box.inner_text()
    if box.locator('[data-testid="turn-steps"] li').count() < 3 or "failed" not in text:
        raise Failure(f"the steps of the turn are not shown: {' '.join(text.split())[:160]!r}")
    if "trace." in text:
        raise Failure("the window shows text keys instead of its texts")
    r.healthy(pg)


def j_push_feed(r: Run) -> None:
    """Settings -> Notifications -> Mobile notifications: what of the feed rings on the phones is saved."""
    r.mock.scenario("ready")
    pg = r.page()
    r.go(pg, "/settings/alerts")
    box = pg.get_by_role("combobox", name="From the Notifications feed")
    box.wait_for()
    box.click()
    pg.get_by_role("option", name="Requests only").click()
    pg.wait_for_timeout(500)
    r.go(pg, "/settings/alerts")
    box = pg.get_by_role("combobox", name="From the Notifications feed")
    box.wait_for()
    if "Requests only" not in box.inner_text():
        raise Failure("the choice went back to its old value after a reload")
    r.healthy(pg)


def j_share(r: Run) -> None:
    """Another app shares a text and a link to the installed app (phone): a new session opens with them typed in."""
    r.mock.scenario("ready")
    pg = r.page(PHONE)
    pg.add_init_script("Object.defineProperty(navigator, 'standalone', { get: () => true })")   # the installed app
    r.go(pg, "/sessions")
    pg.evaluate("navigator.serviceWorker.ready")
    r.go(pg, "/sessions")                       # the service worker now answers the requests of the page
    pg.evaluate("""() => { const f = document.createElement('form'); f.method = 'post'; f.action = '/share'
        f.enctype = 'multipart/form-data'
        f.innerHTML = '<input name="text" value="Look at this before the call"><input name="url" value="https://example.com/pricing">'
        document.body.appendChild(f); f.submit() }""")
    pg.wait_for_url("**/sessions?*new=1*")
    r.settle(pg)
    box = pg.locator("main textarea").first
    box.wait_for()
    pg.wait_for_function("() => (document.querySelector('main textarea')?.value || '').includes('example.com/pricing')")
    if "Look at this before the call" not in box.input_value():
        raise Failure("the shared text is not in the message box")
    r.healthy(pg, phone=True)


JOURNEYS = {
    "guide": j_guide, "pages": j_pages, "pages-phone": j_pages_phone, "pages-fr": j_pages_fr,
    "pages-fr-phone": j_pages_fr_phone, "pages-translated": j_pages_translated,
    "pages-translated-phone": j_pages_translated_phone, "not-found": j_not_found, "setup": j_setup, "login": j_login,
    "onboarding": j_onboarding, "session": j_session, "session-reload": j_session_reload,
    "new-session": j_new_session, "session-phone": j_session_phone, "palette": j_palette, "theme": j_theme,
    "setting-saved": j_setting_saved, "settings-nav": j_settings_nav, "files": j_files, "team": j_team, "nav": j_nav,
    "usage-agents": j_usage_agents, "logs-search": j_logs_search, "turn-details": j_turn_details, "community": j_community,
    "push-feed": j_push_feed, "share": j_share, "sign-out": j_sign_out,
}


def shot(r: Run, pg, name: str) -> None:
    if r.shots:
        try:
            r.shots.mkdir(parents=True, exist_ok=True)
            pg.screenshot(path=str(r.shots / f"{name}.png"))
        except Exception:  # noqa: BLE001 - a screenshot never hides the failure
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Click through the built interface on the mock backend.")
    ap.add_argument("--only", help="journeys to run, comma separated")
    ap.add_argument("--list", action="store_true", help="list the journeys")
    ap.add_argument("--shots", type=Path, help="folder for a screenshot of each failure")
    a = ap.parse_args()
    if a.list:
        for name, fn in JOURNEYS.items():
            print(f"{name:16} {(fn.__doc__ or '').strip()}")
        return 0
    names = [n.strip() for n in a.only.split(",")] if a.only else list(JOURNEYS)
    unknown = [n for n in names if n not in JOURNEYS]
    if unknown:
        print(f"unknown journey: {', '.join(unknown)} (see --list)", file=sys.stderr)
        return 2
    dist = Path(os.environ.get("MAXXING_E2E_DIST") or WEB / "dist")
    if not (dist / "index.html").exists():
        print(f"no built interface in {dist} (npm run build)", file=sys.stderr)
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is missing: run scripts/ui-check.sh, which brings it", file=sys.stderr)
        return 2
    NOT_FOUND.extend(not_found_titles())
    if not NOT_FOUND:
        print("the title of the not-found screen was not found in src/i18n (key error.notFound)", file=sys.stderr)
        return 2
    mock = Mock()
    failed = []
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(executable_path=chrome(), args=["--no-sandbox"])
            except Exception as e:  # noqa: BLE001
                print(f"no browser to drive ({str(e).splitlines()[0][:160]}): set MAXXING_E2E_CHROME", file=sys.stderr)
                return 2
            r, t0 = Run(browser, mock, a.shots), time.time()
            for name in names:
                t, pages_before = time.time(), len(browser.contexts)
                try:
                    JOURNEYS[name](r)
                    print(f"  ok    {name:16} {time.time() - t:5.1f} s", flush=True)
                except Exception as e:  # noqa: BLE001 - a journey that breaks is a result, the others still run
                    msg = str(e) if isinstance(e, Failure) else f"{type(e).__name__}: {str(e).splitlines()[0][:260]}"
                    if r.errors and not isinstance(e, Failure):  # what the page itself reported says more
                        msg += "\n      " + "; ".join(dict.fromkeys(r.errors))
                    failed.append(name)
                    print(f"  FAIL  {name:16} {(JOURNEYS[name].__doc__ or '').strip()}\n      {msg}", flush=True)
                    for ctx in browser.contexts[pages_before:]:
                        for pg in ctx.pages:
                            shot(r, pg, name)
                for ctx in browser.contexts:
                    ctx.close()
            browser.close()
            print(f"{len(names) - len(failed)}/{len(names)} journeys passed in {time.time() - t0:.0f} s"
                  + (f" - failed: {', '.join(failed)}" if failed else ""))
    finally:
        mock.stop()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
