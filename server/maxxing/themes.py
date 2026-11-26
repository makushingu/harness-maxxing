"""Installed themes: `<workspace>/themes/<id>/theme.json` (+ optional images). See docs/user/39-themes.md.

A theme is data, never code: values for a fixed list of the interface's variables (TOKENS), per mode, on top of one
of the two built-in themes (`base`: solid or glass). What a theme leaves out keeps the built-in value; what it gets
wrong (an unknown variable, a value of the wrong kind, text that would be unreadable) is dropped with a warning, so a
theme can never break the interface nor survive an update badly: the product only ever ADDS variables to TOKENS
(an old theme simply gets the default of a new one) and renames go through ALIASES.

    theme.json   {"schema": 1, "name": "Nord", "base": "solid", "light": {...}, "dark": {...}, "options": {...}}
    wallpaper.*  optional background image (glass base), wallpaper-dark.* for the dark mode
    logo.*       optional logo shown instead of the Harness one (sidebar, tab icon...), logo-dark.* for the dark mode
    preview.png  optional picture for a listing (Community); the cards in Settings are drawn from the colors
    README.md    optional

One escape hatch: `"css"`, a single field of advanced CSS for what no variable reaches. It is checked (no url(),
no @import, no fixed layer over the app, braces balanced: see _css), applied only inside html[data-theme-id="<id>"]
(CSS nesting, `&` = <html>), and switched off by itself when an update changes the interface's own CSS, until
`maxxing themes verify <id>` (Claude, after checking it still looks right) records the new build: this is the part
of a theme that MAY break with an update, the variables never do.

`load(dir)` -> (theme | None, warnings, error); `list_themes()` = every folder of <workspace>/themes, sanitized:
the web app writes the values as they come (`web/src/lib/themes.ts`).
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from . import config

SCHEMA = 1
BASES = ("solid", "glass")
MODES = ("light", "dark")
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")     # always fullmatch: $ would let a final newline in
MAX_JSON = 64 * 1024
MAX_IMAGE = 4 * 1024 * 1024
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".avif": "image/avif"}
MAX_LOGO = 512 * 1024
MAX_CSS = 16 * 1024
CSS_STAMP = ".css-check.json"                    # {"ui": fingerprint of the app's CSS when the theme's css was checked}
FILES = ("theme.json", "README.md", "LICENSE")    # copied by install (+ the images the theme names)

# The contract: every variable a theme may set, and its kind. Names are the CSS custom properties of
# web/src/styles/globals.css without `--` (tests/test_themes.py checks each one exists there). Only ever add.
COLOR, LENGTH, SHADOW, HUE, CHROMA, LIGHTNESS, PERCENT = "color", "length", "shadow", "hue", "chroma", "lightness", "percent"
TOKENS: dict[str, str] = {
    # surfaces, from the furthest (the frame) to the nearest (what floats)
    "sidebar": COLOR, "list": COLOR, "background": COLOR, "card": COLOR, "popover": COLOR, "secondary": COLOR,
    "sunken": COLOR,
    # text
    "foreground": COLOR, "card-foreground": COLOR, "popover-foreground": COLOR, "secondary-foreground": COLOR,
    "muted-foreground": COLOR, "accent-foreground": COLOR,
    # fills (hover, selected, chips) and lines
    "muted": COLOR, "accent": COLOR, "border": COLOR, "input": COLOR, "sidebar-border": COLOR, "ring": COLOR,
    "overlay": COLOR,
    # the accent color and the states
    "primary": COLOR, "primary-foreground": COLOR, "destructive": COLOR, "destructive-foreground": COLOR,
    "success": COLOR, "warning": COLOR,
    # shape and depth
    "radius": LENGTH, "shadow-panel": SHADOW, "shadow-pop": SHADOW,
    # glass: the edge light, the blur, the two colors of the backdrop
    "glass-edge": COLOR, "glass-blur": LENGTH, "wall-a": COLOR, "wall-b": COLOR,
    # surface levels (advanced): hue and chroma of every surface, lightness of each level
    "sf-h": HUE, "sf-c": CHROMA, "l-frame": LIGHTNESS, "l-list": LIGHTNESS, "l-content": LIGHTNESS,
    "l-card": LIGHTNESS, "l-float": LIGHTNESS, "l-accent": LIGHTNESS,
    "a-fill-1": PERCENT, "a-fill-2": PERCENT, "a-fill-3": PERCENT,
}
ALIASES: dict[str, str] = {}      # old name -> new name, when a variable is renamed (never removed)
SURFACE = {"sidebar", "list", "background", "card", "popover", "secondary", "sunken", "sf-h", "sf-c", "l-frame",
           "l-list", "l-content", "l-card", "l-float", "l-accent"}
LIMITS = {"radius": 2.5, "glass-blur": 4.0}          # in rem (16 px)

# Fonts of the catalog (web/src/lib/fonts.ts; tests/test_themes.py keeps them equal).
SANS_FONTS = ("inter", "geist", "plex", "dmsans", "manrope", "jakarta", "grotesk", "outfit", "sora", "nunito",
              "quicksand", "comfortaa", "rubik", "sourceserif", "lora", "newsreader", "fraunces", "garamond",
              "atkinson", "lexend", "jetbrainsui", "martian", "system")
MONO_FONTS = ("system", "jetbrains", "fira", "geist", "cascadia", "sourcecode", "victor", "martian", "roboto",
              "redhat", "atkinsonmono")
ACCENTS = ("blue", "clay", "violet", "green", "amber", "rose")
OPTIONS = {"mode": ("dark", "light", "system"), "accent": ACCENTS, "tint": ("neutral", "tinted"),
           "font": SANS_FONTS, "mono": MONO_FONTS, "density": ("comfortable", "compact")}

# Readable text: (text, surface, minimum contrast ratio). Checked on the values the interface will really show
# (the theme's, else the built-in ones), per mode.
PAIRS = (("foreground", "background", 4.5), ("foreground", "sidebar", 4.5), ("card-foreground", "card", 4.5),
         ("popover-foreground", "popover", 4.5), ("muted-foreground", "background", 3.0),
         ("primary-foreground", "primary", 3.0), ("destructive-foreground", "destructive", 3.0))

# Built-in values used by the contrast check (Solid, neutral, blue accent; globals.css).
_LEVELS = {
    "light": {"sf-h": 286, "sf-c": 0.004, "l-frame": 0.928, "l-list": 0.958, "l-content": 0.988, "l-card": 1.0,
              "l-float": 1.0, "l-accent": 0.94},
    "dark": {"sf-h": 286, "sf-c": 0.006, "l-frame": 0.1, "l-list": 0.145, "l-content": 0.19, "l-card": 0.232,
             "l-float": 0.258, "l-accent": 0.305},
}
_TEXT = {
    "light": {"foreground": "oklch(0.141 0.005 285.823)", "muted-foreground": "oklch(0.552 0.016 285.938)",
              "primary": "oklch(0.58 0.2 256)", "primary-foreground": "oklch(0.99 0 0)",
              "destructive": "oklch(0.577 0.245 27.325)", "destructive-foreground": "oklch(0.985 0 0)"},
    "dark": {"foreground": "oklch(0.985 0 0)", "muted-foreground": "oklch(0.705 0.015 286.067)",
             "primary": "oklch(0.66 0.18 256)", "primary-foreground": "oklch(0.99 0 0)",
             "destructive": "oklch(0.637 0.208 25.331)", "destructive-foreground": "oklch(0.985 0 0)"},
}


class ThemeError(Exception):
    pass


def root() -> Path:
    return config.workspace() / "themes"


# ---------------------------------------------------------------------------------------------- values

_NUM = r"[+-]?(?:\d+\.?\d*|\.\d+)"
_COLOR_FN = re.compile(r"^(rgba?|hsla?|oklch|oklab)\(\s*([0-9.,%\s/+-]|deg)*\)$", re.I)
_HEX = re.compile(r"^#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$", re.I)
_LEN = re.compile(rf"^({_NUM})(px|rem|em)?$")
_SHADOW_WORDS = {"rgb", "rgba", "hsl", "hsla", "oklch", "oklab", "inset", "px", "rem", "em", "deg", "transparent",
                 "none"}


def _clean(kind: str, name: str, v: Any) -> str | None:
    """The value as CSS, or None when it is not a value of that kind (never anything that could load or run)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        v = str(v)
    if not isinstance(v, str):
        return None
    v = " ".join(v.split())
    if not v or len(v) > 200 or any(c in v for c in ";{}<>\\\"'`@:!"):
        return None
    low = v.lower()
    if kind == COLOR:
        if low == "transparent" or _HEX.match(v):
            return v
        return v if _COLOR_FN.match(v) and parse_color(v) is not None else None
    if kind == LENGTH:
        m = _LEN.match(low)
        if not m:
            return None
        n, unit = float(m.group(1)), m.group(2) or "px"
        rem = n / 16 if unit == "px" else n
        if n < 0 or (unit == "px" and n != 0 and not m.group(2)) or rem > LIMITS.get(name, 2.5):
            return None
        return f"{m.group(1)}{unit}"
    if kind == SHADOW:
        if low == "none":
            return "none"
        if not re.fullmatch(r"[0-9a-z.,%\s()/#+-]+", low) or not set(re.findall(r"[a-z]+", low)) <= _SHADOW_WORDS:
            return None
        depth = 0                       # an open "(" would swallow the rest of the theme's rules
        for c in low:
            depth += (c == "(") - (c == ")")
            if depth < 0 or depth > 1:
                return None
        if depth:
            return None
        return v
    try:
        n = float(v.rstrip("%"))
    except ValueError:
        return None
    if kind == HUE:
        return f"{n % 360:g}" if math.isfinite(n) else None
    if kind == CHROMA:
        return f"{n:g}" if 0 <= n <= 0.4 else None
    if kind == LIGHTNESS:
        return f"{n:g}" if 0 <= n <= 1 else None
    if kind == PERCENT:
        return f"{n:g}%" if 0 <= n <= 40 else None
    return None


