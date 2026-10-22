#!/usr/bin/env python3
"""Generate every logo file from one vector drawing, for each accent color.

Run from anywhere: `uv run --with playwright python web/scripts/gen-icons.py` (the PNGs are rendered by Chromium;
set MX_CHROMIUM to a Chromium / chrome-headless-shell binary to skip `playwright install`). Outputs are committed,
so this only runs when the logo or the accents change.

public/icons/logo-<accent>.svg              the logo, vector (sidebar, splash, favicon, sign-in)
public/icons/logo-<accent>-64|128.png       the same, raster (older references, notifications fallback)
public/icons/icon-<accent>-192|512.png      installed app, "any" purpose: rounded square, transparent corners
public/icons/icon-maskable-<accent>-512.png "maskable": full-bleed background, logo inside the 80 % safe zone
                                            (Android cuts its own shape - corners must be filled)
public/icons/apple-touch-icon-<accent>.png  iOS home screen, 180 px, full-bleed and opaque (iOS rounds it)
public/manifest-<accent>.webmanifest        the web app manifest pointing at that accent's icons
The blue files are also written under the historical names (icon-192.png, icon-512.png, icon-maskable-512.png,
apple-touch-icon.png, favicon.svg, manifest.webmanifest) - the defaults before any accent is known.
"""
import colorsys
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

WEB = Path(__file__).resolve().parent.parent
PUBLIC = WEB / "public"
ICONS = PUBLIC / "icons"

# The logo body is a diagonal gradient; each accent rotates the hue of both stops (lightness and saturation kept).
BLUE_STOPS = ((45, 110, 253), (14, 199, 247))
ACCENT_BODY = {"blue": (42, 128, 254), "violet": (213, 42, 254), "clay": (254, 170, 42), "green": (51, 254, 42),
               "amber": (254, 241, 42), "rose": (254, 82, 42)}
PAPER, INK, METAL = "#faf9f4", "#1d1e24", "#d6d9df"
RADIUS = 112                                     # corner radius of the rounded square, on the 512 grid


def _hue(rgb):
    return colorsys.rgb_to_hls(*[c / 255 for c in rgb])


def stops(accent: str) -> list[str]:
    shift = _hue(ACCENT_BODY[accent])[0] - _hue(ACCENT_BODY["blue"])[0]
    out = []
    for rgb in BLUE_STOPS:
        h, l, s = _hue(rgb)
        r, g, b = colorsys.hls_to_rgb((h + shift) % 1, l, s)
        out.append("#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255)))
    return out


def svg(accent: str, *, size: int | None = None, rounded: bool = True, scale: float = 1.0) -> str:
    """The logo on a 512 grid. `rounded`: transparent corners (else full bleed); `scale` shrinks the drawing
    around the center (maskable safe zone)."""
    c0, c1 = stops(accent)
    rx = RADIUS if rounded else 0
    wh = f' width="{size}" height="{size}"' if size else ""
    t = 256 * (1 - scale)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"{wh}>'
        f'<defs><linearGradient id="g" x1="40" y1="96" x2="470" y2="414" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{c0}"/><stop offset="1" stop-color="{c1}"/></linearGradient>'
        f'<clipPath id="c"><rect width="512" height="512" rx="{rx}"/></clipPath></defs>'
        f'<g clip-path="url(#c)"><rect width="512" height="512" fill="{PAPER}"/>'
        f'<g transform="translate({t:g} {t:g}) scale({scale:g})">'
        # body: head, arms, belly, four legs
        '<path fill="url(#g)" d="M110 96H394V178H468V240H394V414H350V336H314V414H270V336H234V414H190V336H154V414H110'
        'V240H36V178H110Z"/>'
        f'<rect x="151" y="136" width="38" height="38" fill="{INK}"/><rect x="315" y="136" width="38" height="38" fill="{INK}"/>'
        # collar, its buckle and the leash going off the top-right corner
        f'<path d="M110 243Q246 264 380 232" fill="none" stroke="{INK}" stroke-width="15"/>'
        f'<path d="M384 227Q452 168 540 86" fill="none" stroke="{INK}" stroke-width="9" stroke-linecap="round"/>'
        f'<rect x="-9" y="-12" width="18" height="24" rx="5" fill="none" stroke="{METAL}" stroke-width="4"'
        ' transform="translate(381 231) rotate(-32)"/>'
        "</g></g></svg>"
    )


def manifest(accent: str) -> dict:
    m = json.loads((PUBLIC / "manifest.webmanifest").read_text())
    m["icons"] = [
        {"src": f"/icons/icon-{accent}-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": f"/icons/icon-{accent}-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": f"/icons/icon-maskable-{accent}-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ]
    for s in m.get("shortcuts", []):
        s["icons"] = [{"src": f"/icons/icon-{accent}-192.png", "sizes": "192x192"}]
    return m


def main():
    ICONS.mkdir(parents=True, exist_ok=True)
    launch = {"executable_path": os.environ["MX_CHROMIUM"]} if os.environ.get("MX_CHROMIUM") else {}
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        page = browser.new_page()

        def png(markup: str, size: int, path: Path):
            page.set_viewport_size({"width": size, "height": size})
            page.set_content(f'<html><body style="margin:0;background:transparent">{markup}</body></html>')
            page.locator("svg").screenshot(path=str(path), omit_background=True)

        for a in ACCENT_BODY:
            (ICONS / f"logo-{a}.svg").write_text(svg(a) + "\n")
            for size in (64, 128):
                png(svg(a, size=size), size, ICONS / f"logo-{a}-{size}.png")
            for size in (192, 512):
                png(svg(a, size=size), size, ICONS / f"icon-{a}-{size}.png")
            png(svg(a, size=512, rounded=False, scale=0.78), 512, ICONS / f"icon-maskable-{a}-512.png")
            png(svg(a, size=180, rounded=False, scale=0.94), 180, ICONS / f"apple-touch-icon-{a}.png")
            (PUBLIC / f"manifest-{a}.webmanifest").write_text(json.dumps(manifest(a), indent=2, ensure_ascii=False) + "\n")
            print("wrote", a)
        browser.close()

    for blue, default in (("icon-blue-192.png", "icon-192.png"), ("icon-blue-512.png", "icon-512.png"),
                          ("icon-maskable-blue-512.png", "icon-maskable-512.png"),
                          ("apple-touch-icon-blue.png", "apple-touch-icon.png")):
        (ICONS / default).write_bytes((ICONS / blue).read_bytes())
    (PUBLIC / "favicon.svg").write_text(svg("blue") + "\n")


if __name__ == "__main__":
    main()
