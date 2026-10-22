from __future__ import annotations

import json
import re
from pathlib import Path

from maxxing import config, crons, packs, workspace

ALL = ["ecommerce", "affiliate", "creator", "apps", "second-brain", "freelance"]
# the icon names the UI knows (web/src/components/ui/icon.tsx; an unknown one would show a puzzle piece)
ICON_NAMES = set(re.findall(r"'?([a-z0-9-]+)'?: [A-Z]\w*[,\n]",
                            (Path(__file__).resolve().parents[2] / "web/src/components/ui/icon.tsx").read_text()))


def test_every_pack_is_complete():
    ids = [p.name for p in packs.packs_dir().iterdir() if p.is_dir()]
    assert sorted(ids) == sorted(ALL)
    for pid in ALL:
        data = json.loads((packs.packs_dir() / pid / "pack.json").read_text())
        assert data["id"] == pid and data["emoji"] and data["title"]["en"] and data["title"]["fr"]
        assert data["icon"] in ICON_NAMES, (pid, data.get("icon"))           # the UI shows an icon, not the emoji
        assert len(data["description"]["en"]) <= 120 and data["description"]["fr"]
        root = packs.packs_dir() / pid / "project"
        assert (root / "CLAUDE.md").is_file() and (root / "memory.md").is_file()
        for t in data["topics"]:
            for f in ("CLAUDE.md", "memory.md"):
                assert (root / "topics" / t / f).is_file(), (pid, t, f)
            assert (root / "topics" / t / "CLAUDE.md").read_text().startswith(f"# Topic {t}\n")
        assert sorted(p.name for p in (root / "topics").iterdir()) == sorted(data["topics"])
        for c in data.get("crons", []):
            assert c["topic"] in data["topics"] and c["prompt"] and crons.validate(c["schedule"])


def test_list_install_never_overwrites(client, mx):
    lst = client.get("/api/packs").json()["packs"]
    assert [p["id"] for p in lst] == ["basics"] + ALL and not any(p["project_exists"] for p in lst[1:])
    r = client.post("/api/packs/ecommerce/install").json()
    assert r["ok"] and r["created_files"] > 8 and r["project"] == "ecommerce"
    ws = workspace.root()
    assert (ws / "projects/ecommerce/topics/orders/CLAUDE.md").is_file()
    assert workspace.project_emoji("ecommerce") == "🛒"
    for f in (ws / "projects/ecommerce").rglob("*.md"):
        assert "{{" not in f.read_text(), f
    # the pack's jobs exist, disabled
    jobs = [j for j in crons.list_jobs() if j["topic_path"].startswith("projects/ecommerce/")]
    assert jobs and not any(j["enabled"] for j in jobs) and sorted(j["name"] for j in jobs) == sorted(r["jobs"])
    # adding it again = a second project; the first one is left as it is
    mine = ws / "projects/ecommerce/topics/orders/CLAUDE.md"
    mine.write_text("# Topic orders\n\nmine\n")
    r2 = client.post("/api/packs/ecommerce/install").json()
    assert r2["project"] == "ecommerce-2" and mine.read_text() == "# Topic orders\n\nmine\n"
    assert (ws / "projects/ecommerce-2/CLAUDE.md").read_text().startswith("# Project ecommerce-2\n")
    assert (ws / "projects/ecommerce-2/memory.md").read_text().startswith("# Project ecommerce-2 - memory")
    assert workspace.project_emoji("ecommerce-2") == "🛒"
    jobs2 = [j for j in crons.list_jobs() if j["topic_path"].startswith("projects/ecommerce-2/")]
    assert len(jobs2) == len(jobs) and all(j["name"].endswith(" (ecommerce-2)") for j in jobs2)
    assert client.post("/api/packs/ecommerce/install").json()["project"] == "ecommerce-3"
    assert client.post("/api/packs/nope/install").status_code == 404
    assert client.post("/api/packs/..%2Fetc/install").status_code in (404, 422)


def test_basics_puts_back_the_default_projects(client, mx):
    import shutil
    ws = workspace.root()
    client.post("/api/packs/basics/install")
    basics = client.get("/api/packs").json()["packs"][0]
    assert basics["basics"] and basics["installed"] and "general/inbox" in basics["topics"]
    mine = ws / "projects/general/topics/inbox/memory.md"
    mine.write_text("mine\n")
    shutil.rmtree(ws / "projects/system")
    assert not client.get("/api/packs").json()["packs"][0]["installed"]
    r = client.post("/api/packs/basics/install").json()
    assert r["created_files"] > 0 and r["jobs"] == [] and r["pack"]["installed"]
    assert (ws / "projects/system/topics/help/CLAUDE.md").is_file() and mine.read_text() == "mine\n"


def test_existing_project_keeps_its_emoji(client, mx):
    workspace.create_project("freelance", "mine")
    workspace.set_project_emoji("freelance", "🦊")
    assert client.post("/api/packs/freelance/install").json()["project"] == "freelance-2"
    assert workspace.project_emoji("freelance") == "🦊"
    assert (workspace.root() / "projects/freelance/CLAUDE.md").read_text().startswith("# Project freelance\n\nmine")


def test_cli_packs(mx, capsys):
    from maxxing import cli
    assert cli.main(["packs", "list"]) == 0
    assert "second-brain" in capsys.readouterr().out
    assert cli.main(["packs", "add", "creator", "apps"]) == 0
    out = capsys.readouterr().out
    assert "projects/creator" in out and "projects/apps" in out
    assert (workspace.root() / "projects/apps/topics/app-3/CLAUDE.md").is_file()
    assert cli.main(["packs", "add", "nope"]) == 2


def test_basics_never_writes_through_a_link(client, mx, tmp_path):
    # a missing file that is a dangling link, or a topic folder linked outside the workspace: nothing written there
    ws = workspace.root()
    client.post("/api/packs/basics/install")
    outside = tmp_path / "outside"
    outside.mkdir()
    md = ws / "projects/general/topics/inbox/CLAUDE.md"
    md.unlink()
    md.symlink_to(outside / "planted.md")
    help_dir = ws / "projects/system/topics/help"
    import shutil
    shutil.rmtree(help_dir)
    help_dir.symlink_to(outside, target_is_directory=True)
    client.post("/api/packs/basics/install")
    assert list(outside.iterdir()) == [] and md.is_symlink()


def test_parallel_installs_get_distinct_projects_and_job_names(mx):
    import threading
    res, bar = [], threading.Barrier(6)

    def go():
        bar.wait()
        res.append(packs.install("ecommerce"))
    threads = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    projects = [r["project"] for r in res]
    names = [j["name"] for j in crons.list_jobs()]
    assert len(projects) == 6 and len(set(projects)) == 6
    assert len(set(names)) == len(names)
