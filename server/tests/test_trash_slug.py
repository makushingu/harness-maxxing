"""Restoring a project or topic next to one of the same name keeps a valid name, even for the longest names."""
from __future__ import annotations


def test_a_restored_project_with_a_48_character_name_stays_visible(client, mx):
    """A project named with the full 48 characters, deleted, then created again: the restored copy became
    `<48 chars>-restored`, not a valid project name, so it was invisible in the sidebar."""
    name = "a" * 47 + "b"
    assert client.post("/api/workspace/projects", json={"name": name}).status_code == 200
    assert client.delete(f"/api/workspace/projects/{name}").status_code == 200
    assert client.post("/api/workspace/projects", json={"name": name}).status_code == 200
    item = next(i for i in client.get("/api/trash").json()["items"] if i["kind"] == "project")
    r = client.post(f"/api/trash/{item['id']}/restore")
    assert r.status_code == 200, r.text
    names = sorted(p["name"] for p in client.get("/api/workspace/tree").json()["projects"])
    assert names == sorted([name, "a" * 39 + "-restored"]), names


def test_the_cut_never_leaves_a_double_dash_and_numbers_go_on(client, mx):
    """Names cut on a dash do not end up with `--restored`; a second restore gets `-restored-2`, still 48 max."""
    name = "a" * 38 + "-" + "c" * 9                    # the cut for "-restored" falls right after the dash
    assert len(name) == 48
    for _ in range(2):
        assert client.post("/api/workspace/projects", json={"name": name}).status_code == 200
        assert client.delete(f"/api/workspace/projects/{name}").status_code == 200
    assert client.post("/api/workspace/projects", json={"name": name}).status_code == 200
    for item in [i for i in client.get("/api/trash").json()["items"] if i["kind"] == "project"]:
        assert client.post(f"/api/trash/{item['id']}/restore").status_code == 200
    names = sorted(p["name"] for p in client.get("/api/workspace/tree").json()["projects"])
    assert names == sorted([name, "a" * 38 + "-restored", "a" * 37 + "-restored-2"]), names
