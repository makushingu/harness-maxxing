"""Claude sessions: persistent conversations run turn by turn by a detached runner.

Layout (state_dir('sessions')):
  <id>.json   meta (see store.py)          <id>.log   raw NDJSON (stream-json + mx_* lines)
  <id>.lock   cross-process meta lock      <id>.run   held by the live runner (liveness probe)

Modules: store (meta + log files), normalize (raw -> API events), runner (stdlib-only turn
loop), spawn (systemd-run / direct), service (public functions, see docs/dev/INTERNALS.md).
Only `service` is imported by the rest of the server.
"""