def parse_color(v: str) -> tuple[float, float, float, float] | None:
    """(r, g, b, alpha) in 0..1 (sRGB, gamut-clipped) for hex, rgb(), hsl() and oklch(); None otherwise."""
    v = v.strip().lower()
    if v == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    if v.startswith("#"):
        h = v[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        try:
            vals = [int(h[i:i + 2], 16) / 255 for i in range(0, len(h), 2)]
        except ValueError:
            return None
        return (vals[0], vals[1], vals[2], vals[3] if len(vals) == 4 else 1.0)
    m = re.match(r"^([a-z]+)\((.*)\)$", v)
    if not m:
        return None
    fn, body = m.group(1), m.group(2).replace(",", " ").replace("/", " / ")
    parts = body.split()
    alpha = 1.0
    if "/" in parts:
        i = parts.index("/")
        try:
            alpha = _num(parts[i + 1], 1.0)
        except (ValueError, IndexError):
            return None
        parts = parts[:i]
    elif fn in ("rgba", "hsla") and len(parts) == 4:
        alpha = _num(parts.pop(), 1.0)
    if len(parts) != 3:
        return None
    try:
        if fn in ("rgb", "rgba"):
            r, g, b = (_num(p, 255.0) for p in parts)
            return (_clip(r), _clip(g), _clip(b), _clip(alpha))
        if fn in ("hsl", "hsla"):
            h = float(parts[0].replace("deg", "")); s = _num(parts[1], 100.0); li = _num(parts[2], 100.0)
            return (*_hsl(h, s, li), _clip(alpha))
        if fn == "oklch":
            L = _num(parts[0], 1.0); C = float(parts[1]); H = float(parts[2].replace("deg", ""))
            return (*_oklab(L, C * math.cos(math.radians(H)), C * math.sin(math.radians(H))), _clip(alpha))
        if fn == "oklab":
            return (*_oklab(_num(parts[0], 1.0), float(parts[1]), float(parts[2])), _clip(alpha))
    except ValueError:
        return None
    return None


def _num(p: str, scale: float) -> float:
    """A number, or a percentage of `scale` (rgb: 255 -> 0..1; alpha and oklch L: 1)."""
    if p.endswith("%"):
        return float(p[:-1]) / 100
    n = float(p)
    return n / scale if scale != 1.0 else n


def _clip(x: float) -> float:
    return min(1.0, max(0.0, x))


def _hsl(h: float, s: float, li: float) -> tuple[float, float, float]:
    import colorsys
    return colorsys.hls_to_rgb((h % 360) / 360, _clip(li), _clip(s))


def _oklab(L: float, a: float, b: float) -> tuple[float, float, float]:
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    lin = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
           -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
           -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)

    def enc(x: float) -> float:
        x = _clip(x)
        return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
    return (enc(lin[0]), enc(lin[1]), enc(lin[2]))


