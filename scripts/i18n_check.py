#!/usr/bin/env python3
"""Checks the translations of the product: exit 1 when a language is incomplete, late or unsafe.

    python3 scripts/i18n_check.py [--langs zh,de] [--quiet]

Interface (web/src/i18n/<lang>.ts, English en.ts is the reference):
- same keys as en.ts, none missing, none left over;
- languages written by scripts/translate_ui.py (those listed in web/src/i18n/translated.json): every text was
  translated from the current English text (a changed or new English text makes it late until translate_ui.py ran);
- same variables ({name}) as the English text;
- nothing a translation could smuggle in: same HTML tags, same links, same `code` spans as the English text, no
  script, no event handler, no javascript: address.

Server (server/maxxing/**/*.py): every table of texts written {"en": ..., "fr": ...} also has the other interface
languages, with the same variables.

Run by scripts/ui-check.sh and by the publication of a version (publish.py of the site repository)."""
import argparse, ast, hashlib, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "web" / "src" / "i18n"
STATE = I18N / "translated.json"       # written by scripts/translate_ui.py
SERVER = ROOT / "server" / "maxxing"
# Tables keyed by language that are not interface texts (voices, speech recognition, browser locales).
SERVER_SKIP = {"tts.py", "voice.py", "voicecall.py", "browser/unit.py", "feedback.py"}

VAR = re.compile(r"\{[a-z][a-zA-Z0-9_]*\}")          # {name}; ${KEY_NAME} is a key of the vault, shown as is
TAG = re.compile(r"</?[a-zA-Z][^<>]*>")
URL = re.compile(r"https?://[A-Za-z0-9][^\s)\]}>\"'`，。、）]*")
CODE = re.compile(r"`[^`]+`")
BAD = re.compile(r"<\s*script|javascript:|\bon[a-z]+\s*=|<\s*iframe|data:text/html", re.I)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:10]


def languages() -> list[str]:
    """The interface languages besides English: one dictionary per language."""
    return sorted(f.stem for f in I18N.glob("??.ts") if f.stem != "en")


def dictionaries(langs: list[str]) -> dict[str, dict[str, str]]:
    """The dictionaries as Python tables, read by node (the files are TypeScript object literals)."""
    js = ("const out={};for(const l of JSON.parse(process.argv[1])){const m=await import(process.argv[2]+'/'+l+'.ts');"
          "out[l]=Object.values(m)[0]}process.stdout.write(JSON.stringify(out))")
    r = subprocess.run(["node", "--input-type=module", "--no-warnings", "-e", js, json.dumps(langs), str(I18N)],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"i18n check: node could not read the dictionaries\n{r.stderr.strip()[-600:]}")
    return json.loads(r.stdout)


HTML = {"a", "b", "i", "u", "em", "strong", "code", "pre", "br", "hr", "p", "div", "span", "ul", "ol", "li", "img",
        "kbd", "small", "sub", "sup", "script", "style", "iframe", "svg", "object", "embed", "link", "meta", "form",
        "input", "button", "video", "audio", "source", "base", "table", "tr", "td", "th", "h1", "h2", "h3", "h4"}


def _tags(text: str) -> list[str]:
    """The real HTML tags of a text (`<key>` or `<clé>` in a sentence is a placeholder, not a tag)."""
    names = (re.match(r"</?([a-zA-Z0-9]+)", t).group(1).lower() for t in TAG.findall(text))
    return sorted(n for n in names if n in HTML)


def _urls(text: str) -> set[str]:
    # an example such as http://host:port has no dot in its host: a placeholder, which a language may translate
    return {u.rstrip(".,;:!?") for u in URL.findall(text) if "." in u.split("//", 1)[1].split("/", 1)[0]}


def shape_problems(en: str, out: str, singular: bool = False) -> list[str]:
    """What a translation changed that it must not: variables, tags, links, code, anything executable.
    `singular`: a `key#one` text, which may spell the number out ("1 file") where another language keeps {count}."""
    bad = []
    ev, ov = set(VAR.findall(en)), set(VAR.findall(out))
    if ev != ov and not (singular and ev ^ ov <= {"{count}"}):
        bad.append("variables differ")
    if _tags(en) != _tags(out):
        bad.append("HTML tags differ")
    if _urls(en) != _urls(out):
        bad.append("links differ")
    if sorted(CODE.findall(en)) != sorted(CODE.findall(out)):
        bad.append("code spans differ")
    if BAD.search(out) and not BAD.search(en):
        bad.append("script or event handler")
    return bad


