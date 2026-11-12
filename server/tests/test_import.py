"""Import from another agent: prompt, upload + preview, apply (create / merge / never overwrite), safety."""
from __future__ import annotations

import io
import zipfile

from maxxing import importer

FAKE_KEY = "sk-ant-api03-" + "x" * 40


def _zip(files: dict[str, str | bytes], top: str = "harness-maxxing-export/") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(top + name, data)
    return buf.getvalue()


def _upload(client, data: bytes):
    return client.post("/api/import/upload", files={"file": ("export.zip", data, "application/zip")})


EXPORT = {
    "memory.md": "# Me\n\n- Prefers short answers\n",
    "projects/Coffee Shop/CLAUDE.md": "# Coffee shop\n\nOnline coffee store.\n",
    "projects/Coffee Shop/memory.md": "- 2026-05-02: switched to Stripe\n",
    "projects/Coffee Shop/topics/blog/CLAUDE.md": "# Blog\n\nOne article a week.\n",
    "projects/Coffee Shop/topics/blog/memory.md": "- Next article: cold brew\n",
    "projects/Coffee Shop/topics/blog/plan.md": "1. cold brew\n",
    "projects/acme/topics/seo/memory.md": "- Target: coffee beans\n",
    "skills/blog-article/SKILL.md": "---\nname: blog-article\ndescription: Write a blog article.\n---\n",
    "tasks.md": "- order beans\n",
    "crons.md": "- 0 9 * * 1 weekly report\n",
    "SECRETS.md": "- STRIPE_KEY: payments\n",
    "__MACOSX/._junk": "x",
}


def test_prompt(client):
    r = client.get("/api/import/prompt", params={"agent": "hermes"}).json()
    assert r["agent"] == "hermes" and set(r["agents"]) == {"hermes", "claude-code", "openclaw", "other"}
    assert "~/.hermes/" in r["prompt"] and "projects/<project>/topics/<topic>/memory.md" in r["prompt"]
    assert "NEVER write a secret value" in r["prompt"]
    # where Hermes really keeps things, and what a good export needs whatever the agent
    assert all(x in r["prompt"] for x in ("memories/MEMORY.md", "SOUL.md", "hermes cron list", "Never copy .env"))
    assert "in the language I use with you" in r["prompt"] and "python3 -m zipfile -c" in r["prompt"]
    claw = client.get("/api/import/prompt", params={"agent": "openclaw"}).json()["prompt"]
    assert all(x in claw for x in ("TOOLS.md", "openclaw cron list", "Never copy openclaw.json"))
    assert client.get("/api/import/prompt", params={"agent": "nope"}).json()["agent"] == "other"


def test_preview_then_import_into_an_existing_workspace(client, mx):
    client.post("/api/workspace/projects", json={"name": "acme"})
    client.post("/api/workspace/projects/acme/topics", json={"name": "seo"})
    seo_mem = mx["ws"] / "projects/acme/topics/seo/memory.md"
    seo_mem.write_text("# Topic seo - memory\n\n- existing fact\n")
    (mx["ws"] / ".claude/skills/blog-article").mkdir(parents=True)
    (mx["ws"] / ".claude/skills/blog-article/SKILL.md").write_text("mine")
    r = _upload(client, _zip(EXPORT))
    assert r.status_code == 200, r.text
    p = r.json()
    names = {pr["name"]: pr for pr in p["projects"]}
    assert set(names) == {"coffee-shop", "acme"} and names["acme"]["exists"] and not names["coffee-shop"]["exists"]
    assert [t["name"] for t in names["coffee-shop"]["topics"]] == ["blog"]
    assert names["acme"]["topics"][0]["exists"] is True
    assert {"from": "Coffee Shop", "to": "coffee-shop"} in p["renamed"]
    assert p["skills"] == ["blog-article"] and sorted(p["aside"]) == ["SECRETS.md", "crons.md", "tasks.md"]
    assert p["root_memory"] and not p["secrets"]
    assert not (mx["ws"] / "projects/coffee-shop").exists()          # preview writes nothing
    res = client.post(f"/api/import/{p['id']}/apply").json()
    assert res["ok"] and res["projects"] == ["coffee-shop"] and res["topics"] == ["coffee-shop/blog"]
    ws = mx["ws"]
    blog = ws / "projects/coffee-shop/topics/blog"
    assert "One article a week." in (blog / "CLAUDE.md").read_text() and "@memory.md" in (blog / "CLAUDE.md").read_text()
    assert "cold brew" in (blog / "memory.md").read_text() and (blog / "plan.md").read_text() == "1. cold brew\n"
    # existing memory: appended, never replaced
    body = seo_mem.read_text()
    assert "- existing fact" in body and "## Imported (" in body and "- Target: coffee beans" in body
    assert "Prefers short answers" in (ws / "memory.md").read_text()
    # an existing skill is kept, the imported one lands next to it
    assert (ws / ".claude/skills/blog-article/SKILL.md").read_text() == "mine"
    assert (ws / ".claude/skills/blog-article-imported/SKILL.md").exists() and res["skills"] == ["blog-article-imported"]
    # aside files + report, and the prompt to finish with Claude
    folder = ws / res["folder"]
    assert (folder / "tasks.md").exists() and (folder / "IMPORT_REPORT.md").exists()
    assert "tasks.json" in res["finish_prompt"] and res["report"] in res["finish_prompt"]
    tree = client.get("/api/workspace/tree").json()
    assert "projects/coffee-shop/topics/blog" in [t["path"] for pr in tree["projects"] for t in pr["topics"]]
    # the upload is consumed
    assert client.post(f"/api/import/{p['id']}/apply").status_code == 404