def _luminance(rgb: tuple[float, float, float]) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(fg: str, bg: str, under: str | None = None) -> float | None:
    """WCAG contrast ratio of a text color on a surface (alphas composited on `under`, then on the surface)."""
    b = parse_color(bg)
    f = parse_color(fg)
    if b is None or f is None:
        return None
    if b[3] < 1:
        u = parse_color(under or "#808080") or (0.5, 0.5, 0.5, 1.0)
        b = tuple(b[i] * b[3] + u[i] * (1 - b[3]) for i in range(3)) + (1.0,)
    fr = tuple(f[i] * f[3] + b[i] * (1 - f[3]) for i in range(3))
    l1, l2 = _luminance(fr), _luminance(b[:3])
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _effective(mode: str, tokens: dict[str, str]) -> dict[str, str]:
    """The colors the interface will show in `mode` with these values (built-in ones where the theme is silent)."""
    lv = {k: float(str(tokens.get(k, v)).rstrip("%")) for k, v in _LEVELS[mode].items()}
    surf = {"sidebar": (lv["l-frame"], 1.0), "list": (lv["l-list"], 1.0), "background": (lv["l-content"], 1.0),
            "card": (lv["l-card"], 0.6), "popover": (lv["l-float"], 0.6)}
    out = {k: f"oklch({lv_} {lv['sf-c'] * f:g} {lv['sf-h']:g})" for k, (lv_, f) in surf.items()}
    out.update(_TEXT[mode])
    out["card-foreground"] = out["popover-foreground"] = out["foreground"]
    out.update(tokens)
    for k in ("card-foreground", "popover-foreground"):
        out.setdefault(k, out["foreground"])
    return out


