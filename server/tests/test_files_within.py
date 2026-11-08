"""`within` on the file routes of automatic previews (raw, preview, thumb, stat): the thumbnails and players of an
agent's answers stay in the agent's folders (api/files.py confined), even through a link inside them that leads out.
The folders come from GET .../media-roots (agent_guard.media_roots, agent_rooms.media_roots)."""
from __future__ import annotations

import os
import shutil

import pytest

from maxxing import config
from test_agent_groups import R, W, _setup

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


@pytest.fixture
def area(mx):
    root = mx["files"]
    agent = root / "agent"
    (agent / "out").mkdir(parents=True)
    (agent / "out" / "a.png").write_bytes(PNG)
    (agent / "song.mp3").write_bytes(b"ID3" + b"\0" * 64)
    other = root / "private"
    other.mkdir()
    (other / "photo.png").write_bytes(PNG)
    os.symlink(other / "photo.png", agent / "out" / "leak.png")
    os.symlink(other, agent / "dir")
    return root, agent, other


def test_in_scope_files_are_served(client, area):
    _, agent, _ = area
    w = {"within": str(agent)}
    assert client.get("/api/files/raw", params={"path": str(agent / "song.mp3"), **w}).status_code == 200
    assert client.get("/api/files/preview", params={"path": str(agent / "out" / "a.png"), **w}).status_code == 200
    if shutil.which("ffmpeg"):
        assert client.get("/api/files/thumb", params={"path": str(agent / "out" / "a.png"), **w}).status_code == 200
    r = client.post("/api/files/stat", json={"paths": [str(agent / "out" / "a.png")], "within": [str(agent)]}).json()
    assert r["mtimes"][str(agent / "out" / "a.png")] is not None
    # several folders: the one that holds the file is enough
    two = [("path", str(agent / "song.mp3")), ("within", str(agent / "out")), ("within", str(agent))]
    assert client.get("/api/files/raw", params=two).status_code == 200


def test_links_leading_out_and_dot_dot_are_refused(client, area):
    root, agent, other = area
    bad = [str(agent / "out" / "leak.png"), str(agent / "dir" / "photo.png"), str(other / "photo.png"),
           f"{agent}/out/../../private/photo.png", f"{agent}/./out/a.png"]
    for p in bad:
        for route in ("raw", "preview", "thumb"):
            r = client.get(f"/api/files/{route}", params={"path": p, "within": str(agent)})
            assert r.status_code == 403, (route, p, r.text)
    r = client.post("/api/files/stat", json={"paths": bad, "within": [str(agent)]}).json()
    assert all(v is None for v in r["mtimes"].values())
    # `within` itself must be inside the files root
    r = client.get("/api/files/raw", params={"path": str(agent / "song.mp3"), "within": "/"})
    assert r.status_code == 403
    r = client.get("/api/files/raw", params={"path": str(agent / "song.mp3"), "within": str(root / ".." / "x")})
    assert r.status_code == 403


def test_no_within_is_the_old_behaviour(client, area):
    root, agent, _ = area
    assert client.get("/api/files/raw", params={"path": str(agent / "out" / "leak.png")}).status_code == 200
    assert client.get("/api/files/raw", params={"path": f"{agent}/out/../../private/photo.png"}).status_code == 200
    r = client.post("/api/files/stat", json={"paths": [str(agent / "out" / "leak.png")]}).json()
    assert r["mtimes"][str(agent / "out" / "leak.png")] is not None


def test_media_roots_of_an_agent_and_a_group(client, topic, mx):
    _setup(client)
    ws = config.workspace()
    r = client.get("/api/agents/acme/blog/writer/media-roots")
    assert r.status_code == 200, r.text
    assert r.json()["roots"] == [str(ws / W)]
    r = client.get("/api/agent-groups/acme/team/media-roots")
    assert r.status_code == 200, r.text
    assert r.json()["roots"] == [str(ws / "projects/acme/groups/team"), str(ws / W), str(ws / R)]
    assert client.get("/api/agents/acme/blog/nobody/media-roots").status_code == 404
    assert client.get("/api/agent-groups/acme/nobody/media-roots").status_code == 404
