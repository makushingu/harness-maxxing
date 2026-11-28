#!/usr/bin/env python3
"""Translations of the interface: web/src/i18n/en.ts (the reference, written by hand, like fr.ts) into the other
languages, web/src/i18n/<lang>.ts.

    python3 scripts/translate_ui.py [--langs zh,de] [--jobs 3] [--batch 90] [--dry-run] [--only settings]
    python3 scripts/translate_ui.py --accept      # after translating by hand the texts the model could not

A text is (re)translated only when it is new or when its English text changed: web/src/i18n/translated.json keeps
the fingerprint of the English text the translations were made from, and the texts still late in each language. A
correction made by hand in <lang>.ts therefore stays, until the English text changes. A key gone from en.ts is
removed.

The translation is done by Claude Code in headless mode (`claude -p`), with the subscription of the machine that
runs this script (or the sign-in of the Harness Maxxing installed on it): no API key here. Each answer is checked (scripts/i18n_check.py: same variables, tags, links and
code as the English text); a text that fails twice keeps its English text and stays "late", which
scripts/i18n_check.py reports and the publication of a version refuses.

Run it before sending a change of en.ts; `scripts/i18n_check.py` says whether it is needed."""
import argparse, concurrent.futures as cf, functools, json, os, re, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i18n_check as chk

MODEL = os.environ.get("HM_TRANSLATE_MODEL", "sonnet")
LANGS = {
    "zh": ("Simplified Chinese (zh-CN)", "简体中文",
           "Concise, natural software Chinese. Full-width punctuation in sentences; a space between Chinese and "
           "Latin words or numbers is not needed. Address the user without 您 unless the sentence needs it.",
           {"session": "会话", "topic": "主题", "project": "项目", "agent": "智能体", "Settings": "设置", "Keys": "密钥",
            "Dashboard": "仪表盘", "Tasks": "任务", "Files": "文件", "memory": "记忆", "scheduled job / cron": "定时任务",
            "Notifications (the feed)": "通知", "Team": "团队", "skill": "技能", "widget": "小组件", "extension": "扩展",
            "backup": "备份", "turn (of Claude)": "回合", "worktree / separate copy": "独立副本", "webhook": "Webhook"}),
    "de": ("German", "Deutsch",
           "Informal address (du, dein), as on the product's website. Short labels for buttons; no English word when a "
           "common German one exists.",
           {"session": "Sitzung", "topic": "Thema", "project": "Projekt", "agent": "Agent", "Settings": "Einstellungen",
            "Keys": "Schlüssel", "Dashboard": "Dashboard", "Tasks": "Aufgaben", "Files": "Dateien",
            "memory": "Gedächtnis", "scheduled job / cron": "geplanter Job", "Notifications (the feed)": "Benachrichtigungen",
            "Team": "Team", "skill": "Skill", "widget": "Widget", "extension": "Erweiterung", "backup": "Backup",
            "turn (of Claude)": "Durchlauf", "worktree / separate copy": "separate Kopie", "webhook": "Webhook"}),
    "ja": ("Japanese", "日本語",
           "Polite です・ます style in sentences, plain noun or verb-stem labels for buttons and menus. Katakana for "
           "established software terms. Full-width punctuation.",
           {"session": "セッション", "topic": "トピック", "project": "プロジェクト", "agent": "エージェント",
            "Settings": "設定", "Keys": "キー", "Dashboard": "ダッシュボード", "Tasks": "タスク", "Files": "ファイル",
            "memory": "メモリ", "scheduled job / cron": "定期ジョブ", "Notifications (the feed)": "通知", "Team": "チーム",
            "skill": "スキル", "widget": "ウィジェット", "extension": "拡張機能", "backup": "バックアップ",
            "turn (of Claude)": "ターン", "worktree / separate copy": "別コピー", "webhook": "Webhook"}),
    "es": ("Spanish (neutral, understood in Spain and Latin America)", "Español",
           "Informal address (tú, tu), as on the product's website. Opening ¿ and ¡ where Spanish needs them.",
           {"session": "sesión", "topic": "tema", "project": "proyecto", "agent": "agente", "Settings": "Ajustes",
            "Keys": "Claves", "Dashboard": "Panel", "Tasks": "Tareas", "Files": "Archivos", "memory": "memoria",
            "scheduled job / cron": "tarea programada", "Notifications (the feed)": "Notificaciones", "Team": "Equipo",
            "skill": "skill", "widget": "widget", "extension": "extensión", "backup": "copia de seguridad",
            "turn (of Claude)": "turno", "worktree / separate copy": "copia separada", "webhook": "webhook"}),
}

