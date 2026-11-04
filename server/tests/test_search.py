from __future__ import annotations

import json
import os

from maxxing import config, search
from maxxing.sessions import store


def _session(path: str, title: str, messages: list[tuple[str, str]]) -> str:
    m = store.new_meta(path, title)
    store.create(m)
    with open(store.log_path(m["id"]), "a") as f:
        for role, text in messages:
            if role == "user":
                f.write(json.dumps({"type": "mx_user", "text": text, "attachments": [], "source": "web", "at": 1.0}) + "\n")
            else:
                f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}) + "\n")
    return m["id"]


def test_index_and_query(client, mx):
    ws = config.workspace()
    (ws / "memory.md").write_text("# Global\n- La facturation des clients se fait le 5 du mois\n")
    d = ws / "projects" / "acme" / "topics" / "blog"
    d.mkdir(parents=True)
    (d / "notes.md").write_text("Plan éditorial: articles sur la tâche de relance client\n")
    (d / "big.md").write_text("x" * (search.MAX_FILE_BYTES + 10))
    (d / "image.png").write_bytes(b"\x89PNG\0\0")
    client.post("/api/tasks", json={"title": "Relancer le fournisseur", "notes": "appeler lundi", "labels": ["urgent"]})
    sid = _session("projects/acme/topics/blog", "Refonte du site", [("user", "Peux-tu préparer la facture du mois ?"),
                                                                    ("assistant", "Voici la facture préparée.")])
    search.refresh()

    r = client.get("/api/search", params={"q": "factur"}).json()
    kinds = {x["kind"] for x in r["results"]}
    assert {"memory", "session"} <= kinds
    s = next(x for x in r["results"] if x["kind"] == "session")
    assert s["id"] == sid and "\x02" in s["snippet"] and s["path"] == "projects/acme/topics/blog"

    # accent-insensitive, any order, all words required
    assert any(x["kind"] == "file" for x in client.get("/api/search", params={"q": "tache relance"}).json()["results"])
    assert not client.get("/api/search", params={"q": "tache zzzz"}).json()["results"]
    # tasks, kind filter, path words
    t = client.get("/api/search", params={"q": "fournisseur", "kinds": "task"}).json()["results"]
    assert len(t) == 1 and t[0]["title"] == "Relancer le fournisseur"
    assert client.get("/api/search", params={"q": "acme notes"}).json()["results"][0]["title"] == "notes.md"
    # skipped: too big, binary
    assert not client.get("/api/search", params={"q": "xxxx"}).json()["results"]
    # sessions endpoint goes through the index (markers stripped)
    hits = client.get("/api/sessions/search", params={"q": "facture"}).json()
    assert hits and hits[0]["id"] == sid and "\x02" not in hits[0]["snippet"]


def test_incremental_and_cleanup(client, mx):
    ws = config.workspace()
    f = ws / "doc.md"
    f.write_text("alpha bravo\n")
    sid = _session("", "Root", [("user", "premier message")])
    search.refresh()
    assert search.search("bravo")["results"]
    # file edited -> reindexed; appended session messages -> indexed from the offset
    f.write_text("charlie delta\n")
    os.utime(f, (1, 2))
    with open(store.log_path(sid), "a") as fh:
        fh.write(json.dumps({"type": "mx_user", "text": "second message zoulou", "attachments": [], "source": "web", "at": 2.0}) + "\n")
    search.refresh()
    assert not search.search("bravo")["results"] and search.search("charlie")["results"]
    assert search.search("zoulou")["results"][0]["id"] == sid
    # renamed session -> title updated; deleted file / session -> dropped
    store.update(sid, title="Nouveau titre")
    f.unlink()
    search.refresh()
    assert search.search("nouveau titre")["results"][0]["id"] == sid
    assert not search.search("charlie")["results"]
    store.remove(sid)
    search.refresh()
    assert not search.search("zoulou")["results"]
    st = client.get("/api/search/stats").json()
    assert st["bytes"] > 0


def test_query_parsing():
    assert search.fts_query("Fact  client!") == '"Fact"* "client"*'
    assert search.fts_query('a "b') == '"a" "b"'
    assert search.fts_query("  ") is None


