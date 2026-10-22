import logging

from maxxing import logs


def test_redact_known_secret_formats():
    url = "POST https://api.telegram.org/bot123456789:AAFakeTokenForTestsOnly0123456789abcd/getUpdates"
    assert logs.redact(url) == "POST https://api.telegram.org/bot<redacted>/getUpdates"
    assert "AAFake" not in logs.redact("token 123456789:AAFakeTokenForTestsOnly0123456789abcd here")
    assert logs.redact("key sk-ant-oat01-abcdefghijklmnopqrstuvwxyz") == "key sk-ant-oat01-<redacted>"
    assert logs.redact("ghp_" + "a" * 36) == "ghp_<redacted>"
    assert logs.redact("nothing secret: 12:30, /api/sessions") == "nothing secret: 12:30, /api/sessions"


def test_setup_quiets_httpx_and_filters_records(caplog):
    logs.setup()
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "call %s", ("https://api.telegram.org/bot1234567:AAabcdefghijklmnopqrstuvwxyz0123456789/x",), None)
    logs.RedactSecrets().filter(rec)
    assert rec.getMessage() == "call https://api.telegram.org/bot<redacted>/x"