PROMPT = """You translate the interface texts of Harness Maxxing (a web control room for Claude Code that runs on the
user's own server: sessions with Claude, projects and topics, agents, scheduled jobs, files, tasks, Telegram) from
English into {lang}.

Input (stdin): a JSON object, key -> {{"en": English text, "fr": the French text already in the product}}. The key
tells where the text is shown (settings.*, sessions.*, agents.*...); the French text is there only to make the
meaning clear, translate from the English one.

Output: ONLY a JSON object, the same keys -> the text in {lang}. No code fence, nothing before or after.

Rules:
- {style}
- Interface texts: buttons, menus, titles, hints, error messages. Keep them as short as the English text; a button
  stays a button label.
- Keep exactly, untouched: variables in braces ({{count}}, {{name}}...), HTML tags, URLs, `code` spans, commands, file
  paths and file names (CLAUDE.md, memory.md, tasks.json), environment variables, keyboard keys (Ctrl+K), emojis,
  the characters … → · and the line breaks (\\n).
- Never translate these names: Harness Maxxing, Harness, Claude, Claude Code, Anthropic, Telegram, GitHub, Git,
  Shopify, Stripe, Cloudflare, Tailscale, Caddy, MCP, Jarvis, Radar, and every product, model or service name.
  "fair source" stays in English.
- A key ending in "#one" is the singular of the same key without it (used when {{count}} is 1): translate it as a
  singular even when the language makes no difference.
- Use these words for the product's notions, always the same ones:
{glossary}
- Never add an explanation, a note or anything that is not in the English text."""


def write_dict(lang: str, texts: dict[str, str], order: list[str]) -> None:
    name = LANGS[lang][1]
    lines = [f"import type {{ en }} from './en'", "",
             f"// {name}: written by scripts/translate_ui.py from en.ts (a text is redone only when its English text",
             "// changes: corrections made here by hand stay). Must have every key of en.ts (TypeScript).",
             f"export const {lang}: Record<keyof typeof en, string> = {{"]
    lines += [f"  {json.dumps(k, ensure_ascii=False)}: {json.dumps(texts[k], ensure_ascii=False)}," for k in order]
    (chk.I18N / f"{lang}.ts").write_text("\n".join(lines) + "\n}\n")


@functools.cache
def claude_env() -> dict[str, str]:
    """The environment of `claude -p`: this shell's, plus the Claude sign-in of the Harness Maxxing installed on this
    machine when the shell has none (the shell of a session does not carry it). Nothing else of the vault."""
    env, names = dict(os.environ), ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
    if not any(env.get(n) for n in names):
        try:
            sys.path.insert(0, str(chk.ROOT / "server"))
            from maxxing.sessions import spawn
            env.update({k: v for k, v in spawn.auth_env().items() if k in names})
        except Exception:  # noqa: BLE001 - no Harness here: `claude login` of this machine is used
            pass
    return env


def claude(lang: str, batch: dict[str, dict[str, str]]) -> dict[str, str]:
    name, _, style, glossary = LANGS[lang]
    system = PROMPT.format(lang=name, style=style, glossary="\n".join(f"  {a} -> {b}" for a, b in glossary.items()))
    with tempfile.TemporaryDirectory() as cwd:      # away from the repository: no CLAUDE.md, no project memory
        r = subprocess.run(["claude", "-p", "--model", MODEL, "--tools", "", "--no-session-persistence",
                            "--strict-mcp-config", "--system-prompt", system],
                           input=json.dumps(batch, ensure_ascii=False, indent=0), capture_output=True, text=True,
                           cwd=cwd, timeout=900, env=claude_env())
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-300:] or f"claude exited {r.returncode}")
    return parse(r.stdout, lang)


def parse(out: str, lang: str) -> dict[str, str]:
    """The key -> text table of an answer. Tolerates what the model sometimes does instead of one flat object: a
    code fence, several objects one after the other, or {key: {"<lang>": text}}."""
    out = re.sub(r"^```[a-z]*\n|\n```$", "", out.strip())
    dec, at, data = json.JSONDecoder(), 0, {}
    while (start := out.find("{", at)) >= 0:
        try:
            obj, at = dec.raw_decode(out, start)
        except json.JSONDecodeError:
            at = start + 1
            continue
        if isinstance(obj, dict):
            data.update(obj)
    texts = {}
    for k, v in data.items():
        if isinstance(v, dict):
            v = v.get(lang) or next((x for n, x in v.items() if n not in ("en", "fr") and isinstance(x, str)), None)
        if isinstance(v, str):
            texts[k] = v
    return texts


