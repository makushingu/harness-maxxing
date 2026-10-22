"""Minimal Telegram Bot API client (async for the gateway, sync for other processes).

The API base URL is `MAXXING_TELEGRAM_API` (default https://api.telegram.org) so tests run
against a local mock. Errors are raised as `TelegramError` with the API description; a 429 is
retried once after `retry_after` seconds. The token never appears in raised messages or logs.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

TOKEN_RE = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{30,50}$")


def api_base() -> str:
    """Telegram API base URL (overridable for tests)."""
    return os.environ.get("MAXXING_TELEGRAM_API", "https://api.telegram.org").rstrip("/")


class TelegramError(Exception):
    """An API call failed. `code` = HTTP/API error code (0 = network), `retry_after` for 429."""

    def __init__(self, code: int, description: str, retry_after: float | None = None):
        super().__init__(description)
        self.code = code
        self.description = description
        self.retry_after = retry_after

    @property
    def network(self) -> bool:
        return self.code == 0


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "<token>") if token else text


def _payload(params: dict[str, Any]) -> dict[str, Any]:
    """Drop None values; JSON-encode nested structures (reply_markup, commands…)."""
    out: dict[str, Any] = {}
    for k, v in params.items():
        if v is None:
            continue
        out[k] = v
    return out


def _parse(resp: httpx.Response, token: str) -> Any:
    try:
        data = resp.json()
    except ValueError:
        raise TelegramError(resp.status_code, f"HTTP {resp.status_code} (not JSON)")
    if not isinstance(data, dict) or not data.get("ok"):
        d = data if isinstance(data, dict) else {}           # a proxy answering a list / a string
        desc = _scrub(str(d.get("description") or f"HTTP {resp.status_code}"), token)
        ra = (d.get("parameters") or {}).get("retry_after") if isinstance(d.get("parameters"), dict) else None
        try:
            code = int(d.get("error_code") or resp.status_code)
        except (TypeError, ValueError):
            code = resp.status_code
        try:
            retry = float(ra) if ra is not None else None
        except (TypeError, ValueError):
            retry = None
        raise TelegramError(code, desc, retry)
    return data.get("result")


class Client:
    """Async client bound to one bot token."""

    def __init__(self, token: str, timeout: float = 30.0):
        self.token = token
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0))

    def _url(self, method: str) -> str:
        return f"{api_base()}/bot{self.token}/{method}"

    async def call(self, method: str, http_timeout: float | None = None, **params: Any) -> Any:
        """Call a Bot API method (JSON body) and return `result`.

        `http_timeout` overrides the HTTP read timeout (long polling); every other keyword is
        an API parameter (None values are dropped).
        """
        for attempt in (0, 1):
            try:
                kw: dict[str, Any] = {"json": _payload(params)}
                if http_timeout is not None:
                    kw["timeout"] = httpx.Timeout(http_timeout, connect=10.0)
                resp = await self._http.post(self._url(method), **kw)
            except httpx.HTTPError as e:
                raise TelegramError(0, _scrub(f"{type(e).__name__}: {e}", self.token)) from None
            try:
                return _parse(resp, self.token)
            except TelegramError as e:
                if e.code == 429 and attempt == 0 and (e.retry_after or 0) <= 30:
                    await asyncio.sleep(e.retry_after or 1)
                    continue
                raise
        raise TelegramError(429, "rate limited")                       # pragma: no cover

    async def download(self, file_id: str, dest: Path, max_bytes: int = 20 * 1024 * 1024) -> Path:
        """getFile + download into `dest` (parents created). Bot API caps downloads at 20 MB."""
        info = await self.call("getFile", file_id=file_id)
        fp = (info or {}).get("file_path")
        if not fp:
            raise TelegramError(400, "file is not downloadable")
        if (info.get("file_size") or 0) > max_bytes:
            raise TelegramError(413, "file is too big (Telegram bots can download up to 20 MB)")
        url = f"{api_base()}/file/bot{self.token}/{fp}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        try:
            async with self._http.stream("GET", url, timeout=httpx.Timeout(120, connect=10)) as r:
                if r.status_code != 200:
                    raise TelegramError(r.status_code, f"download failed (HTTP {r.status_code})")
                size = 0
                with open(tmp, "wb") as f:
                    async for chunk in r.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise TelegramError(413, "file is too big")
                        f.write(chunk)
            os.replace(tmp, dest)
        except httpx.HTTPError as e:
            raise TelegramError(0, _scrub(f"download failed: {type(e).__name__}", self.token)) from None
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return dest

    async def aclose(self) -> None:
        await self._http.aclose()


def call_sync(token: str, method: str, http_timeout: float = 15.0, **params: Any) -> Any:
    """Blocking one-shot call (worker threads, `maxxing cron run`, CLI)."""
    for attempt in (0, 1):
        try:
            with httpx.Client(timeout=httpx.Timeout(http_timeout, connect=10.0)) as c:
                resp = c.post(f"{api_base()}/bot{token}/{method}", json=_payload(params))
        except httpx.HTTPError as e:
            raise TelegramError(0, _scrub(f"{type(e).__name__}: {e}", token)) from None
        try:
            return _parse(resp, token)
        except TelegramError as e:
            if e.code == 429 and attempt == 0 and (e.retry_after or 0) <= 10:
                time.sleep(e.retry_after or 1)
                continue
            raise
    raise TelegramError(429, "rate limited")                           # pragma: no cover


def keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    """Inline keyboard markup from rows of (label, callback_data); data is capped at 64 bytes."""
    return {"inline_keyboard": [[{"text": t[:60], "callback_data": d.encode()[:64].decode("utf-8", "ignore")}
                                 for t, d in row] for row in rows]}
