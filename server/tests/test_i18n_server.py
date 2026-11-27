"""The texts the server shows itself exist in every interface language (config.LANGUAGES), with the same entries
and the same variables as the English ones, and the configured language is the one used."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from maxxing import agent_templates, config, packs, shopify, smartupdate, team, twofactor, widgets
from maxxing.api import push
from maxxing.devices import dist
from maxxing.telegram import gateway, texts

LANGS = config.LANGUAGES
OTHERS = tuple(lang for lang in LANGS if lang != "en")
VAR = re.compile(r"\{[a-z_]+\}")
TAG = re.compile(r"</?[a-z]+>")

# Tables {language: {key: text}} with an English entry.
BY_KEY = {
    "telegram.WORDS": texts.WORDS, "telegram.STATUS_WORDS": texts.STATUS_WORDS,
    "telegram.AGENT_REASONS": texts.AGENT_REASONS, "twofactor.WORDS": twofactor.WORDS, "push._TEXT": push._TEXT,
    "devices.TEXTS": dist.TEXTS, "widgets._CUSTOMIZE_TEXT": widgets._CUSTOMIZE_TEXT, "widgets._FORMS": widgets._FORMS,
}
# Tables {language: text}.
FLAT = {"telegram.LINK_WORDS": texts.LINK_WORDS, "team.ME_NAME": team.ME_NAME, "shopify._CONNECT": shopify._CONNECT,
        "packs.title": packs.BASICS_TEXT["title"], "packs.description": packs.BASICS_TEXT["description"]}
# Tables {language: {English text: text}}: English is the key itself.
BY_ENGLISH = {"widgets._T": widgets._T, "shopify._T": shopify._T}


def _same_shape(en: str, out: str) -> bool:
    return sorted(VAR.findall(en)) == sorted(VAR.findall(out)) and sorted(TAG.findall(en)) == sorted(TAG.findall(out))


def test_the_helper_falls_back_to_english(mx):
    assert config.LANGUAGES == ("en", "fr", "es", "de", "zh", "ja")
    assert config.language() == "en"
    for lang in LANGS:
        config.update_config(language=lang)
        assert config.language() == lang
    config.update_config(language="xx")                      # a hand-edited config
    assert config.language() == "en"
    assert [config.language(v) for v in ("de", "pt", "", None, 3, "DE")] == ["de", "en", "en", "en", "en", "en"]


@pytest.mark.parametrize("name", sorted(BY_KEY))
def test_tables_have_the_english_keys_in_every_language(name):
    table = BY_KEY[name]
    assert set(table) == set(LANGS)
    for lang in OTHERS:
        assert set(table[lang]) == set(table["en"]), f"{name} {lang}"
        for key, en in table["en"].items():
            if isinstance(en, str):
                assert table[lang][key].strip(), f"{name} {lang} {key}"
                assert _same_shape(en, table[lang][key]), f"{name} {lang} {key}"


@pytest.mark.parametrize("name", sorted(FLAT))
def test_single_texts_exist_in_every_language(name):
    table = FLAT[name]
    assert set(table) == set(LANGS)
    assert all(table[lang].strip() and _same_shape(table["en"], table[lang]) for lang in OTHERS), name


@pytest.mark.parametrize("name", sorted(BY_ENGLISH))
def test_tables_keyed_by_the_english_text(name):
    table = BY_ENGLISH[name]
    assert set(table) == set(OTHERS)
    for lang in OTHERS:
        assert set(table[lang]) == set(table["fr"]), f"{name} {lang}"
        assert all(v.strip() and _same_shape(en, v) for en, v in table[lang].items()), f"{name} {lang}"


def test_dashboard_examples_and_reply_language():
    assert set(widgets._EXAMPLES) == set(LANGS)
    for lang in OTHERS:
        assert [e[0] for e in widgets._EXAMPLES[lang]] == [e[0] for e in widgets._EXAMPLES["en"]]      # same icons
        assert all(len(e) == 4 and all(x.strip() for x in e) for e in widgets._EXAMPLES[lang])
    assert set(smartupdate.REPLY_LANGUAGES) == set(OTHERS)


def test_agent_templates_in_every_language():
    def check(v, where):
        if isinstance(v, dict) and "en" in v:
            assert set(v) == set(LANGS), where
            for lang in OTHERS:
                assert type(v[lang]) is type(v["en"]) and len(v[lang]) > 0, f"{where} {lang}"
                if isinstance(v["en"], tuple):
                    assert len(v[lang]) == len(v["en"]) and all(x.strip() for x in v[lang]), f"{where} {lang}"
                else:
                    assert v["en"].count("`") == v[lang].count("`"), f"{where} {lang}"          # commands kept
                    assert v["en"].endswith("\n- ") == v[lang].endswith("\n- "), f"{where} {lang}"   # the list to fill in
        elif isinstance(v, dict):
            for k, x in v.items():
                check(x, f"{where}.{k}")

    for t in agent_templates.TEMPLATES:
        check(t, t["id"])
    check(agent_templates.BRIEF_LABELS, "BRIEF_LABELS")
    assert set(agent_templates.BRIEFS) == {t["id"] for t in agent_templates.TEMPLATES}
    for tid, b in agent_templates.BRIEFS.items():
        check(b, f"brief {tid}")
    es = agent_templates.get("mail-sort", "es")
    assert es["name"] == "Clasificador de correo" and "`maxxing mail move UID --to CARPETA`" in es["role"]
    assert es["cron"]["prompt"] and es["mail"]["trigger"]["prompt"] and es["brief"].startswith("Mi trabajo: ")
    assert agent_templates.brief("watch", "fr").startswith("Mon travail : ")
    assert agent_templates.brief("watch", "ja").startswith("私の仕事：")
    assert agent_templates.get("watch", "pt") == agent_templates.get("watch", "en")       # unknown: English


def test_settings_accept_the_six_languages_only(client: TestClient):
    for lang in LANGS:
        assert client.put("/api/settings", json={"language": lang}).status_code == 200, lang
        assert client.get("/api/settings").json()["language"] == lang
    assert client.put("/api/settings", json={"language": "pt"}).status_code == 422
    assert client.put("/api/settings", json={"language": "EN"}).status_code == 422
    assert client.get("/api/settings").json()["language"] == LANGS[-1]


def test_the_configured_language_is_used(mx):
    config.update_config(language="de")
    assert widgets.t("Tasks") == "Aufgaben" and widgets.t("not a known text") == "not a known text"
    assert widgets.ago(None) == "Nie" and widgets._form("ago", v="3 min") == "vor 3 min"
    assert twofactor._w("expires", m=5) == "Läuft in 5 Min. ab."
    assert push._TEXT.get(config.language())["done"] == "Harness ist fertig"
    assert team._me()["name"] == "Ich"
    assert smartupdate._reply_in() == "\n\nAnswer me in German."
    assert shopify.t("To ship") == "Zu versenden" and "Einstellungen → Schlüssel" in shopify.connect_card()["blocks"][1]["text"]
    assert gateway._w("stopped") == "⏹ Gestoppt." and gateway._w("stopped", lang="xx") == "⏹ Stopped."
    assert packs._basics_summary("de")["title"] == "Standardprojekte"
    assert widgets.customize()["blocks"][0]["text"].startswith("**Dieses Dashboard")
    config.update_config(language="xx")                      # unknown: English everywhere, nothing raises
    assert widgets.t("Tasks") == "Tasks" and widgets._form("ago", v="3 min") == "3 min ago"
    assert twofactor._w("gone") == "This request expired." and gateway._w("stopped") == "⏹ Stopped."
    assert team._me()["name"] == "Me" and smartupdate._reply_in() == ""
    assert widgets.customize()["title"] == "Make it yours"


def test_telegram_sender_language(mx):
    sender = lambda code: gateway._sender_lang({"from": {"language_code": code}})      # noqa: E731
    assert [sender(c) for c in ("fr", "fr-CA", "de", "zh-hans", "ja", "es", "pt-br", "en")] == \
        ["fr", "fr", "de", "zh", "ja", "es", "en", "en"]
    config.update_config(language="ja")
    assert gateway._sender_lang({"from": {}}) == "ja" and sender("it") == "en"
    assert texts.LINK_WORDS.get(sender("zh"), texts.LINK_WORDS["en"]).startswith("此链接")


def test_pairing_page_in_the_language(mx):
    status, page = dist.link_page("", "https://h.example", "ja")
    assert '<html lang="ja">' in page and dist.TEXTS["ja"]["expired"] in page
    assert dist.TEXTS["en"]["expired"] in dist.link_page("", "https://h.example", "pt")[1]