# ---------------------------------------------------------------------------------------------- loading

def _text(v: Any, cap: int) -> Any:
    """A label: a string, or {"en": ..., "fr": ...} (other languages kept), cut at `cap`."""
    if isinstance(v, str):
        return v.strip()[:cap]
    if isinstance(v, dict):
        out = {k: str(x).strip()[:cap] for k, x in v.items() if isinstance(k, str) and re.fullmatch(r"[a-z]{2}", k)
               and isinstance(x, str) and x.strip()}
        return out or None
    return None


def _mode_tokens(raw: Any, mode: str, warn: list[str]) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        warn.append(f"{mode}: must be an object of variables, ignored")
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        name = ALIASES.get(str(k).lstrip("-"), str(k).lstrip("-"))
        kind = TOKENS.get(name)
        if not kind:
            warn.append(f"{mode}.{k}: unknown variable, ignored")
            continue
        val = _clean(kind, name, v)
        if val is None:
            warn.append(f"{mode}.{k}: {json.dumps(v)[:60]} is not a valid {kind}, the built-in value stays")
            continue
        out[name] = val
    # readable text: a pair below its minimum loses the theme's values (back to the built-in ones), then the
    # surface levels if the built-in text is still unreadable on them
    for fg, bg, need in PAIRS:
        eff = _effective(mode, out)
        c = contrast(eff[fg], eff[bg], eff.get("sidebar"))
        if c is None or c >= need:
            continue
        dropped = [k for k in (fg, bg) if k in out]
        for k in dropped:
            out.pop(k)
        eff = _effective(mode, out)
        c2 = contrast(eff[fg], eff[bg], eff.get("sidebar"))
        if c2 is not None and c2 < need:
            lv = [k for k in out if k in _LEVELS[mode]]
            for k in lv:
                out.pop(k)
            dropped += lv
        warn.append(f"{mode}: {fg} on {bg} reads badly (contrast {c:.1f}, needs {need:g}): "
                    f"{', '.join(dropped) or 'nothing'} back to the built-in value")
    return out


