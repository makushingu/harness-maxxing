"""Router registry.

Each module listed in ROUTERS exposes `router` (fastapi.APIRouter, prefix included) and may
expose `async def startup()` / `async def shutdown()` (background tasks: Telegram gateway,
session watcher, …). Routers protect themselves with `dependencies=[Depends(require_auth)]`
except the public auth endpoints.
"""
ROUTERS = [
    "auth",
    "onboarding",
    "claude",
    "workspace",
    "sessions",
    "trash",
    "importer",
    "files",
    "filesite",
    "tasks",
    "crons",
    "telegram",
    "pc",
    "backup",
    "settings",
    "secrets",
    "system",
    "docs",
    "dashboard",
    "extensions",
    "voice",
    "memory",
    "stats",
    "search",
    "feed",
    "hooks",
    "packs",
    "git",
    "mcp",
    "infra",
]
