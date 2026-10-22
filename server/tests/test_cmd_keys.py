"""`maxxing keys`: the vault from scripts (value on stdin, exposed by default, never printed by list)."""
from __future__ import annotations

import io

from maxxing import cli, vault


def run(monkeypatch, *argv, stdin=""):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return cli.main(["keys", *argv])


def test_set_get_list_delete(mx, monkeypatch, capsys):
    assert run(monkeypatch, "set", "SHOP_TOKEN", "--note", "Shopify admin", stdin="shpat_abc\n") == 0
    assert vault.get("SHOP_TOKEN") == "shpat_abc"
    assert vault.exposed_env()["SHOP_TOKEN"] == "shpat_abc"          # new key: exposed to sessions and jobs
    capsys.readouterr()
    assert run(monkeypatch, "get", "SHOP_TOKEN") == 0
    assert capsys.readouterr().out == "shpat_abc\n"
    assert run(monkeypatch, "list") == 0
    out = capsys.readouterr().out
    assert "SHOP_TOKEN" in out and "Shopify admin" in out and "shpat_abc" not in out
    assert run(monkeypatch, "set", "SHOP_TOKEN", stdin="shpat_new") == 0   # update keeps note and exposure
    assert vault.get("SHOP_TOKEN") == "shpat_new" and vault.exposed_env()["SHOP_TOKEN"] == "shpat_new"
    assert [r["note"] for r in vault.list_secrets()] == ["Shopify admin"]
    assert run(monkeypatch, "delete", "SHOP_TOKEN") == 0
    assert vault.get("SHOP_TOKEN") is None
    assert run(monkeypatch, "get", "SHOP_TOKEN") == 1


def test_set_refuses_empty_value_bad_name_and_can_stay_private(mx, monkeypatch):
    assert run(monkeypatch, "set", "EMPTY", stdin="  \n") == 2
    assert run(monkeypatch, "set", "bad-name", stdin="x") == 2
    assert run(monkeypatch, "set", "PRIVATE_ONE", "--no-expose", stdin="v") == 0
    assert "PRIVATE_ONE" not in vault.exposed_env()
