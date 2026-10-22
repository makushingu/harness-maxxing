"""Loads the CLI sub-commands contributed by each domain (each module calls cli.register)."""
import importlib
import logging

for _m in ("cmd_core", "cmd_cron", "cmd_backup", "cmd_telegram", "cmd_sessions", "cmd_voice", "cmd_custom", "cmd_import", "cmd_video", "cmd_license", "cmd_memory", "cmd_feed", "cmd_packs", "cmd_keys", "cmd_infra", "cmd_twofactor", "cmd_mcp", "cmd_deps"):
    try:
        importlib.import_module(f"maxxing.{_m}")
    except ModuleNotFoundError as e:
        if e.name != f"maxxing.{_m}":
            logging.getLogger("maxxing").exception("CLI module %s failed", _m)