def test_wal_truncated_after_a_pass_that_wrote(mx):
    import sqlite3
    import time as _time
    ws = config.workspace()
    for i in range(200):
        (ws / f"note-{i}.md").write_text(f"note {i} " + "lorem ipsum dolor " * 200)
    search.refresh()
    wal = config.STATE / "search.db-wal"
    assert not wal.exists() or wal.stat().st_size == 0
    # a reader holding a snapshot: the checkpoint gives up quickly, the next pass truncates
    (ws / "late.md").write_text("late words")
    rd = sqlite3.connect(search.db_path())
    rd.execute("BEGIN")
    rd.execute("SELECT count(*) FROM items").fetchone()
    (ws / "later.md").write_text("later words")
    t = _time.monotonic()
    search.refresh()
    assert _time.monotonic() - t < 5
    rd.rollback()
    rd.close()
    (ws / "last.md").write_text("last words")
    search.refresh()
    assert wal.stat().st_size == 0
    assert search.checkpoint()[0] == 0


def _q(client, q, kinds=""):
    return client.get("/api/search", params={"q": q, "kinds": kinds, "limit": 100}).json()["results"]


def test_big_project_never_hides_the_others(client, mx, monkeypatch):
    """A project full of files used to take every place (alphabetical fill): the others had nothing indexed."""
    monkeypatch.setattr(search, "MAX_FILES", 40)
    monkeypatch.setattr(search, "BUCKET_MIN", 5)
    ws = config.workspace()
    big = ws / "projects" / "aaa-data" / "topics" / "dump"
    for i in range(30):
        d = big / f"part{i:02d}"
        d.mkdir(parents=True)
        for j in range(10):
            (d / f"n{j}.py").write_text(f"VALUE_{i}_{j} = 1\n")
    z = ws / "projects" / "zzz-shop" / "topics" / "orders"
    z.mkdir(parents=True)
    (z / "memory.md").write_text("Le transporteur zebulon livre le mardi\n")
    (z / "CLAUDE.md").write_text("# Topic orders\nRegle: verifier le colis quokka\n")
    (z / "notes.md").write_text("relance pangolin\n")
    (ws / "projects" / "zzz-shop" / "memory.md").write_text("Projet ornithorynque\n")
    search.refresh()
    assert [r["kind"] for r in _q(client, "zebulon")] == ["memory"]
    assert _q(client, "quokka", "memory") and _q(client, "ornithorynque", "memory")
    assert _q(client, "pangolin")                                  # a fair share for the last topic too
    st = search._state["files"]
    assert st["files"] <= 40 and st["cut"] >= 1


def test_walk_stops_at_the_cap(client, mx, monkeypatch):
    monkeypatch.setattr(search, "MAX_FILES", 10)
    monkeypatch.setattr(search, "BUCKET_MIN", 1)
    monkeypatch.setattr(search, "BUCKET_MAX", 10)
    ws = config.workspace()
    root = ws / "projects" / "acme" / "topics" / "data"
    for i in range(50):
        d = root / f"d{i:02d}"
        d.mkdir(parents=True)
        (d / "a.txt").write_text("x\n")
        (d / "b.txt").write_text("y\n")
    seen = []
    real = os.walk

    def walk(top, *a, **k):
        for cur, dirs, files in real(top, *a, **k):
            seen.append(cur)
            yield cur, dirs, files
    monkeypatch.setattr(search.os, "walk", walk)
    search.refresh()
    data_dirs = [s for s in seen if "/topics/data/" in s]
    assert len(data_dirs) < 10                                  # stopped early, not all 50 folders


def test_data_files_leave_the_index_and_the_base_shrinks(client, mx, monkeypatch, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="maxxing.search")
    ws = config.workspace()
    d = ws / "projects" / "acme" / "topics" / "blog"
    d.mkdir(parents=True)
    (d / "notes.md").write_text("texte gardé\n")
    con = search._db()
    # rows left by the previous rules: a .json data file, a dummy rules version
    fp = str(d / "export.json")
    (d / "export.json").write_text('{"produit": "wombat"}')
    con.execute("INSERT INTO items(src, kind, ref, path, title, body, at) VALUES (?,?,?,?,?,?,?)",
                (f"f:{fp}", "file", fp, fp, "export.json", "wombat", 1.0))
    con.execute("INSERT OR REPLACE INTO src(key, sig) VALUES (?, ?)", (f"f:{fp}", "1:1"))
    con.execute("INSERT OR REPLACE INTO meta VALUES('file_rules', '1')")
    con.commit()
    search.refresh()
    assert not _q(client, "wombat") and _q(client, "garde")
    assert con.execute("SELECT v FROM meta WHERE k='file_rules'").fetchone()[0] == search.FILE_RULES
    assert "compacted" in caplog.text                          # VACUUM once, when the rules changed
    caplog.clear()
    search.refresh()
    assert "compacted" not in caplog.text


