"""`maxxing video new DIR` / `maxxing video render DIR` / `maxxing video status` / `maxxing pdf IN.html OUT.pdf`.

The installer prepares Remotion once in <state>/tools/remotion (node_modules + headless browser,
~700 MB); every video project links its node_modules there, so a new project is ready in a second
and weighs a few MB. The same headless browser prints HTML to PDF.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import cli, config


def _node() -> str | None:
    from .sessions.spawn import base_env
    return shutil.which("node", path=base_env()["PATH"])

HINT = "run `maxxing deps update` (as root) to install Node.js, Remotion and the browser"


def tools_dir() -> Path:
    return config.STATE / "tools" / "remotion"


def template_dir() -> Path:
    return config.CODE / "templates" / "remotion"


def browser() -> Path | None:
    """The server's one Chromium (Playwright's build, shared with Scrapling and Remotion renders), else the headless
    shell older installs downloaded for Remotion. Used for PDFs."""
    from . import deps
    shared = deps.chromium_bin()
    if shared:
        return shared
    base = tools_dir() / "node_modules" / ".remotion" / "chrome-headless-shell"
    for p in sorted(base.glob("*/chrome-headless-shell-*/chrome-headless-shell")) if base.is_dir() else []:
        if p.is_file():
            return p
    return None


def status() -> dict:
    node = _node()
    version = ""
    if node:
        try:
            version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            version = ""
    ready = (tools_dir() / "node_modules" / "remotion").is_dir()
    from . import deps
    scrapling = deps.scrapling_python() is not None and deps.chromium_bin() is not None
    return {"node": version or None, "remotion": ready, "browser": str(browser() or "") or None,
            "scrapling": scrapling, "tools_dir": str(tools_dir())}


def new_project(dest: Path) -> Path:
    if not (tools_dir() / "node_modules").is_dir():
        raise SystemExit("Remotion is not prepared on this server: " + HINT.format(code=config.CODE))
    if dest.exists() and not dest.is_dir():
        raise SystemExit(f"{dest} already exists and is a file, not a folder")
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} already exists and is not empty")
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for item in template_dir().iterdir():
            if item.name in ("node_modules", "package-lock.json", "out"):
                continue
            (shutil.copytree if item.is_dir() else shutil.copy2)(item, dest / item.name)
        (dest / "public").mkdir(exist_ok=True)
        (dest / "node_modules").symlink_to(tools_dir() / "node_modules", target_is_directory=True)
        (dest / ".gitignore").write_text("node_modules\nout\n")
    except OSError as e:
        raise SystemExit(f"Cannot create the project in {dest}: {e.strerror or e}") from None
    return dest


def pdf(src: str, out: Path) -> None:
    b = browser()
    if b is None:
        raise SystemExit("No headless browser on this server: " + HINT.format(code=config.CODE))
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise SystemExit(f"PDF failed: cannot create {out.parent}: {e.strerror or e}") from None
    url = src if src.startswith(("http://", "https://")) else Path(src).expanduser().resolve().as_uri()
    node = _node()
    if node is None:
        raise SystemExit("Node.js is not installed: " + HINT.format(code=config.CODE))
    script = Path(__file__).resolve().parent / "assets" / "print_pdf.mjs"
    try:
        r = subprocess.run([node, str(script), str(b), url, str(out.resolve())], capture_output=True, text=True,
                           timeout=180)
    except subprocess.TimeoutExpired:
        # a page that never finishes loading: same clean exit as the other failures, not a traceback
        raise SystemExit("PDF failed: the page did not print within 180 s") from None
    if r.returncode != 0 or not out.exists():
        raise SystemExit("PDF failed: " + (r.stderr or r.stdout).strip()[-400:])


def render_cmd(entry: str, comp: str, out: str) -> list[str]:
    from .sessions.spawn import base_env
    npx = shutil.which("npx", path=base_env()["PATH"]) or "npx"     # the server's Node, even an isolated one
    return [npx, "remotion", "render", entry, comp, out]


def render(project: Path, comp: str = "Intro", out: str = "out/video.mp4") -> int:
    """Render a Remotion project through `maxxing heavy`: a render takes every core for minutes, it goes after the UI
    and the sessions (CPU priorities) and is never slowed while the processor has room."""
    entry = next((e for e in ("src/index.jsx", "src/index.tsx", "src/index.ts", "src/index.js")
                  if (project / e).is_file()), None)
    if entry is None:
        raise SystemExit(f"{project} is not a video project (no src/index.jsx): `maxxing video new DIR` makes one")
    from . import cmd_heavy
    return cmd_heavy.run(render_cmd(entry, comp, out), cwd=project)


def _configure_video(p) -> None:
    sub = p.add_subparsers(dest="video_cmd", required=True)
    n = sub.add_parser("new", help="create a Remotion video project (linked to the shared install)")
    n.add_argument("dir", help="folder to create, e.g. projects/acme/topics/blog/videos/launch")
    sub.add_parser("status", help="Node.js / Remotion / headless browser on this server")
    r = sub.add_parser("render", help="render a video project with the background priority (`maxxing heavy`)")
    r.add_argument("dir", nargs="?", default=".", help="the video project (default: the current folder)")
    r.add_argument("--id", default="Intro", help="the composition to render (default: Intro)")
    r.add_argument("--out", default="out/video.mp4", help="the file to write (default: out/video.mp4)")


def _video(a) -> int:
    if a.video_cmd == "status":
        st = status()
        print(f"node     : {st['node'] or 'not installed'}")
        print(f"remotion : {'ready' if st['remotion'] else 'not prepared'} ({st['tools_dir']})")
        print(f"browser  : {st['browser'] or 'not downloaded'}")
        print(f"scrapling: {'ready' if st['scrapling'] else 'not installed'} (web scraping)")
        if not st["remotion"]:
            print(HINT.format(code=config.CODE))
        return 0 if st["remotion"] else 1
    if a.video_cmd == "render":
        return render(Path(a.dir).expanduser(), a.id, a.out)
    d = new_project(Path(a.dir).expanduser())
    print(f"Video project ready: {d}")
    print(f"  cd {d} && npm run still     # check one frame (out/still.png)")
    print(f"  maxxing video render {d}    # out/video.mp4 (after the UI and the sessions when the CPU is full)")
    return 0


def _configure_pdf(p) -> None:
    p.add_argument("src", help="an HTML file (or an http(s) URL)")
    p.add_argument("out", help="the PDF to write")


def _pdf(a) -> int:
    if not a.src.startswith(("http://", "https://")) and not Path(a.src).expanduser().is_file():
        raise SystemExit(f"No such file: {a.src}")
    pdf(a.src, Path(a.out).expanduser())
    print(f"PDF written: {a.out}")
    return 0


cli.register("video", "Motion design videos with Remotion (new, render, status)", _configure_video, _video)
cli.register("pdf", "Print an HTML page to PDF with the headless browser", _configure_pdf, _pdf)
