"""chrome-devtools-mcp (node, stdio JSON-RPC): the tools Claude gets, one process per turn using a profile.

It reaches the browser through this server's DevTools relay (loopback + a secret of that browser), never directly.
Its environment holds nothing of this server's (keys, tokens). The tool list is trimmed: no performance traces,
emulation, memory or network tools, nothing that reads or writes a file of this server.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from . import unit

START_TIMEOUT = 60.0
CALL_TIMEOUT = 120.0
MAX_FRAME = 16 * 1024 * 1024
ARGS = ("--usageStatistics=false", "--performanceCrux=false", "--screenshotMaxWidth=1280",
        "--categoryPerformance=false", "--categoryEmulation=false", "--categoryMemory=false",
        "--categoryNetwork=false", "--no-page-id-routing")    # pageId optional: the page in front
BLOCKED_TOOLS = frozenset({"upload_file", "screencast_start", "screencast_stop", "lighthouse_audit",
                           "get_network_request", "list_network_requests"})
SERVER_FILE_ARGS = ("filePath", "sourcePath")
WHEN = ("Use the browser only when a page needs JavaScript, a sign-in or clicks; to read a page or call an API, "
        "WebFetch / curl / the API is faster and cheaper. ")
LEAD_TOOLS = ("navigate_page", "new_page")


def env() -> dict:
    keep = ("PATH", "LANG", "LC_ALL", "TZ")
    out = {k: os.environ[k] for k in keep if k in os.environ}
    out["HOME"] = "/tmp"
    out["CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS"] = "1"
    return out


def offered(tools: list[dict]) -> list[dict]:
    """The tools Claude sees: none blocked, no argument naming a file of this server, the advice on the first ones."""
    out = []
    for t in tools:
        if t.get("name") in BLOCKED_TOOLS:
            continue
        schema = dict(t.get("inputSchema") or {})
        if "properties" in schema:
            schema["properties"] = {k: v for k, v in (schema.get("properties") or {}).items()
                                    if k not in SERVER_FILE_ARGS}
        if "required" in schema:
            schema["required"] = [k for k in schema["required"] if k not in SERVER_FILE_ARGS]
        d = str(t.get("description") or "")
        if t.get("name") in LEAD_TOOLS:
            d = WHEN + d
        out.append({**t, "description": d, "inputSchema": schema})
    return out


def clean_args(args: dict) -> dict:
    return {k: v for k, v in (args or {}).items() if k not in SERVER_FILE_ARGS}


class Child:
    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self.proc = proc
        self._ids = 0
        self._wait: dict[int, asyncio.Future] = {}
        self._reader = asyncio.get_running_loop().create_task(self._read())
        self.tools: list[dict] = []

    @property
    def alive(self) -> bool:
        return self.proc.returncode is None and not self._reader.done()

    @classmethod
    async def start(cls, ws_url: str, secret: str) -> "Child":
        node = unit.node_bin()
        entry = unit.cdm_entry()
        if not node or not entry.is_file():
            raise RuntimeError("the browser tools are not installed (maxxing browser setup)")
        proc = await asyncio.create_subprocess_exec(
            node, str(entry), "--wsEndpoint", ws_url, "--wsHeaders", json.dumps({"X-Browser-Secret": secret}), *ARGS,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=MAX_FRAME, env=env())
        c = cls(proc)
        try:
            await c.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "harness-maxxing", "version": "1"}}, START_TIMEOUT)
            await c.notify("notifications/initialized")
            c.tools = list((await c.call("tools/list", {}, START_TIMEOUT)).get("tools") or [])
        except BaseException:
            await c.stop()
            raise
        return c

    async def _read(self) -> None:
        assert self.proc.stdout is not None
        why = "the browser tools stopped"
        try:
            while True:
                try:
                    line = await self.proc.stdout.readline()
                except ValueError:
                    why = "the answer of the browser tools is too large"
                    break
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                f = self._wait.get(msg.get("id")) if isinstance(msg, dict) else None
                if f and not f.done():
                    f.set_result(msg)
        finally:
            for f in self._wait.values():
                if not f.done():
                    f.set_exception(RuntimeError(why))

    async def _write(self, msg: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()

    async def notify(self, method: str, params: dict | None = None) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    async def call(self, method: str, params: dict, timeout: float = CALL_TIMEOUT) -> dict:
        self._ids += 1
        rid = self._ids
        f = asyncio.get_running_loop().create_future()
        self._wait[rid] = f
        try:
            await self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            msg = await asyncio.wait_for(f, timeout)
        finally:
            self._wait.pop(rid, None)
        if "error" in msg:
            raise RuntimeError(str((msg["error"] or {}).get("message") or msg["error"]))
        return msg.get("result") or {}

    async def stop(self) -> None:
        if self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), 5)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    self.proc.kill()
                except ProcessLookupError:
                    pass
        self._reader.cancel()


def shipped_tools() -> list[dict]:
    """The tool list without starting anything (written at the first start; tools.json in this folder otherwise)."""
    from .. import browser
    for f in (browser.home() / "tools.json", Path(__file__).with_name("tools.json")):
        try:
            d = json.loads(f.read_text())
            if d.get("version") == unit.CDM_VERSION and isinstance(d.get("tools"), list) and d["tools"]:
                return d["tools"]
        except (OSError, ValueError):
            pass
    return []


def remember_tools(tools: list[dict]) -> None:
    from .. import browser, config
    try:
        browser.home().mkdir(parents=True, exist_ok=True)
        config.write_json(browser.home() / "tools.json", {"version": unit.CDM_VERSION, "tools": tools})
    except OSError:
        pass
