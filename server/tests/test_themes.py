"""Themes: the contract with the interface (every variable exists in globals.css, fonts match the catalog), the
fallback to the built-in values, values that could load or run something, contrast, install / remove, the API."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from maxxing import cli, themes

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def _theme(root: Path, tid: str, body: dict, files: dict[str, bytes] | None = None) -> Path:
    d = root / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "theme.json").write_text(json.dumps(body), encoding="utf-8")
    for n, b in (files or {}).items():
        (d / n).write_bytes(b)
    return d


def test_every_token_is_a_variable_of_the_interface():
    css = (WEB / "styles" / "globals.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"(?m)^\s*--([a-z0-9-]+)\s*:", css))
    missing = [t for t in themes.TOKENS if t not in defined]
    assert not missing, f"theme variables not in globals.css (never remove one: add an alias): {missing}"
    assert not set(themes.ALIASES) & set(themes.TOKENS)


def test_fonts_and_accents_match_the_catalog():
    fonts = (WEB / "lib" / "fonts.ts").read_text(encoding="utf-8")
    def keys(block: str) -> list[str]:
        body = fonts.split(f"export const {block} = {{", 1)[1].split("\n}", 1)[0]
        return re.findall(r"(?m)^  ([a-z0-9]+): \{", body)
    assert list(themes.SANS_FONTS) == keys("SANS_FONTS")
    assert list(themes.MONO_FONTS) == keys("MONO_FONTS")
    ui = (WEB / "stores" / "ui.ts").read_text(encoding="utf-8")
    assert re.search(r"ACCENTS = \[([^\]]+)\]", ui).group(1).replace("'", "").replace(" ", "").split(",") == list(themes.ACCENTS)


def test_the_docs_list_every_token():
    doc = (Path(__file__).resolve().parents[2] / "docs" / "user" / "39-themes.md").read_text(encoding="utf-8")
    assert [t for t in themes.TOKENS if f"`{t}`" not in doc] == []


def test_what_is_missing_or_wrong_falls_back(tmp_path):
    d = _theme(tmp_path, "nord", {
        "schema": 1, "name": "Nord", "base": "glass",
        "dark": {"background": "#2e3440", "foreground": "#eceff4", "radius": "6px", "nope": "#fff",
                 "border": "url(https://evil.example/x)", "primary": "red; } body { display: none",
                 "shadow-pop": "0 0 1px var(--x)", "glass-blur": "900px", "sf-h": 220},
        "options": {"font": "plex", "accent": "pink"}, "extra": 1,
    })
    t, warn, err = themes.load(d)
    assert err is None and t["id"] == "nord" and t["modes"] == ["dark"]
    assert t["dark"] == {"background": "#2e3440", "foreground": "#eceff4", "radius": "6px", "sf-h": "220"}
    assert t["light"] == {} and t["options"] == {"font": "plex"}
    assert t["own_surfaces"] and not t["own_accent"]
    for bit in ("dark.nope", "dark.border", "dark.primary", "dark.shadow-pop", "dark.glass-blur", "options.accent", "extra"):
        assert any(w.startswith(bit) for w in warn), bit


def test_unreadable_text_goes_back_to_the_built_in_values(tmp_path):
    d = _theme(tmp_path, "grey", {"name": "Grey", "light": {"background": "#f4f4f4", "foreground": "#f0f0f0",
                                                            "muted-foreground": "#777"},
                                  "dark": {"l-content": 0.95}})
    t, warn, _ = themes.load(d)
    assert "foreground" not in t["light"] and "background" not in t["light"]
    assert t["light"]["muted-foreground"] == "#777"
    assert "l-content" not in t["dark"]                    # the built-in white text on a near white surface
    assert sum("reads badly" in w for w in warn) >= 2


def test_colors_are_parsed_for_the_contrast():
    assert themes.contrast("#000", "#fff") > 20
    assert round(themes.contrast("oklch(1 0 0)", "rgb(0 0 0)"), 0) == 21
    assert themes.contrast("hsl(0 0% 100%)", "#000000") > 20
    assert themes.parse_color("oklch(0.6 0.2 30 / 50%)")[3] == 0.5
    assert themes.parse_color("var(--x)") is None


def test_bad_themes_are_refused(tmp_path):
    assert themes.load(_theme(tmp_path, "aa", {"name": "x", "schema": 0}))[2]
    assert themes.load(_theme(tmp_path, "bb", {"schema": 1}))[2]                       # no name
    assert themes.load(_theme(tmp_path, "solid", {"name": "Mine"}))[2]               # a built-in id
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "theme.json").write_text("{nope", encoding="utf-8")
    assert "JSON" in themes.load(tmp_path / "cc")[2]
    t, warn, err = themes.load(_theme(tmp_path, "dd", {"name": "Future", "schema": 2}))
    assert t and not err and any("newer" in w for w in warn)


def test_install_list_files_and_remove(mx, client, tmp_path, capsys):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    src = _theme(tmp_path / "src", "dune", {"name": {"en": "Dune", "fr": "Dune"}, "base": "glass",
                                            "wallpaper": "wall.png", "light": {"primary": "#b5651d"}},
                 {"wall.png": png, "notes.txt": b"not copied", "run.sh": b"#!/bin/sh"})
    assert cli.main(["themes", "install", str(src)]) == 0
    dest = mx["ws"] / "themes" / "dune"
    assert sorted(p.name for p in dest.iterdir()) == ["theme.json", "wall.png"]
    assert cli.main(["themes", "install", str(src)]) == 1                         # already there
    assert cli.main(["themes", "install", str(src), "--force"]) == 0
    _theme(mx["ws"] / "themes", "broken", {"schema": 1})
    data = client.get("/api/themes").json()
    assert [t["id"] for t in data["themes"]] == ["dune"] and data["errors"][0]["id"] == "broken"
    t = data["themes"][0]
    assert t["own_accent"] and t["wallpaper"] == {"light": "/api/themes/dune/file/wall.png",
                                                  "dark": "/api/themes/dune/file/wall.png"}
    r = client.get(t["wallpaper"]["light"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == png
    assert client.get("/api/themes/dune/file/theme.json").status_code == 404
    assert client.get("/api/themes/dune/file/..%2F..%2Fconfig.json").status_code == 404
    capsys.readouterr()
    assert cli.main(["themes", "list"]) == 0 and "NOT USABLE" in capsys.readouterr().out
    assert cli.main(["themes", "remove", "dune"]) == 0 and not dest.exists()
    assert cli.main(["themes", "remove", "dune"]) == 1


def test_solid_wallpaper_is_ignored(tmp_path):
    d = _theme(tmp_path, "ww", {"name": "W", "wallpaper": "w.png"}, {"w.png": b"x"})
    t, warn, _ = themes.load(d)
    assert t["wallpaper"] == {"light": None, "dark": None} and any("only a glass" in w for w in warn)


def test_advanced_css_is_checked_and_switched_off_by_an_update(mx, client, tmp_path, monkeypatch, capsys):
    ok = ["& .rounded-xl { letter-spacing: .01em }", "&.dark aside { border-right: 2px solid red }",
          "@media (max-width: 600px) { & h1 { font-size: 1.1rem } }", "/* a comment { */"]
    t, warn, _ = themes.load(_theme(tmp_path, "fine", {"name": "F", "css": ok}))
    assert t["css"] and "/*" not in t["css"] and not warn
    for bad in ["& a { background: url(https://x.example/p.png) }", "@import 'https://x.example/a.css';",
                "& div { position: fixed; inset: 0 }", "} body { color: red", "& a { color: red",
                "& a::after { content: '</style>' }", "@font-face { font-family: x }", "& a { b: \\75rl(x) }",
                "& a { content: 'x }", "& a { color: red } /* open", 5]:
        t, warn, _ = themes.load(_theme(tmp_path, "bad", {"name": "B", "css": bad}))
        assert t["css"] is None and any(w.startswith("css:") for w in warn), bad
    big = "& a { color: red }\n" * 1000
    t, warn, _ = themes.load(_theme(tmp_path, "big", {"name": "B", "css": big}))
    assert t["css"] is None and any("KB" in w for w in warn)

    src = _theme(tmp_path / "src", "neon", {"name": "Neon", "css": ok})
    assert themes.load(src)[0]["css_state"] == "stale"                  # not installed: never checked
    assert cli.main(["themes", "install", str(src)]) == 0
    assert client.get("/api/themes").json()["themes"][0]["css_state"] == "on"
    monkeypatch.setattr(themes, "ui_fingerprint", lambda: "another-build")   # an update changed the app's CSS
    assert client.get("/api/themes").json()["themes"][0]["css_state"] == "stale"
    capsys.readouterr()
    assert cli.main(["themes", "list"]) == 0 and "css OFF" in capsys.readouterr().out
    assert cli.main(["themes", "verify", "neon"]) == 0
    assert client.get("/api/themes").json()["themes"][0]["css_state"] == "on"
    assert cli.main(["themes", "verify", "nope"]) == 1


def test_advanced_css_cannot_leave_its_scope_nor_stay_on_after_an_edit(mx, client, tmp_path):
    for bad in ['a{b:"\r}}:root{--bg:red}x{y:"}', 'a{b:"\f}}:root{--bg:red}x{y:"}', "a{b:c}\x00",
                "--p: fixed; & .x { position: var(--p); inset: 0 }"]:
        t, warn, _ = themes.load(_theme(tmp_path, "esc", {"name": "E", "css": bad}))
        assert t["css"] is None and any(w.startswith("css:") for w in warn), repr(bad)
    t, warn, _ = themes.load(_theme(tmp_path, "sh", {"name": "S", "light": {"shadow-panel": "0 0 1px rgb("}}))
    assert "shadow-panel" not in t["light"]
    src = _theme(tmp_path / "src", "edited", {"name": "Ed", "css": "& aside { opacity: .9 }"})
    assert cli.main(["themes", "install", str(src)]) == 0
    dest = mx["ws"] / "themes" / "edited"
    assert themes.get("edited")["css_state"] == "on"
    _theme(dest.parent, "edited", {"name": "Ed", "css": "& aside { opacity: .5 }"})     # edited in place
    assert themes.get("edited")["css_state"] == "stale"
    assert cli.main(["themes", "verify", "edited"]) == 0 and themes.get("edited")["css_state"] == "on"
    assert cli.main(["themes", "install", str(src), "--force"]) == 0
    assert sorted(p.name for p in dest.parent.iterdir()) == ["edited"]                  # no .tmp / .old left


def test_a_theme_can_bring_its_own_logo(mx, client, tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    src = _theme(tmp_path / "src", "brand", {"name": "Brand", "logo": "logo.png", "logo_dark": "logo-dark.webp",
                                             "light": {"primary": "#b5651d"}},
                 {"logo.png": png, "logo-dark.webp": b"RIFF0000WEBP", "logo.svg": b"<svg onload=alert(1)/>"})
    assert cli.main(["themes", "install", str(src)]) == 0
    t = client.get("/api/themes").json()["themes"][0]
    assert t["logo"] == {"light": "/api/themes/brand/file/logo.png", "dark": "/api/themes/brand/file/logo-dark.webp"}
    assert client.get(t["logo"]["light"]).content == png
    assert not (mx["ws"] / "themes" / "brand" / "logo.svg").exists()
    d = _theme(tmp_path, "svg", {"name": "S", "logo": "logo.svg"}, {"logo.svg": b"<svg/>"})
    t, warn, _ = themes.load(d)
    assert t["logo"] == {"light": None, "dark": None} and any("logo" in w for w in warn)
    d = _theme(tmp_path, "big", {"name": "B", "logo": "l.png"}, {"l.png": b"0" * (themes.MAX_LOGO + 1)})
    assert themes.load(d)[0]["logo"]["light"] is None
    d = _theme(tmp_path, "one", {"name": "O", "logo_dark": "l.png"}, {"l.png": png})
    assert themes.load(d)[0]["logo"] == {"light": "/api/themes/one/file/l.png", "dark": "/api/themes/one/file/l.png"}


def test_a_deeply_nested_theme_json_does_not_break_the_list(mx, client, tmp_path):
    _theme(mx["ws"] / "themes", "fine", {"name": "Fine"})
    deep = mx["ws"] / "themes" / "deep"
    deep.mkdir()
    (deep / "theme.json").write_text('{"name": "D", "light": ' + "[" * 30000 + "]" * 30000 + "}", encoding="utf-8")
    t, _, err = themes.load(deep)
    assert t is None and "JSON" in err
    data = themes.list_themes()
    assert [t["id"] for t in data["themes"]] == ["fine"] and data["errors"][0]["id"] == "deep"
    assert client.get("/api/themes").status_code == 200


def test_an_id_ending_with_a_newline_is_refused(mx, tmp_path):
    t, _, err = themes.load(_theme(tmp_path, "nl", {"name": "N", "id": "evil\n"}))
    assert t is None and err.startswith("id:")
    assert themes.get("evil\n") is None and themes.remove("evil\n") is False


def test_a_linked_theme_json_never_replaces_an_installed_theme(mx, tmp_path):
    good = _theme(tmp_path / "src", "good", {"name": "Good"})
    assert cli.main(["themes", "install", str(good)]) == 0
    link = tmp_path / "link" / "good"
    link.mkdir(parents=True)
    (tmp_path / "elsewhere.json").write_text(json.dumps({"name": "Good v2", "id": "good"}), encoding="utf-8")
    (link / "theme.json").symlink_to(tmp_path / "elsewhere.json")
    assert themes.load(link)[2]
    assert cli.main(["themes", "install", str(link), "--force"]) == 1
    assert themes.get("good")["name"] == "Good"
    assert sorted(p.name for p in (mx["ws"] / "themes").iterdir()) == ["good"]


def test_two_installs_of_the_same_theme_at_once_do_not_collide(mx, tmp_path):
    import threading
    src = _theme(tmp_path / "src", "race", {"name": "Race"}, {"README.md": b"x" * 20000})
    errors: list[BaseException] = []

    def run():
        for _ in range(40):
            try:
                themes.install(src, force=True)
            except BaseException as e:      # noqa: BLE001 - the test counts every failure
                errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors, errors[:3]
    assert themes.get("race")["name"] == "Race"
    assert sorted(p.name for p in (mx["ws"] / "themes").iterdir()) == ["race"]


def test_advanced_css_cannot_cover_the_app(tmp_path):
    for bad in ["& body::after { content: ''; position: absolute; inset: 0; z-index: 2147483647; background: #000 }",
                "& aside { position: if(media(min-width: 0px): fixed; else: static) }",
                "& aside::after { content: attr(title) }", "& aside { z-index: 10 }", "& aside { z-index: calc(9 + 1) }",
                "& aside {\n  z-index: 99\n}"]:
        t, warn, _ = themes.load(_theme(tmp_path, "cover", {"name": "C", "css": bad}))
        assert t["css"] is None and any(w.startswith("css:") for w in warn), bad
    for ok in ["& aside { z-index: 2; opacity: .9 }", "& aside { z-index: auto !important }"]:
        t, warn, _ = themes.load(_theme(tmp_path, "fine", {"name": "F", "css": ok}))
        assert t["css"], (ok, warn)


def test_serving_a_theme_image_does_not_read_the_theme_again(mx, monkeypatch, tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    src = _theme(tmp_path / "src", "cached", {"name": "Cached", "base": "glass", "wallpaper": "wall.png"},
                 {"wall.png": png})
    assert cli.main(["themes", "install", str(src)]) == 0
    calls = []
    real = themes._load
    monkeypatch.setattr(themes, "_load", lambda d: calls.append(d) or real(d))
    assert themes.file_path("cached", "wall.png") and themes.file_path("cached", "wall.png")
    assert len(calls) <= 1
    dest = mx["ws"] / "themes" / "cached"
    _theme(dest.parent, "cached", {"name": "Renamed", "base": "glass", "wallpaper": "wall.png"})
    assert themes.get("cached")["name"] == "Renamed"                                  # an edit is seen at once


def test_a_failed_replace_keeps_the_installed_theme(mx, monkeypatch, tmp_path):
    import errno
    v1 = _theme(tmp_path / "v1", "keep", {"name": "Keep v1"})
    v2 = _theme(tmp_path / "v2", "keep", {"name": "Keep v2"})
    themes.install(v1)
    real, calls = Path.rename, []

    def rename(self, target):
        calls.append(self)
        if len(calls) == 2:             # the new copy taking the place of the old one
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, target)

    with monkeypatch.context() as m:
        m.setattr(Path, "rename", rename)
        with pytest.raises(OSError):
            themes.install(v2, force=True)
    assert themes.get("keep")["name"] == "Keep v1"
    assert sorted(p.name for p in (mx["ws"] / "themes").iterdir()) == ["keep"]


def test_an_install_finished_meanwhile_is_not_replaced_without_force(mx, monkeypatch, tmp_path):
    first = _theme(tmp_path / "a", "twice", {"name": "First"})
    second = _theme(tmp_path / "b", "twice", {"name": "Second"})
    real = themes.tempfile.mkdtemp

    def mkdtemp(*a, **k):               # the other install completes after this one checked dest
        monkeypatch.setattr(themes.tempfile, "mkdtemp", real)
        themes.install(first)
        return real(*a, **k)

    monkeypatch.setattr(themes.tempfile, "mkdtemp", mkdtemp)
    with pytest.raises(themes.ThemeError):
        themes.install(second)
    assert themes.get("twice")["name"] == "First"
    assert sorted(p.name for p in (mx["ws"] / "themes").iterdir()) == ["twice"]


def test_work_folders_left_by_a_killed_install_are_removed(mx, tmp_path):
    import os
    import time
    src = _theme(tmp_path / "src", "left", {"name": "Left"})
    r = mx["ws"] / "themes"
    stale, recent = r / ".left.dead0001", r / ".left.busy0002"
    for d in (stale / "left", recent / "left"):
        d.mkdir(parents=True)
    old = time.time() - 3600
    os.utime(stale, (old, old))
    themes.install(src)
    assert sorted(p.name for p in r.iterdir()) == [".left.busy0002", "left"]   # a running install keeps its own


def test_a_linked_preview_png_is_not_announced(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    (tmp_path / "elsewhere.png").write_bytes(png)
    d = _theme(tmp_path, "linked", {"name": "Linked"})
    (d / "preview.png").symlink_to(tmp_path / "elsewhere.png")
    assert themes.load(d)[0]["preview"] is None          # file_path() refuses links: it would be a 404
    (d / "preview.png").unlink()
    (d / "preview.png").write_bytes(png)
    assert themes.load(d)[0]["preview"] == "/api/themes/linked/file/preview.png"