_CSS_BANNED = [
    (re.compile(r"url\s*\(|image-set\s*\(|image\s*\(|src\s*\(|element\s*\(", re.I),
     "no url(), image() or element(): images go in wallpaper"),
    (re.compile(r"@(?!media\b|supports\b|container\b)[a-z-]+", re.I), "only @media, @supports and @container"),
    (re.compile(r"expression\s*\(|javascript:|-moz-binding|behavior\s*:", re.I), "nothing that runs code"),
    (re.compile(r"position\s*:\s*(fixed|var\s*\()", re.I), "no position: fixed nor var() (nothing may cover the app)"),
    (re.compile(r"[<\\]"), "no < and no backslash"),
    (re.compile(r"\b(?:if|attr)\s*\(", re.I), "no if() nor attr()"),
    (re.compile(r"z-index\s*:(?!\s*(?:-?\d|auto|inherit|initial|unset|revert)\s*(?:!important\s*)?(?:[;}]|$))",
                re.I | re.M), "z-index: a single digit at most (nothing may cover the app)"),
]


def _css(v: Any, warn: list[str]) -> str | None:
    """The advanced CSS of a theme (a string, or a list of lines), or None with a warning: refused as a whole."""
    if v is None or v == "" or v == []:
        return None
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        v = "\n".join(v)
    if not isinstance(v, str):
        warn.append("css: must be a string or a list of lines, ignored")
        return None
    if len(v.encode()) > MAX_CSS:
        warn.append(f"css: over {MAX_CSS // 1024} KB, ignored")
        return None
    # CR and form feed end a string for the browser too: one unseen newline would let a rule leave the scope
    if re.search(r"[\x00-\x08\x0b-\x1f\x7f\u2028\u2029]", v):
        warn.append("css: control characters (only newlines and tabs), ignored")
        return None
    bare = re.sub(r"/\*.*?\*/", " ", v, flags=re.S)
    if "/*" in bare:
        warn.append("css: unclosed comment, ignored")
        return None
    depth, quote = 0, ""
    for c in bare:
        if quote:
            quote = "" if c == quote else quote
            if c == "\n":
                break
        elif c in "\"'":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                break
    if quote or depth:
        warn.append("css: braces or quotes do not balance, ignored")
        return None
    for rx, why in _CSS_BANNED:
        if rx.search(bare):
            warn.append(f"css: {why}, ignored")
            return None
    return bare.strip() or None


_FINGERPRINT: dict[str, Any] = {}


def ui_fingerprint() -> str:
    """Names of the interface's built CSS files (hashed by Vite: they change exactly when its CSS does). Kept while
    the assets folder is unchanged: every theme image served reads it."""
    import hashlib
    from . import webbuild
    assets = webbuild.active_dist() / "assets"
    try:
        key: tuple | None = (str(assets), assets.stat().st_mtime_ns)
    except OSError:
        key = None
    if key and _FINGERPRINT.get("key") == key:
        return _FINGERPRINT["fp"]
    try:
        names = sorted(f.name for f in assets.glob("*.css"))
    except OSError:
        names = []
    fp = hashlib.sha256("\n".join(names).encode()).hexdigest()[:16]
    _FINGERPRINT.update(key=key, fp=fp)
    return fp


def _css_hash(css: str) -> str:
    import hashlib
    return hashlib.sha256(css.encode()).hexdigest()[:16]


