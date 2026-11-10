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


def test_tracebacks_and_uvicorn_records_are_redacted():
    import io
    import logging.config
    token = "123456789:AA" + "b" * 33
    logs.setup()
    root_filter = next(x for x in logging.getLogger().handlers[0].filters if isinstance(x, logs.RedactSecrets))
    out = io.StringIO()
    h = logging.StreamHandler(out)
    h.addFilter(root_filter)
    lg = logging.getLogger("maxxing.test_logs_tb")
    lg.addHandler(h)
    lg.propagate = False
    try:
        try:
            raise RuntimeError(f"call https://api.telegram.org/bot{token}/getMe failed ({token})")
        except RuntimeError:
            lg.exception("boom")
        lg.error("stack", stack_info=True)
    finally:
        lg.removeHandler(h)
    assert "RuntimeError" in out.getvalue() and token not in out.getvalue()
    # uvicorn installs its own handlers (dictConfig, no propagation): the filter sits on its loggers
    logging.config.dictConfig({"version": 1, "disable_existing_loggers": False,
                               "handlers": {"s": {"class": "logging.StreamHandler", "stream": "ext://sys.stderr"}},
                               "loggers": {"uvicorn.error": {"handlers": ["s"], "propagate": False}}})
    uv = logging.getLogger("uvicorn.error")
    try:
        rec = uv.makeRecord("uvicorn.error", logging.ERROR, __file__, 1, "token %s", (token,), None)
        assert uv.filter(rec)
        assert token not in rec.getMessage()
    finally:
        uv.handlers.clear()
        uv.propagate = True