def translate_batch(lang: str, batch: dict[str, dict[str, str]]) -> tuple[dict[str, str], dict[str, str]]:
    """(the good translations, key -> why it was refused) after one retry of what failed."""
    good, bad, todo = {}, {}, dict(batch)
    for _ in range(2):
        if not todo:
            break
        try:
            got = claude(lang, todo)
        except Exception as e:
            bad = {k: f"no answer ({str(e)[:80]})" for k in todo}
            continue
        bad = {}
        for k, src in todo.items():
            out = got.get(k)
            if not out or not out.strip():
                bad[k] = "no translation"
            elif (p := chk.shape_problems(src["en"], out, k.endswith("#one"))):
                bad[k] = ", ".join(p)
            else:
                good[k] = out
        todo = {k: batch[k] for k in bad}
    return good, bad


def load_state(en: dict[str, str]) -> dict:
    """{"source": {key: fingerprint of the English text the translations were made from}, "late": {lang: [keys whose
    translation is not made from that text]}}, brought in line with the current en.ts: a new or changed English text
    becomes late in every language, a key gone from en.ts is forgotten."""
    st = json.loads(chk.STATE.read_text()) if chk.STATE.exists() else {"source": {}, "late": {}}
    changed = [k for k, text in en.items() if st["source"].get(k) != chk.sha(text)]
    for lang in LANGS:
        late = set(st["late"].get(lang, en)) | set(changed)
        st["late"][lang] = [k for k in en if k in late]
    st["source"] = {k: chk.sha(text) for k, text in en.items()}
    return st


def save_state(st: dict) -> None:
    chk.STATE.write_text(json.dumps(st, indent=0, sort_keys=True, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--langs", default=",".join(LANGS))
    ap.add_argument("--jobs", type=int, default=3, help="translations run at the same time")
    ap.add_argument("--batch", type=int, default=60, help="texts per request")
    ap.add_argument("--only", help="only the keys starting with this (e.g. settings)")
    ap.add_argument("--dry-run", action="store_true", help="say what would be translated, change nothing")
    ap.add_argument("--accept", action="store_true",
                    help="record the texts written by hand in <lang>.ts (different from English, same shape) as done")
    a = ap.parse_args()
    langs = [l for l in a.langs.split(",") if l in LANGS]
    have = [l for l in LANGS if (chk.I18N / f"{l}.ts").exists()]
    dicts = chk.dictionaries(["en", "fr", *have])
    en, fr = dicts["en"], dicts["fr"]
    order = list(en)
    st = load_state(en)
    failed = 0
    for lang in langs:
        cur = {k: v for k, v in dicts.get(lang, {}).items() if k in en}
        late = set(st["late"][lang]) | {k for k in order if k not in cur}
        todo = [k for k in order if k in late and (not a.only or k.startswith(a.only))]

        def save():
            write_dict(lang, {k: cur.get(k, en[k]) for k in order}, order)
            st["late"][lang] = [k for k in order if k in late]
            save_state(st)

        if a.accept:
            ok = [k for k in todo if k in cur and cur[k] != en[k] and not chk.shape_problems(en[k], cur[k], k.endswith("#one"))]
            late -= set(ok)
            save()
            print(f"{lang}: {len(ok)} text(s) written by hand recorded, {len(todo) - len(ok)} still to translate")
            continue
        print(f"{lang}: {len(todo)} text(s) to translate out of {len(order)}", flush=True)
        if a.dry_run:
            continue
        if not todo:
            save()                                         # keys gone from en.ts leave the dictionary
            continue
        batches = [{k: {"en": en[k], "fr": fr.get(k, "")} for k in todo[i:i + a.batch]} for i in range(0, len(todo), a.batch)]
        done = 0
        with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
            for good, bad in ex.map(lambda b: translate_batch(lang, b), batches):
                cur.update(good)
                late -= set(good)
                for k, why in bad.items():
                    failed += 1
                    print(f"  {lang}: {k}: {why}", flush=True)
                done += 1
                save()                                     # a stopped run keeps what is done
                print(f"  {lang}: {done}/{len(batches)} request(s)", flush=True)
    if not a.dry_run:
        save_state(st)
    if failed:
        print(f"{failed} text(s) left in English: run the script again, or translate them by hand then --accept")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