def _css_state(d: Path, css: str | None) -> str:
    """none | on | stale: off until verified when it was never checked, was checked against another build of the
    interface, or was edited since (the stamp holds both)."""
    if not css:
        return "none"
    try:
        stamp = json.loads((d / CSS_STAMP).read_text())
    except (OSError, ValueError):
        return "stale"
    ok = isinstance(stamp, dict) and stamp.get("ui") == ui_fingerprint() and stamp.get("css") == _css_hash(css)
    return "on" if ok else "stale"


def _stamp(d: Path, css: str) -> None:
    config.write_json(d / CSS_STAMP, {"ui": ui_fingerprint(), "css": _css_hash(css)})


def _image(d: Path, name: Any, what: str, warn: list[str], cap: int = MAX_IMAGE) -> str | None:
    if name is None:
        return None
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", name):
        warn.append(f"{what}: must be the name of a file in the theme folder, ignored")
        return None
    f = d / name
    if f.suffix.lower() not in IMAGE_TYPES:
        warn.append(f"{what}: {name} is not a png, jpg, webp or avif image, ignored")
        return None
    if not f.is_file() or f.is_symlink():
        warn.append(f"{what}: {name} is missing, ignored")
        return None
    if f.stat().st_size > cap:
        warn.append(f"{what}: {name} is over {cap // 1024} KB, ignored")
        return None
    return name


_LOADED: dict[str, tuple[tuple, tuple]] = {}      # folder -> (what it was read from, what load() gave)


def _load_key(d: Path) -> tuple | None:
    """What load() reads: theme.json's bytes, every file's name, size and time (images, the css stamp), the interface."""
    import hashlib
    try:
        files = tuple(sorted((e.name, e.is_symlink(), e.stat(follow_symlinks=False).st_size,
                              e.stat(follow_symlinks=False).st_mtime_ns) for e in os.scandir(d)))
        f = d / "theme.json"
        body = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() and not f.is_symlink() else ""
    except OSError:
        return None
    return files, body, ui_fingerprint()


def load(d: Path) -> tuple[dict | None, list[str], str | None]:
    """Reads and sanitizes one theme folder: (theme, warnings, error). An error means the theme is not usable.
    Kept while nothing it reads changed: every theme image served (logo, wallpaper, tab icon) loads its theme."""
    import copy
    key = _load_key(d)
    hit = _LOADED.get(str(d))
    if key is not None and hit and hit[0] == key:
        return copy.deepcopy(hit[1])
    res = _load(d)
    if key is not None:
        if len(_LOADED) > 256:
            _LOADED.clear()
        _LOADED[str(d)] = (key, copy.deepcopy(res))
    return res


