from __future__ import annotations

import pytest

from maxxing import config, skills


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
    _skill(ws / "projects/acme/topics/news/.claude/skills", "other", "---\nname: other\n---")
    _skill(ws / "projects/zeta/.claude/skills", "z", "---\nname: z\n---")
    seen = {s["folder"] for s in client.get("/api/skills", params={"path": "projects/acme/topics/blog"}).json()["skills"]}
    assert seen == {"memory", "mine", "ws-skill", "shop", "post"}                  # not acme/news nor zeta


@pytest.mark.parametrize("header", ["|", "|-", "|+", ">", ">-", ">+"])
def test_a_block_scalar_description_loses_its_header(header):
    text = f"---\nname: x\ndescription: {header}\n  Line one\n  line two\ndisable-model-invocation: true\n---\nBody\n"
    assert skills._front(text)["description"] == "Line one line two"


def test_folders_with_a_name_that_is_not_utf8_are_left_out(client, mx, monkeypatch):
    import os
    cdir = mx["tmp"] / "claude"                          # never the skills of the machine running the tests
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cdir))
    config.save_config({**config.load_config(), "claude_dir": str(cdir)})
    ws = mx["ws"]
    _skill(ws / ".claude/skills", "fine", "---\nname: fine\n---")
    _skill(ws / ".claude/skills", os.fsdecode(b"s\xff"), "---\nname: bad\n---")
    _skill(ws / "projects" / os.fsdecode(b"p\xff") / ".claude/skills", "s", "---\nname: s\n---")
    _skill(ws / "projects/acme/topics" / os.fsdecode(b"t\xff") / ".claude/skills", "t", "---\nname: t\n---")
    r = client.get("/api/skills")
    assert r.status_code == 200
    assert {s["folder"] for s in r.json()["skills"] if s["origin"] != "product"} == {"fine"}


def test_front_matter_is_split_on_newlines_only():
    from maxxing import skills
    out = skills._front("---\nname: x\ndescription: hello\u2028disable-model-invocation: true\n---\n")
    assert list(out) == ["name", "description"]


def test_a_skill_file_that_is_a_link_is_not_read(client, mx):
    """SKILL.md -> any file starting with `---`: its name:/description: lines came out of GET /api/skills."""
    secret = mx["tmp"] / "secret.txt"
    secret.write_text("---\nname: leak\ndescription: TOPSECRET line\n---\n")
    folder = mx["ws"] / ".claude/skills/linked"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").symlink_to(secret)
    assert "linked" not in {s["folder"] for s in client.get("/api/skills").json()["skills"]}


def test_a_topic_menu_opens_only_the_skills_it_can_use(mx, monkeypatch):
    """for_topic listed every skill of every topic of the server, then dropped the other topics' ones."""
    from pathlib import Path
    from maxxing import skills
    ws = mx["ws"]
    for t in ("t0", "t1", "t2"):
        _skill(ws / f"projects/p0/topics/{t}/.claude/skills", f"s-{t}", "---\nname: s\n---")
        _skill(ws / f"projects/p1/topics/{t}/.claude/skills", f"x-{t}", "---\nname: x\n---")
    _skill(ws / ".claude/skills", "w", "---\nname: w\n---")
    opened: list[str] = []
    real = Path.open
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: (opened.append(str(self)), real(self, *a, **k))[1])
    got = {s["folder"] for s in skills.for_topic("projects/p0/topics/t1")}
    assert "s-t1" in got and "w" in got and not got & {"s-t0", "s-t2", "x-t1"}
    assert not [o for o in opened if "/p1/" in o or "/t0/" in o or "/t2/" in o], opened
