from __future__ import annotations

from maxxing import config


def _skill(root, name, head):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(head + "\n# Body\n", encoding="utf-8")


def test_skills_are_listed_by_origin_read_only(client, mx, monkeypatch):
    cdir = mx["tmp"] / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cdir))
    config.save_config({**config.load_config(), "claude_dir": str(cdir)})
    _skill(cdir / "skills", "memory", "---\nname: memory\ndescription: Update the right memory.md\n---")
    _skill(cdir / "skills", "mine", "---\nname: mine\ndescription: >-\n  Folded\n  text\ndisable-model-invocation: true\n---")
    ws = mx["ws"]
    _skill(ws / ".claude/skills", "ws-skill", '---\nname: ws-skill\ndescription: "Quoted: yes"\n---')
    _skill(ws / "projects/acme/.claude/skills", "shop", "---\nname: shop\ndescription: Shop things\n---")
    _skill(ws / "projects/acme/topics/blog/.claude/skills", "post", "no front matter")
    (ws / "projects/acme/.claude/skills/empty").mkdir()               # no SKILL.md: not a skill
    before = {p: p.read_text() for p in (cdir / "skills").rglob("SKILL.md")}
    out = {s["folder"]: s for s in client.get("/api/skills").json()["skills"]}
    assert set(out) == {"memory", "mine", "ws-skill", "shop", "post"}
    assert out["memory"]["origin"] == "product" and out["memory"]["description"] == "Update the right memory.md"
    assert out["mine"]["origin"] == "user" and out["mine"]["description"] == "Folded text" and out["mine"]["hidden"]
    assert out["ws-skill"]["origin"] == "workspace" and out["ws-skill"]["description"] == "Quoted: yes"
    assert out["shop"] == {**out["shop"], "origin": "project", "project": "acme"}
    assert out["post"]["origin"] == "topic" and out["post"]["topic"] == "blog" and out["post"]["name"] == "post"
    assert out["post"]["path"].endswith("projects/acme/topics/blog/.claude/skills/post/SKILL.md")
    assert {p: p.read_text() for p in (cdir / "skills").rglob("SKILL.md")} == before