def _load(d: Path) -> tuple[dict | None, list[str], str | None]:
    warn: list[str] = []
    f = d / "theme.json"
    if f.is_symlink():                  # install never copies a link: it would read a file outside the folder
        return None, warn, "theme.json must be a file, not a symbolic link"
    if not f.is_file():
        return None, warn, "no theme.json in the folder"
    if f.stat().st_size > MAX_JSON:
        return None, warn, f"theme.json is over {MAX_JSON // 1024} KB"
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError) as e:   # RecursionError: nested too deep
        return None, warn, f"theme.json is not valid JSON ({type(e).__name__ if isinstance(e, RecursionError) else e})"
    if not isinstance(raw, dict):
        return None, warn, "theme.json must be an object"
    schema = raw.get("schema", SCHEMA)
    if schema != SCHEMA:
        if isinstance(schema, int) and schema > SCHEMA:
            warn.append(f"schema {schema} is newer than this Harness Maxxing ({SCHEMA}): what it does not know is "
                        "ignored (update to get all of it)")
        else:
            return None, warn, f"schema must be {SCHEMA}"
    tid = str(raw.get("id") or d.name)
    if not ID_RE.fullmatch(tid):
        return None, warn, "id: 2-40 characters, lowercase letters, digits and dashes"
    if tid in BASES:
        return None, warn, f"id: {tid} is a built-in theme, pick another id"
    name = _text(raw.get("name"), 40)
    if not name:
        return None, warn, "name is missing"
    base = raw.get("base", "solid")
    if base not in BASES:
        warn.append(f"base: {json.dumps(base)[:40]} is not solid or glass, solid is used")
        base = "solid"
    for k in raw:
        if k not in ("schema", "id", "name", "description", "author", "version", "homepage", "base", "light", "dark",
                     "options", "wallpaper", "wallpaper_dark", "logo", "logo_dark", "preview", "css"):
            warn.append(f"{k}: unknown key, ignored")
    modes = {m: _mode_tokens(raw.get(m), m, warn) for m in MODES}
    present = [m for m in MODES if isinstance(raw.get(m), dict)]
    options: dict[str, str] = {}
    ro = raw.get("options") or {}
    if not isinstance(ro, dict):
        warn.append("options: must be an object, ignored")
        ro = {}
    for k, v in ro.items():
        if k not in OPTIONS:
            warn.append(f"options.{k}: unknown option, ignored")
        elif v not in OPTIONS[k]:
            warn.append(f"options.{k}: {json.dumps(v)[:40]} is not one of {', '.join(OPTIONS[k])}, ignored")
        else:
            options[k] = v
    if len(present) == 1 and "mode" in options:     # its only mode applies while it is in use: nothing to suggest
        if options["mode"] != present[0]:
            warn.append(f"options.mode: the theme only has a {present[0]} mode, ignored")
        del options["mode"]
    wall = {"light": _image(d, raw.get("wallpaper"), "wallpaper", warn)}
    wall["dark"] = _image(d, raw.get("wallpaper_dark"), "wallpaper_dark", warn) or wall["light"]
    if base != "glass" and (wall["light"] or wall["dark"]):
        warn.append("wallpaper: only a glass theme shows a wallpaper (\"base\": \"glass\"), ignored")
        wall = {"light": None, "dark": None}
    logo = {"light": _image(d, raw.get("logo"), "logo", warn, MAX_LOGO)}
    logo["dark"] = _image(d, raw.get("logo_dark"), "logo_dark", warn, MAX_LOGO) or logo["light"]
    logo["light"] = logo["light"] or logo["dark"]
    css = _css(raw.get("css"), warn)
    preview = _image(d, raw.get("preview"), "preview", warn) if raw.get("preview") is not None else (
        "preview.png" if (d / "preview.png").is_file() and not (d / "preview.png").is_symlink()
        and (d / "preview.png").stat().st_size <= MAX_IMAGE else None)
    return {
        "id": tid,
        "schema": SCHEMA,
        "name": name,
        "description": _text(raw.get("description"), 200) or "",
        "author": str(raw.get("author") or "")[:60],
        "version": str(raw.get("version") or "")[:20],
        "homepage": str(raw.get("homepage") or "")[:200] if str(raw.get("homepage") or "").startswith("https://") else "",
        "base": base,
        "modes": present or list(MODES),
        "light": modes["light"],
        "dark": modes["dark"],
        "options": options,
        "own_accent": "primary" in modes["light"] or "primary" in modes["dark"],
        "own_surfaces": any(k in SURFACE for m in MODES for k in modes[m]),
        "wallpaper": {m: (f"/api/themes/{tid}/file/{wall[m]}" if wall[m] else None) for m in MODES},
        "logo": {m: (f"/api/themes/{tid}/file/{logo[m]}" if logo[m] else None) for m in MODES},
        "preview": f"/api/themes/{tid}/file/{preview}" if preview else None,
        "css": css,
        "css_state": _css_state(d, css),
        "warnings": warn,
    }, warn, None


def list_themes() -> dict:
    """Every folder of <workspace>/themes: {"themes": [usable ones, by name], "errors": [{id, error}]}."""
    themes, errors = [], []
    r = root()
    for d in sorted(r.iterdir()) if r.is_dir() else []:
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        try:
            t, _, err = load(d)
        except Exception as e:          # one broken folder never hides the others
            t, err = None, str(e) or type(e).__name__
        if t and t["id"] != d.name:
            t, err = None, f"its id ({t['id']}) differs from its folder name"
        if t:
            themes.append(t)
        else:
            errors.append({"id": d.name, "error": err})
    themes.sort(key=lambda t: str(t["name"] if isinstance(t["name"], str) else t["name"].get("en") or t["id"]).lower())
    return {"themes": themes, "errors": errors}


