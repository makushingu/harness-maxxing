"""Themes: the contract with the interface (every variable exists in globals.css, fonts match the catalog), the
fallback to the built-in values, values that could load or run something, contrast, install / remove, the API."""
from __future__ import annotations

import json
import re
from pathlib import Path

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