def check_web(langs: list[str]) -> list[str]:
    problems = []
    dicts = dictionaries(["en", *langs])
    en = dicts["en"]
    state = json.loads(STATE.read_text()) if STATE.exists() else {"source": {}, "late": {}}
    late_keys = {l: set(v) for l, v in state["late"].items()}
    state["late"] = late_keys
    for lang in langs:
        d = dicts[lang]
        missing = [k for k in en if k not in d]
        extra = [k for k in d if k not in en]
        if missing:
            problems.append(f"{lang}: {len(missing)} missing text(s), e.g. {', '.join(missing[:3])}")
        if extra:
            problems.append(f"{lang}: {len(extra)} text(s) no longer in en.ts, e.g. {', '.join(extra[:3])}")
        late = []
        for k, text in en.items():
            if k not in d:
                continue
            if lang in state["late"] and (k in state["late"][lang] or state["source"].get(k) != sha(text)):
                late.append(k)
                continue
            for p in shape_problems(text, d[k], k.endswith("#one")):
                problems.append(f"{lang}: {k}: {p}")
        if late:
            problems.append(f"{lang}: {len(late)} text(s) not translated from the current English text, e.g. "
                            f"{', '.join(late[:3])} (run scripts/translate_ui.py)")
    return problems


def _const(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _fields(node) -> list[str] | None:
    """The variables of a text literal ("..." or adjacent literals), None when it is not a plain text."""
    s = _const(node)
    return sorted(VAR.findall(s)) if s is not None else None


def check_server(langs: list[str]) -> list[str]:
    problems = []
    want = [l for l in langs if l != "fr"]
    for f in sorted(SERVER.rglob("*.py")):
        rel = f.relative_to(SERVER).as_posix()
        if rel in SERVER_SKIP:
            continue
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError as e:
            problems.append(f"server/{rel}: {e}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [_const(k) if k is not None else None for k in node.keys]
            if "en" not in keys or "fr" not in keys:
                continue
            by = dict(zip(keys, node.values))
            missing = [l for l in want if l not in by]
            if missing:
                problems.append(f"server/{rel}:{node.lineno}: texts in en and fr but not in {', '.join(missing)}")
                continue
            ref = _fields(by["en"])
            ref_keys = sorted(_const(k) or "" for k in by["en"].keys) if isinstance(by["en"], ast.Dict) else None
            for l in want:
                if ref is not None and _fields(by[l]) not in (None, ref):
                    problems.append(f"server/{rel}:{by[l].lineno}: {l}: variables differ from the English text")
                if ref_keys is not None and isinstance(by[l], ast.Dict):
                    got = sorted(_const(k) or "" for k in by[l].keys)
                    if got != ref_keys:
                        lost = sorted(set(ref_keys) - set(got))[:3]
                        problems.append(f"server/{rel}:{by[l].lineno}: {l}: not the same entries as en"
                                        + (f" (missing {', '.join(lost)})" if lost else ""))
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--langs", help="only these languages (default: every dictionary of web/src/i18n)")
    ap.add_argument("--quiet", action="store_true", help="print nothing when everything is fine")
    ap.add_argument("--web-only", action="store_true", help="skip the server texts")
    a = ap.parse_args()
    langs = [l for l in (a.langs.split(",") if a.langs else languages()) if l != "en"]
    problems = check_web(langs)
    if not a.web_only and SERVER.is_dir():
        problems += check_server(langs)
    if problems:
        shown = problems[:60]
        print("\n".join(shown) + (f"\n… and {len(problems) - len(shown)} more" if len(problems) > len(shown) else ""))
        print(f"i18n check: {len(problems)} problem(s)")
        return 1
    if not a.quiet:
        print(f"i18n check: {', '.join(langs)} complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