def test_existing_files_are_never_overwritten(client, mx):
    client.post("/api/workspace/projects", json={"name": "acme"})
    client.post("/api/workspace/projects/acme/topics", json={"name": "blog"})
    plan = mx["ws"] / "projects/acme/topics/blog/plan.md"
    plan.write_text("mine")
    p = _upload(client, _zip({"projects/acme/topics/blog/plan.md": "theirs"}, top="")).json()
    res = client.post(f"/api/import/{p['id']}/apply").json()
    assert plan.read_text() == "mine"
    assert (mx["ws"] / "projects/acme/topics/blog/plan (imported).md").read_text() == "theirs"
    assert res["renamed"][0]["to"].endswith("plan (imported).md")


def test_secrets_and_unsafe_entries_are_refused(client, mx):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("projects/acme/topics/blog/memory.md", "- fine\n")
        z.writestr("projects/acme/topics/blog/.env", f"ANTHROPIC_API_KEY={FAKE_KEY}\n")
        z.writestr("SECRETS.md", f"- ANTHROPIC: {FAKE_KEY}\n")
        z.writestr("../../etc/evil", "x")
    p = _upload(client, buf.getvalue()).json()
    assert {s["file"] for s in p["secrets"]} == {"projects/acme/topics/blog/.env", "SECRETS.md"}
    assert any(s["reason"] == "unsafe path" for s in p["skipped"])
    res = client.post(f"/api/import/{p['id']}/apply").json()
    assert not (mx["ws"] / "projects/acme/topics/blog/.env").exists()
    assert FAKE_KEY not in (mx["ws"] / res["report"]).read_text()
    assert not (mx["tmp"] / "etc").exists()


def test_bad_uploads(client):
    assert _upload(client, b"not a zip").json()["error"] == "bad_zip"
    assert _upload(client, _zip({"random/file.txt": "x"}, top="")).status_code == 200      # kept aside
    assert _upload(client, _zip({}, top="")).json()["error"] == "empty"
    assert client.post("/api/import/0123456789abcdef/apply").status_code == 404
    assert client.post("/api/import/bad/apply").status_code == 400


