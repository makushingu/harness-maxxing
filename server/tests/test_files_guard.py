"""The Files page cannot trash the workspace, pull a folder from under a running session, or 500 on odd paths."""
from __future__ import annotations

import os

from maxxing import config

from conftest import wait_for


def test_the_workspace_and_its_parents_cannot_be_deleted_or_moved(client, mx):
    """With the default files root (the home folder) the workspace is a folder like any other in the Files page:
    deleting it (or a folder that holds it) used to move the whole workspace to the trash."""
    config.update_config(files_root=str(mx["tmp"]))
    assert client.post("/api/workspace/projects", json={"name": "acme"}).status_code == 200
    holder = mx["tmp"] / "holder"
    holder.mkdir()
    for path in (mx["ws"],):
        r = client.post("/api/files/delete", json={"path": str(path)})
        assert r.status_code == 403, r.text
        r = client.post("/api/files/move", json={"from": str(path), "to": str(holder / "ws")})
        assert r.status_code == 403, r.text
    assert (mx["ws"] / "projects" / "acme").is_dir()
    # A folder holding the workspace is refused too.
    config.update_config(files_root="/")
    r = client.post("/api/files/delete", json={"path": str(mx["tmp"])})
    assert r.status_code == 403, r.text
    assert (mx["ws"] / "projects" / "acme").is_dir()


def test_a_folder_with_a_running_session_is_neither_moved_nor_deleted(client, topic, mx):
    """The workspace sidebar refuses to rename / delete a topic while its session runs (409); the Files page
    went around that rule and moved the folder away from the running turn."""
    config.update_config(files_root=str(mx["tmp"]))
    s = client.post("/api/sessions", json={"path": topic, "message": "SLOW"}).json()
    wait_for(lambda: client.get(f"/api/sessions/{s['id']}").json()["state"] == "running")
    folder = mx["ws"] / topic
    for path in (folder, folder.parent.parent):                     # the topic, then its project
        r = client.post("/api/files/move", json={"from": str(path), "to": str(path.parent / "elsewhere")})
        assert r.status_code == 409 and r.json()["error"] == "has_running_sessions", r.text
        r = client.post("/api/files/delete", json={"path": str(path)})
        assert r.status_code == 409 and r.json()["error"] == "has_running_sessions", r.text
    assert folder.is_dir()
    # A plain file inside the topic is still free to go.
    (folder / "draft.txt").write_text("x")
    assert client.post("/api/files/delete", json={"path": str(folder / "draft.txt")}).status_code == 200


def test_odd_paths_are_client_errors(client, mx):
    """A NUL byte in a path, a dangling link or a file in the way answered 500."""
    for url in ("/api/files/list?path=", "/api/files/read?path=", "/api/files/raw?path="):
        r = client.get(url + str(mx["files"]) + "/a%00b")
        assert r.status_code == 400, (url, r.status_code)
    os.symlink(str(mx["files"] / "nowhere"), str(mx["files"] / "dangling"))
    r = client.post("/api/files/mkdir", json={"path": str(mx["files"] / "dangling")})
    assert r.status_code == 409, r.text
    (mx["files"] / "plain.txt").write_text("x")
    r = client.post("/api/files/mkdir", json={"path": str(mx["files"] / "plain.txt" / "sub")})
    assert r.status_code == 409, r.text