def test_background_pass_reads_memory_but_walks_rarely(client, mx):
    ws = config.workspace()
    t = ws / "projects" / "acme" / "topics" / "blog"
    t.mkdir(parents=True)
    search.refresh()                                            # full walk
    (t / "memory.md").write_text("souvenir capybara\n")
    (t / "notes.md").write_text("note okapi\n")
    search.refresh(True, None)                                  # the loop, right after a walk
    assert _q(client, "capybara", "memory") and not _q(client, "okapi")
    (t / "memory.md").unlink()
    search.refresh(True, None)
    assert not _q(client, "capybara")
    search._state["files_at"] = 0.0                             # FILES_EVERY_S elapsed
    search.refresh(True, None)
    assert _q(client, "okapi")


def test_unchanged_sessions_are_not_read_again(client, mx, monkeypatch):
    sids = [_session("", f"Session {i}", [("user", f"message {i}")]) for i in range(5)]
    search.refresh()
    reads = []
    real = store.read
    monkeypatch.setattr(store, "read", lambda sid: reads.append(sid) or real(sid))
    search.refresh()
    search.search("message")
    assert reads == []                                   # nothing changed: no meta parsed again
    with open(store.log_path(sids[0]), "a") as fh:
        fh.write(json.dumps({"type": "mx_user", "text": "nouveau yankee", "attachments": [], "source": "web", "at": 2.0}) + "\n")
    store.update(sids[1], title="Titre changé")
    reads.clear()                                        # (update() reads the meta itself)
    search.refresh()
    assert sorted(reads) == sorted(sids[:2])
    assert search.search("yankee")["results"][0]["id"] == sids[0]
    assert search.search("titre changé")["results"][0]["id"] == sids[1]


def test_a_lone_surrogate_in_a_log_breaks_neither_the_session_nor_the_index(client, mx):
    bad = _session("", "Coupée", [])
    with open(store.log_path(bad), "a") as fh:      # a text cut inside an emoji: valid JSON, not valid UTF-8
        fh.write('{"type":"assistant","message":{"role":"assistant","content":[{"type":"text",'
                 '"text":"cut \\ud800 zebrafish"}]}}\n')
    good = _session("", "Saine", [("assistant", "fine quokkaword")])
    for q in ("from=0", "tail=50"):
        r = client.get(f"/api/sessions/{bad}/events?{q}")
        assert r.status_code == 200 and "cut � zebrafish" in r.text
    search.refresh()
    assert [x["id"] for x in search.search("quokkaword")["results"]] == [good]
    assert [x["id"] for x in search.search("zebrafish")["results"]] == [bad]


def test_a_moved_session_is_found_under_its_new_topic(client, mx):
    sid = _session("projects/acme/topics/blog", "Déplacée", [("user", "okapiword")])
    search.refresh()
    store.update(sid, path="projects/zeta/topics/t2")
    search.refresh()
    assert [x["path"] for x in search.search("okapiword")["results"]] == ["projects/zeta/topics/t2"]


def test_a_fifo_named_like_a_text_file_does_not_block_the_index(client, mx):
    import threading
    d = config.workspace() / "projects" / "acme" / "topics" / "blog"
    d.mkdir(parents=True)
    os.mkfifo(d / "pipe.md")
    os.mkfifo(d / "memory.md")
    (d / "notes.md").write_text("une note sur le fromage\n")
    t = threading.Thread(target=search.refresh, daemon=True)
    t.start()
    t.join(8)
    blocked = t.is_alive()
    for _ in range(20):                                  # unblock the reader (each FIFO in turn) before failing
        if not t.is_alive():
            break
        for name in ("memory.md", "pipe.md"):
            os.close(os.open(d / name, os.O_RDWR))
        t.join(0.5)
    assert not blocked, "the index blocked reading a FIFO"
    assert [r["title"] for r in _q(client, "fromage")] == ["notes.md"]


def test_a_link_to_a_file_outside_the_workspace_is_not_indexed(client, mx, tmp_path):
    secret = tmp_path / "outside" / "app.conf"
    secret.parent.mkdir()
    secret.write_text("password=zqxsecretvalue123\n")
    d = config.workspace() / "projects" / "acme" / "topics" / "blog"
    d.mkdir(parents=True)
    (d / "notes.md").write_text("zqxsecretvalue123 dans une vraie note\n")
    os.symlink(secret, d / "link.txt")
    os.symlink(secret, d / "memory.md")
    os.symlink(d / "notes.md", d / "inside.md")              # a link inside the workspace is still read
    search.refresh()
    assert sorted(r["title"] for r in _q(client, "zqxsecretvalue123")) == ["inside.md", "notes.md"]