def test_names_that_give_the_same_folder_stay_apart(client, mx):
    """"Блог" and "Продажи" both slug to "imported" (and "My Blog" / "my-blog" to "my-blog"): never merged."""
    p = _upload(client, _zip({"projects/Блог/CLAUDE.md": "# Blog\n\nRules A\n",
                              "projects/Продажи/CLAUDE.md": "# Sales\n\nRules B\n",
                              "projects/acme/topics/My Blog/memory.md": "- one\n",
                              "projects/acme/topics/my-blog/memory.md": "- two\n"}, top="")).json()
    assert [x["name"] for x in p["projects"]] == ["acme", "imported", "imported-2"]
    assert [t["name"] for t in p["projects"][0]["topics"]] == ["my-blog", "my-blog-2"]
    assert {r["from"] for r in p["renamed"]} == {"Блог", "Продажи", "acme/My Blog", "acme/my-blog"}   # all shown
    client.post(f"/api/import/{p['id']}/apply")
    assert "Rules A" in (mx["ws"] / "projects/imported/CLAUDE.md").read_text()
    assert "Rules B" in (mx["ws"] / "projects/imported-2/CLAUDE.md").read_text()
    assert "two" in (mx["ws"] / "projects/acme/topics/my-blog-2/memory.md").read_text()


def test_a_renamed_folder_never_lands_in_an_unrelated_existing_one(client, mx):
    (mx["ws"] / "projects/my-blog-2").mkdir(parents=True)
    (mx["ws"] / "projects/my-blog-2/CLAUDE.md").write_text("# Mine\n")
    p = _upload(client, _zip({"projects/My Blog/CLAUDE.md": "# A\n\nRules A\n",
                              "projects/my-blog/CLAUDE.md": "# B\n\nRules B\n"}, top="")).json()
    assert [x["name"] for x in p["projects"]] == ["my-blog", "my-blog-3"]
    client.post(f"/api/import/{p['id']}/apply")
    assert (mx["ws"] / "projects/my-blog-2/CLAUDE.md").read_text() == "# Mine\n"
    assert "Rules B" in (mx["ws"] / "projects/my-blog-3/CLAUDE.md").read_text()


def test_skills_that_give_the_same_folder_stay_apart(client, mx):
    p = _upload(client, _zip({"skills/My Skill/SKILL.md": "---\nname: a\n---\nA\n",
                              "skills/my-skill/SKILL.md": "---\nname: b\n---\nB\n",
                              "skills/my-skill/x.md": "b file\n"}, top="")).json()
    client.post(f"/api/import/{p['id']}/apply")
    sk = mx["ws"] / ".claude/skills"
    assert sorted(f.name for f in (sk / "my-skill").iterdir()) == ["SKILL.md"]
    assert sorted(f.name for f in (sk / "my-skill-2").iterdir()) == ["SKILL.md", "x.md"]
    assert {(sk / d / "SKILL.md").read_text()[-2] for d in ("my-skill", "my-skill-2")} == {"A", "B"}


def test_an_export_zipped_from_higher_up_is_still_read(client, mx):
    """The old agent zipped the parent folder ("out/harness-maxxing-export/..."): same import, not everything aside."""
    p = _upload(client, _zip({"projects/shop/topics/seo/memory.md": "- fact\n", "memory.md": "- me\n",
                              "tasks.md": "- call\n"}, top="out/harness-maxxing-export/")).json()
    assert [x["name"] for x in p["projects"]] == ["shop"] and p["root_memory"] and p["aside"] == ["tasks.md"]


def test_skills_sorted_in_categories(client, mx):
    """Hermes keeps skills/<category>/<name>/SKILL.md: the skill is the folder that holds SKILL.md."""
    p = _upload(client, _zip({"skills/ecommerce/DESCRIPTION.md": "about the category\n",
                              "skills/ecommerce/weekly-report/SKILL.md": "---\nname: weekly-report\n---\nA\n",
                              "skills/ecommerce/weekly-report/scripts/run.py": "print(1)\n",
                              "skills/devops/weekly-report/SKILL.md": "---\nname: weekly-report\n---\nB\n",
                              "skills/plain/SKILL.md": "---\nname: plain\n---\nC\n",
                              "skills/plain/docs/SKILL.md": "an example\n",
                              "skills/notes/how.md": "no SKILL.md here\n"})).json()
    assert p["skills"] == ["notes", "plain", "weekly-report", "weekly-report-2"]
    assert p["aside"] == ["skills/ecommerce/DESCRIPTION.md"]
    client.post(f"/api/import/{p['id']}/apply")
    sk = mx["ws"] / ".claude/skills"
    assert sorted(d.name for d in sk.iterdir()) == ["notes", "plain", "weekly-report", "weekly-report-2"]
    assert {(sk / d / "SKILL.md").read_text()[-2] for d in ("weekly-report", "weekly-report-2")} == {"A", "B"}
    both = [sk / d / "scripts/run.py" for d in ("weekly-report", "weekly-report-2")]
    assert sum(f.is_file() for f in both) == 1 and (sk / "plain/docs/SKILL.md").is_file()


