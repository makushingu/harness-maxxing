"""Security fixes of the interface, read in its sources: what a text written by someone else may load, draw or type."""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def _src(*parts: str) -> str:
    return WEB.joinpath(*parts).read_text(encoding="utf-8")


def _fn(src: str, start: str, end: str = "\n}\n") -> str:
    a = src.index(start)
    return src[a:src.index(end, a)]


def test_a_diagram_loads_nothing_from_elsewhere():
    src = _src("components", "ui", "diagram.tsx")
    labels = _fn(src, "const LABELS = {")
    # labels: no tag or attribute that loads something, and a diagram's own directives cannot give them back
    loads = re.search(r"const LOADS = '([^']+)'", src).group(1).split(",")
    assert {"img", "image", "video", "audio", "source", "picture", "input"} <= set(loads)
    assert "FORBID_TAGS: ['style', ...LOADS.split(',')]" in labels
    for attr in ("'style'", "'src'", "'srcset'", "'poster'"):
        assert attr in labels.split("FORBID_ATTR")[1], attr
    assert "'dompurifyConfig'" in labels.split("secure:")[1] and "'securityLevel'" in labels.split("secure:")[1]
    render = _fn(src, "async function render(")
    assert "securityLevel: 'strict'" in render and "...LABELS" in render
    # an image shape is refused before the drawing (mermaid downloads it to measure it), the drawing is filtered after
    assert render.index("refuseImages(mermaid, code)") < render.index("mermaid.render(")
    assert "noRemote((await mermaid.render(" in render
    css = re.compile(re.search(r"const REMOTE_CSS = /(.+)/gi\n", src).group(1), re.I)
    for bad in ("url(https://evil.test/a.png)", "url( 'https://evil.test/a.png')", 'url("//evil.test/a")', "url(/api/x)",
                "@import 'https://evil.test/a.css';"):
        assert css.sub("none", f"a{{background:{bad}}}").count("evil") == 0 and "/api/x" not in css.sub("none", bad), bad
    for ok in ("url(#arrow)", 'url("#arrow")', "url(data:image/png;base64,AA)"):
        assert css.sub("none", ok) == ok, ok


def test_a_markdown_picture_never_calls_an_api_route_by_itself():
    src = _src("components", "ui", "markdown.tsx")
    fn = _fn(src, "export function loadsAtOnce(")
    assert "decodeURIComponent(new URL(src, location.href).pathname)" in fn      # ./api, ../api, /%61pi
    assert "path.startsWith('/api/files/') && !path.includes('..')" in fn
    api = re.compile(re.search(r"return !/(.+?)/i\.test\(path\)", fn).group(1), re.I)
    for path in ("/api/system/update/preflight", "/api", "/API/mail/message", "//api/x"):
        assert api.search(path), path
    for path in ("/logo.png", "/apiary.png", "/x/api/a.png"):
        assert not api.search(path), path
    img = _fn(src, "      img({ src, alt }) {", "\n      },\n")
    assert "local === null || !loadsAtOnce(local) ? <RemoteImage" in img


def test_a_team_summary_draws_no_live_card():
    md = _src("components", "ui", "markdown.tsx")
    plain = _fn(md, "export const PLAIN_BLOCKS")
    assert "pre(" in plain and "<CodeBlock" in plain
    for live in ("PrReviewBlock", "GitBlock", "InfraBlock", "Diagram"):
        assert live not in plain, live
    chat = _src("features", "team", "Chat.tsx")
    assert "const SUMMARY_PARTS = { ...PLAIN_BLOCKS, img:" in chat
    assert chat.count("<Markdown") == 1 and "<Markdown components={SUMMARY_PARTS}" in chat


def test_an_approval_shows_the_whole_file_and_says_replace_all():
    items = _src("pages", "sessions", "Items.tsx")
    diff = _fn(items, "export function toolDiff(")
    assert "(whole ? lines : lines.slice(0, 200))" in diff
    assert "toolDiff(a.tool, a.input, 0, true)" in _src("pages", "sessions", "Approvals.tsx")
    tool = _fn(items, "export function ToolInput(")
    assert "input.replace_all === true" in tool and "e?.replace_all === true" in tool
    assert "{diff && everywhere && <p" in tool and "t('sessions.diff.all')" in tool
    for lang in ("en", "fr"):
        assert "'sessions.diff.all':" in _src("i18n", f"{lang}.ts"), lang


def test_only_a_link_of_the_app_types_a_prompt_in_a_new_session():
    arm = _src("features", "agents", "EditWithClaude.tsx")
    take = _fn(arm, "export function takePrompt(")
    assert "armed === prompt" in take and "armed = null" in take             # the armed prompt, once
    assert "armPrompt(url)" in _fn(arm, "export const draftUrl")
    index = _src("pages", "sessions", "index.tsx")
    assert re.search(r"if \(!prompt \|\| [^\n]*\|\| !takePrompt\(prompt\)\) return\n\s+prefillDraft\(", index)
    assert index.count("prefillDraft(") == 1
    # the links of the app that carry a prompt arm it; a link of a message (Markdown) does not
    assert "armPrompt" not in _src("components", "ui", "markdown.tsx")
    assert "onClick={() => armPrompt(href)}" in _src("pages", "dashboard", "blocks.tsx")
    assert "armPrompt(r)" in _src("pages", "dashboard", "HtmlWidget.tsx")
    assert "armPrompt(to)" in _src("pages", "ext", "index.tsx")
    for f in WEB.rglob("*.tsx"):
        if "i18n" not in f.parts and f.name != "EditWithClaude.tsx":
            assert not re.search(r"&prompt=\$\{", f.read_text(encoding="utf-8")), f"{f}: use draftUrl()"


def test_the_outbox_shows_every_recipient():
    src = _src("features", "mail", "agents.tsx")
    card = src[src.index('data-testid="mail-outbox-item"'):src.index("x.subject || t('mail.noSubject')")]
    for who in ("{to.join(', ')}", "{x.bcc.join(', ')}"):
        line = card[:card.index(who)].rsplit("<span className=", 2)[1]
        assert line.startswith('"wrap-anywhere"'), who
    assert card.count('className="truncate') == 1                             # the subject only