def test_a_session_whose_title_matches_never_hides_the_others(mx):
    big = _session("", "Kangaroo planning", [("user", f"step {i} of the plan") for i in range(200)])
    others = {_session("", f"Shop {i}", [("user", "we should buy a kangaroo plush")]) for i in range(5)}
    search.refresh()
    ids = [x["id"] for x in search.search("kangaroo")["results"]]
    assert set(ids) == others | {big} and len(ids) == 6          # one entry per session
    # a message row shows its session's title; a rename rewrites the title row only
    assert {x["title"] for x in search.search("plush")["results"]} == {f"Shop {i}" for i in range(5)}
    store.update(big, title="Wallaby planning")
    con = search._db()
    before = con.total_changes
    search.refresh()
    assert con.total_changes - before < 50                       # the title row, not its 200 messages
    assert [x["title"] for x in search.search("wallaby")["results"]] == ["Wallaby planning"]
    assert search.search("step 7")["results"][0]["title"] == "Wallaby planning"


def test_an_index_of_the_previous_schema_is_migrated(mx):
    sid = _session("", "Kangaroo planning", [("user", f"step {i}") for i in range(80)])
    other = _session("", "Shop", [("user", "a kangaroo plush")])
    search.refresh()
    con = search._db()                                           # as version 1 wrote it: title on every row
    con.executescript("""
        DROP TRIGGER items_au;
        CREATE TRIGGER items_au AFTER UPDATE ON items BEGIN
            INSERT INTO fts(fts, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
            INSERT INTO fts(rowid, title, body) VALUES (new.id, new.title, new.body); END;
        UPDATE items SET title = (SELECT t.title FROM items t WHERE t.src = items.src AND t.body = '')
            WHERE kind = 'session';
        UPDATE meta SET v = '1' WHERE k = 'schema';
    """)
    search._con = None                                           # next start
    search.refresh()
    con = search._db()
    assert con.execute("SELECT v FROM meta WHERE k='schema'").fetchone()[0] == search.SCHEMA_VERSION
    assert con.execute("SELECT COUNT(*) FROM items WHERE kind='session' AND title!=''").fetchone()[0] == 2
    assert {x["id"] for x in search.search("kangaroo")["results"]} == {sid, other}


def test_a_log_ending_in_a_cut_line_is_not_rewritten_on_every_query(mx):
    sid = _session("", "Cut", [("user", "complete message")])
    with open(store.log_path(sid), "a") as fh:
        fh.write('{"type":"mx_user","text":"cut in the mid')         # a runner killed mid-write
    search.refresh()
    con = search._db()
    before = con.total_changes
    search.refresh()
    search.search("complete")
    assert con.total_changes == before and f"s:{sid}" in search._seen
    with open(store.log_path(sid), "a") as fh:                      # the line is completed later: indexed
        fh.write('dle zanzibar","attachments":[],"source":"web","at":2.0}\n')
    search.refresh()
    assert search.search("zanzibar")["results"][0]["id"] == sid


def test_broad_queries_rank_only_the_newest_matches_and_can_be_cancelled(mx, monkeypatch):
    old = _session("", "Old", [("user", "deploy the server")])
    search.refresh()
    new = _session("", "New", [("user", "deploy again")])
    search.refresh()
    monkeypatch.setattr(search, "RANK_MAX", 1)
    assert [x["id"] for x in search.search("deploy")["results"]] == [new]
    monkeypatch.setattr(search, "RANK_MAX", 5000)
    assert {x["id"] for x in search.search("deploy")["results"]} == {old, new}
    assert search.fts_query("de facture") == '"de" "facture"*'   # 2 letters: the word itself, not a prefix
    r = search.search("deploy", cancelled=lambda: True)          # the palette already sent the next query
    assert r["results"] == [] and r.get("cancelled")
    with search._rlock:                                          # waiting for the reader: gives up when cancelled
        assert search.search("deploy", cancelled=lambda: True).get("cancelled")


async def test_an_aborted_request_stops_its_query(monkeypatch):
    import asyncio
    import time as _time
    from maxxing.api import search as search_api

    def slow(q, kinds, limit, cancelled):                       # a query that only ends when cancelled
        while not cancelled():
            _time.sleep(0.01)
        return {"results": [], "cancelled": True}
    monkeypatch.setattr(search_api.engine, "search", slow)

    class Gone:                                                  # the palette aborted the request
        async def is_disconnected(self):
            return True
    r = await asyncio.wait_for(search_api.search(Gone(), q="de", kinds="", limit=30), 5)
    assert r["cancelled"]
