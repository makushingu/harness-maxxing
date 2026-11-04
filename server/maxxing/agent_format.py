"""Claude Code's subagent format (`.claude/agents/<name>.md`) for Harness agents.

    ---
    name: writer
    description: Writes the weekly post
    tools: Read, Grep, Edit(./drafts/**)
    model: sonnet
    permissionMode: acceptEdits
    ---
    The role (system prompt)...

`export_md` writes an agent in that format (its role = the body), `parse_md` reads one (fields Harness has no
equivalent for - mcpServers, hooks, memory, skills... - are listed in `ignored`), and `subagents` gives the
`--agents` JSON that makes the agents of a topic (option `subagent`) callable from the topic's own sessions.
"""
from __future__ import annotations

import json
import re

from . import agents, config

MODES_OUT = {"bypass": "bypassPermissions", "acceptEdits": "acceptEdits", "default": "default"}
MODES_IN = {"bypassPermissions": "bypass", "acceptEdits": "acceptEdits", "default": "default",
            "plan": "default", "dontAsk": "default", "auto": "default", "manual": "default"}
KNOWN = {"name", "description", "tools", "disallowedTools", "model", "permissionMode"}
MD_MAX = 64_000


def _role(path: str) -> str:
    """The agent's CLAUDE.md without its heading nor the `@memory.md` import."""
    try:
        lines = (agents.folder(path) / "CLAUDE.md").read_text(errors="replace").splitlines()
    except OSError:
        return ""
    start = next((i + 1 for i, ln in enumerate(lines) if ln.startswith("# ")), 0)
    return "\n".join(ln for ln in lines[start:] if ln.strip() != "@memory.md").strip()


def _one_line(text: str, limit: int = 300) -> str:
    first = next((p for p in re.split(r"\n\s*\n", text or "") if p.strip()), "")
    return " ".join(first.split())[:limit]


def _yaml_str(v: str) -> str:
    """A YAML plain scalar when it is one ("Bash(git log:*)"), else a JSON (= YAML) quoted string."""
    plain = not re.search(r": |\s#|:$|^[\s\-?:,\[\]{}#&*!|>'\"%@`]|\s$|\n", v)
    return v if plain and v else json.dumps(v, ensure_ascii=False)


def export_md(path: str) -> str:
    a = agents.load(path)
    name = agents.parse(path)[2]
    role = _role(path)
    head = {"name": name, "description": _one_line(role) or a["name"] or name}
    if a["allowed_tools"]:
        head["tools"] = ", ".join(a["allowed_tools"])
    if a["disallowed_tools"]:
        head["disallowedTools"] = ", ".join(a["disallowed_tools"])
    if a["model"]:
        head["model"] = a["model"]
    if a["permission_mode"]:
        head["permissionMode"] = MODES_OUT[a["permission_mode"]]
    front = "\n".join(f"{k}: {_yaml_str(str(v))}" for k, v in head.items())
    return f"---\n{front}\n---\n\n{role}\n"


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        try:
            return str(json.loads(v))
        except ValueError:
            return v[1:-1]
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def parse_md(text: str) -> dict:
    """{name, description, fields, ignored} of a Claude Code subagent file. ValueError when it is not one."""
    if len(text or "") > MD_MAX:
        raise ValueError("File too big for an agent")
    m = re.match(r"\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", text or "", re.S)
    if not m:
        raise ValueError("Not a Claude Code agent file: it starts with a --- block (name, description...)")
    head: dict[str, object] = {}
    key = None
    for ln in m.group(1).splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s*(.*)$", ln)
        if item and key:                                # a YAML list under the last key
            cur = head.get(key)
            head[key] = (cur if isinstance(cur, list) else []) + [_unquote(item.group(1))]
            continue
        kv = re.match(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*)$", ln)
        if not kv:
            key = None
            continue
        key, val = kv.group(1), kv.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            head[key] = [_unquote(x) for x in val[1:-1].split(",") if x.strip()]
        else:
            head[key] = _unquote(val) if val else []
    name = str(head.get("name") or "").strip()
    if not name:
        raise ValueError("The agent file has no name")
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:48] or "agent"

    def tools(v: object) -> list[str]:
        items = v if isinstance(v, list) else re.split(r",(?![^(]*\))", str(v or ""))
        return [str(t).strip() for t in items if str(t).strip()]

    body = m.group(2).strip()
    desc = str(head.get("description") or "").strip()
    fields: dict = {"name": name[:60]}
    if head.get("tools"):
        fields["allowed_tools"] = tools(head["tools"])
    if head.get("disallowedTools"):
        fields["disallowed_tools"] = tools(head["disallowedTools"])
    model = str(head.get("model") or "").strip()
    if model and model != "inherit":
        fields["model"] = model
    mode = str(head.get("permissionMode") or "").strip()
    if mode in MODES_IN:
        fields["permission_mode"] = MODES_IN[mode]
    role = body if not desc or desc in body else f"{desc}\n\n{body}".strip()
    return {"name": slug, "description": role or desc, "fields": fields,
            "ignored": sorted(k for k in head if k not in KNOWN)}


def import_md(topic_path: str, text: str, name: str | None = None) -> dict:
    """Create an agent in a topic from a Claude Code agent file (switched on, sandboxed, no trigger)."""
    p = parse_md(text)
    created = agents.create(topic_path, name or p["name"], {**p["fields"], "description": p["description"]})
    return {**created, "ignored": p["ignored"]}


# ---- the agents of a topic as subagents of its sessions --------------------------------------------
def subagents(topic_path: str) -> dict:
    """{name: {description, prompt, tools?, model?}} for `--agents`: the agents of this topic with `subagent` on.
    A subagent runs inside the session that calls it (its permissions, its budget), not as a run of the agent."""
    m = re.fullmatch(r"projects/([a-z0-9][a-z0-9-]{0,47})/topics/([a-z0-9][a-z0-9-]{0,47})", (topic_path or "").strip("/"))
    if not m:
        return {}
    out: dict = {}
    for n in agents.names(m.group(1), m.group(2)):
        path = agents.agent_path(m.group(1), m.group(2), n)
        a = agents.load(path)
        if not (a["subagent"] and a["enabled"]):
            continue
        role, folder = _role(path), config.workspace() / path
        d: dict = {"description": f"{a['name'] or n}: {_one_line(role, 400) or 'agent of this topic'}",
                   "prompt": f"{role}\n\nYour folder: {folder}. Read {folder}/memory.md first. Write there only "
                             "what will change how you work next time (a rule from the user, a trap, a lasting "
                             "fact), as a short dated bullet; never a log of the task: most tasks add nothing."}
        if a["allowed_tools"]:
            d["tools"] = a["allowed_tools"]
        if a["model"]:
            d["model"] = a["model"]
        out[n] = d
    return out


def subagents_args(topic_path: str) -> list[str]:
    s = subagents(topic_path)
    return ["--agents", json.dumps(s, separators=(",", ":"), ensure_ascii=False)] if s else []