def test_a_raw_hermes_memory_folder_is_the_root_memory(client, mx):
    p = _upload(client, _zip({"memories/MEMORY.md": "- runs a shop\n", "memories/USER.md": "- likes short answers\n",
                              "memories/old/MEMORY.md": "- elsewhere\n", "SOUL.md": "calm\n"}, top="")).json()
    assert p["root_memory"] and p["aside"] == ["SOUL.md", "memories/old/MEMORY.md"]
    client.post(f"/api/import/{p['id']}/apply")
    mem = (mx["ws"] / "memory.md").read_text()
    assert "runs a shop" in mem and "likes short answers" in mem and "elsewhere" not in mem


def test_a_new_folder_keeps_a_description_without_a_heading(client, mx):
    """An imported CLAUDE.md with no "# " heading: the generated one stays, so the app has a description to show."""
    from maxxing import workspace
    p = _upload(client, _zip({"projects/shop/CLAUDE.md": "Online shop of the bakery.\n",
                              "projects/shop/topics/seo/CLAUDE.md": "# SEO\n\nRank the shop.\n\n@memory.md\n",
                              "projects/shop/topics/blog/CLAUDE.md": "Two posts a week.\n"})).json()
    client.post(f"/api/import/{p['id']}/apply")
    shop = mx["ws"] / "projects/shop"
    assert (shop / "CLAUDE.md").read_text() == "# Project shop\n\nOnline shop of the bakery.\n\n@memory.md\n"
    assert (shop / "topics/seo/CLAUDE.md").read_text() == "# SEO\n\nRank the shop.\n\n@memory.md\n"
    assert workspace._parse_description(shop / "CLAUDE.md") == "Online shop of the bakery."
    assert workspace._parse_description(shop / "topics/blog/CLAUDE.md") == "Two posts a week."


def test_slug():
    assert importer.slug("Café Crème !") == "cafe-creme" and importer.slug("***") == "imported"


def test_cli(mx, tmp_path, capsys):
    from maxxing import cli, commands  # noqa: F401 - registers the commands
    z = tmp_path / "export.zip"
    z.write_bytes(_zip({"projects/acme/topics/blog/memory.md": "- fact\n"}))
    assert cli.main(["import", "--prompt", "openclaw"]) == 0 and "~/.openclaw/workspace/" in capsys.readouterr().out
    assert cli.main(["import", str(z), "--dry-run"]) == 0 and "new    acme: +blog" in capsys.readouterr().out
    assert not (mx["ws"] / "projects/acme").exists()
    assert cli.main(["import", str(z)]) == 0
    out = capsys.readouterr().out
    assert "Imported: 1 new projects" in out
    assert "Last step: open a session in general/inbox" in out and "IMPORT_REPORT.md first" in out   # how to finish
    assert (mx["ws"] / "projects/acme/topics/blog/memory.md").read_text().strip().endswith("- fact")


def test_video_project_and_tools_status(mx, tmp_path, capsys):
    from maxxing import cli, cmd_core, cmd_video, commands  # noqa: F401
    assert cli.main(["video", "status"]) == 1 and "maxxing deps update" in capsys.readouterr().out
    assert cmd_core.check_tools()["level"] == cmd_core.WARN
    shared = cmd_video.tools_dir() / "node_modules" / "remotion"
    shared.mkdir(parents=True)
    dest = tmp_path / "videos" / "launch"
    assert cli.main(["video", "new", str(dest)]) == 0
    assert (dest / "src" / "Root.jsx").exists() and (dest / "package.json").exists()
    assert (dest / "node_modules").is_symlink() and (dest / "node_modules").resolve() == shared.parent.resolve()
    try:
        cli.main(["video", "new", str(dest)])
        raise AssertionError("an existing project must be refused")
    except SystemExit as e:
        assert "not empty" in str(e)