def get(tid: str) -> dict | None:
    if not ID_RE.fullmatch(tid) or not (root() / tid).is_dir():
        return None
    t, _, _ = load(root() / tid)
    return t


def file_path(tid: str, name: str) -> Path | None:
    """An image a theme names (wallpaper, wallpaper_dark, logo, logo_dark, preview), else None."""
    t = get(tid)
    if not t:
        return None
    urls = [*t["wallpaper"].values(), *t["logo"].values(), t["preview"]]
    if f"/api/themes/{tid}/file/{name}" not in urls:
        return None
    f = root() / tid / name
    return f if f.is_file() and not f.is_symlink() else None


STALE_STAGE_S = 600                    # an install takes seconds: an older work folder was left by a killed one


def _drop_stale_stages(tid: str, keep: Path) -> None:
    """Removes the work folders (.<id>.XXXX) that an install killed midway left in themes/."""
    now = time.time()
    for d in root().glob(f".{tid}.*"):
        try:
            if d != keep and d.is_dir() and not d.is_symlink() and now - d.stat().st_mtime > STALE_STAGE_S:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def install(src: Path, force: bool = False) -> tuple[dict, list[str]]:
    """Copies a checked theme folder into <workspace>/themes/<id>/: theme.json, its images, README and LICENSE only."""
    src = src.expanduser().resolve()
    if src.is_file() and src.name == "theme.json":
        src = src.parent
    t, warn, err = load(src)
    if err or not t:
        raise ThemeError(err or "not a theme")
    dest = root() / t["id"]
    if dest.exists() and dest.resolve() != src:
        if not force:
            raise ThemeError(f"a theme {t['id']} is already installed (--force replaces it)")
    names = set(FILES) | {u.rsplit("/", 1)[1] for u in [*t["wallpaper"].values(), *t["logo"].values(), t["preview"]] if u}
    if dest.resolve() == src:
        return t, warn
    root().mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(dir=root(), prefix=f".{t['id']}."))   # one per install: two never share it
    tmp = stage / t["id"]               # named like the theme: load() falls back on the folder name for the id
    tmp.mkdir(parents=True)
    for n in names:
        f = src / n
        if f.is_file() and not f.is_symlink():
            shutil.copy2(f, tmp / n)
    _, _, err = load(tmp)               # the copy itself must be usable before it replaces anything
    if err:
        shutil.rmtree(stage, ignore_errors=True)
        raise ThemeError(err)
    if t["css"]:
        _stamp(tmp, t["css"])           # installed by Claude after `check`: checked against this interface
    fd = os.open(root(), os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # two installs of the same theme swap one after the other
        _drop_stale_stages(t["id"], stage)
        if dest.exists() and not force:     # another install may have finished since the check above
            raise ThemeError(f"a theme {t['id']} is already installed (--force replaces it)")
        old = stage / "old"
        if dest.exists():
            dest.rename(old)            # never a moment without the theme for a browser that lists it
        try:
            tmp.rename(dest)
        except BaseException:
            if old.exists() and not dest.exists():
                old.rename(dest)        # the finally empties the stage: put the installed theme back first
            raise
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        shutil.rmtree(stage, ignore_errors=True)
    t2, warn2, _ = load(dest)
    return t2 or t, warn2


def verify(tid: str) -> dict:
    """Records that the theme's css was checked against the interface as it is now (turns it back on)."""
    d = root() / tid
    if not ID_RE.fullmatch(tid) or not d.is_dir():
        raise ThemeError(f"no installed theme {tid}")
    t, warn, err = load(d)
    if err or not t:
        raise ThemeError(err or "not a theme")
    if t["css"]:
        _stamp(d, t["css"])
        t["css_state"] = "on"
    return t


def remove(tid: str) -> bool:
    d = root() / tid
    if not ID_RE.fullmatch(tid) or not d.is_dir():
        return False
    shutil.rmtree(d)
    return True
