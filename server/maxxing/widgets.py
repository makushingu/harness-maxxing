"""Built-in dashboard widgets. Each returns an API.md `Card`; they are computed in worker
threads by api/dashboard.py, so they may block briefly but must never raise for "normal"
situations (module not configured, nothing to show): they return a card saying so instead.

Labels follow the configured UI language (en / fr). Links are SPA routes
(/sessions/<id>, /tasks, /crons, /settings/<section>).
"""
from __future__ import annotations

import copy
import datetime as dt
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import config

_T = {
    "fr": {
        "Activity": "Activité", "Running": "En cours", "Unread": "Non lues", "Today": "Aujourd'hui",
        "No session yet": "Aucune session pour l'instant", "Tasks": "Tâches", "Doing": "En cours",
        "Due today": "Pour aujourd'hui", "Overdue": "En retard", "Nothing due - well done": "Rien d'urgent, bravo",
        "Scheduled jobs": "Tâches planifiées", "Jobs": "Tâches", "Failed (24 h)": "Échecs (24 h)",
        "No run yet": "Aucune exécution", "Success": "Succès", "Failure": "Échec", "Server": "Serveur",
        "CPU": "CPU", "Memory": "Mémoire", "Disk": "Disque", "Memory backup": "Sauvegarde mémoire",
        "Not configured": "Non configuré", "Last backup": "Dernière sauvegarde", "Never": "Jamais",
        "Files": "Fichiers", "Telegram": "Telegram", "Bot": "Bot", "Status": "État", "Connected": "Connecté",
        "Stopped": "Arrêté", "Claude usage": "Utilisation Claude", "5-hour window": "Fenêtre 5 h",
        "7-day window": "Fenêtre 7 jours", "Usage data unavailable": "Données d'utilisation indisponibles",
        "resets": "réinit.", "ago": "il y a", "Set it up": "Configurer", "Load": "Charge",
        "Up": "Allumé depuis", "Runs": "Exécutions", "Today's schedule": "Planning du jour",
        "Runs today": "Exécutions du jour", "Failed today": "Échecs du jour", "Next": "Prochaine",
        "Nothing scheduled today": "Rien de planifié aujourd'hui", "more jobs": "autres tâches",
        "Sign Claude in on this server to read the plan usage.": "Connectez Claude sur ce serveur pour lire l'utilisation du forfait.",
        "Plan usage exists only for a Claude subscription (this server uses an API key).":
            "L'utilisation du forfait n'existe qu'avec un abonnement Claude (ce serveur utilise une clé API).",
        "Anthropic limits how often the usage can be read - next reading at": "Anthropic limite la fréquence de lecture - prochaine lecture à",
        "The Claude sign-in was refused: sign in again.": "La connexion Claude a été refusée : reconnectez-vous.",
        "Last known values - next reading at": "Dernières valeurs connues - prochaine lecture à",
        "Start your first session": "Démarrer votre première session",
        "Ask anything: a question, a task, an idea.": "Posez une question, confiez une tâche, notez une idée.",
        "No open task. Add one on the Tasks page, or just tell Harness \"remind me to...\".":
            "Aucune tâche ouverte. Ajoutez-en sur la page Tâches, ou dites simplement à Harness « rappelle-moi de… ».",
        "Nothing scheduled today.": "Rien de planifié aujourd'hui.",
        "Next run": "Prochaine exécution", "No active scheduled job.": "Aucune tâche planifiée active.",
        "Ask Harness to schedule one": "Demandez à Harness d'en programmer une",
        "Make it yours": "À votre image", "Take the tutorial": "Suivre le tutoriel",
        "4 short lessons, at your pace": "4 courtes leçons, à votre rythme",
        "Add a starter project": "Ajouter un projet de départ",
        "Online store, creator, freelance... ready to use": "Boutique, créateur, freelance… prêts à l'emploi",
        "Welcome! Everything starts with a session: Claude works in a topic, with its memory, on your server.":
            "Bienvenue ! Tout commence par une session : Harness travaille dans un topic, avec sa mémoire, sur votre serveur.", "today": "aujourd'hui", "tomorrow": "demain",
    },
}


def t(text: str) -> str:
    lang = config.load_config().get("language", "en")
    return _T.get(lang, {}).get(text, text)


def _zone() -> ZoneInfo:
    try:
        return ZoneInfo(config.load_config().get("timezone") or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def ago(ts: float | None) -> str:
    if not ts:
        return t("Never")
    s = max(0, time.time() - float(ts))
    if s < 60:
        v = f"{int(s)} s"
    elif s < 3600:
        v = f"{int(s // 60)} min"
    elif s < 86400:
        v = f"{int(s // 3600)} h"
    else:
        v = f"{int(s // 86400)} d" if t("ago") == "ago" else f"{int(s // 86400)} j"
    return f"{v} ago" if t("ago") == "ago" else f"il y a {v}"


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n < 1e12 else f"{n / 1e12:.2f} TB"


# ---- widgets --------------------------------------------------------------------------------
def activity(force: bool = False) -> dict:
    from .sessions import service                       # owned by core
    sessions = [s for s in service.list_sessions() if not s.get("archived")]
    midnight = dt.datetime.now(_zone()).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    running = [s for s in sessions if s.get("state") == "running"]
    unread = [s for s in sessions if s.get("unread")]
    today = [s for s in sessions if (s.get("updated") or 0) >= midnight]
    recent = sorted(sessions, key=lambda s: s.get("updated") or 0, reverse=True)[:5]
    items = [{"title": s.get("title") or "Untitled", "subtitle": s.get("path") or "/",
              "value": "…" if s.get("state") == "running" else ago(s.get("updated")),
              "href": f"/sessions/{s['id']}",
              "status": "error" if s.get("state") == "error" else ("warn" if s.get("unread") else None)}
             for s in recent]
    if not sessions:
        return {"title": t("Activity"), "link": "/sessions", "blocks": _first_steps()}
    return {"title": t("Activity"), "link": "/sessions", "blocks": [
        {"type": "stats", "items": [
            {"type": "stat", "label": t("Running"), "value": len(running)},
            {"type": "stat", "label": t("Unread"), "value": len(unread), "tone": "warn" if unread else None},
            {"type": "stat", "label": t("Today"), "value": len(today)}]},
        {"type": "list", "items": items, "empty": t("No session yet")}]}


def _first_steps() -> list[dict]:
    """No session yet: where to start."""
    ws = config.workspace()
    inbox = "projects/general/topics/inbox"
    tutorial = next((p for p in ("projects/system/topics/tutorial", "projects/tutorial/topics/1-first-steps")
                     if (ws / p).is_dir()), None)
    items = [{"icon": "message-square", "title": t("Start your first session"),
              "subtitle": t("Ask anything: a question, a task, an idea."),
              "href": f"/sessions?path={inbox}&new=1" if (ws / inbox).is_dir() else "/sessions"}]
    if tutorial:
        items.append({"icon": "graduation-cap", "title": t("Take the tutorial"), "subtitle": t("4 short lessons, at your pace"),
                      "href": f"/sessions?path={tutorial}&new=1"})
    items.append({"icon": "folder-plus", "title": t("Add a starter project"),
                  "subtitle": t("Online store, creator, freelance... ready to use"), "href": "/settings/packs"})
    return [{"type": "markdown", "text": t("Welcome! Everything starts with a session: Claude works in a topic, "
                                           "with its memory, on your server.")},
            {"type": "list", "grid": True, "items": items}]


def tasks(force: bool = False) -> dict:
    from .api import tasks as tasks_api
    s = tasks_api.summary()
    if "error" in s:
        return {"title": t("Tasks"), "status": "error", "link": "/tasks",
                "blocks": [{"type": "markdown", "text": s["error"]}]}
    if not s["open"]:
        return {"title": t("Tasks"), "link": "/tasks", "blocks": [{"type": "markdown", "text": t(
            "No open task. Add one on the Tasks page, or just tell Harness \"remind me to...\".")}]}
    items = []
    for task in s["items"][:6]:
        overdue = bool(task.get("due") and task["due"] < s["today"])
        items.append({"title": task["title"], "subtitle": task.get("due") or t("Doing"),
                      "href": f"/tasks?task={task['id']}", "status": "error" if overdue else "warn"
                      if task.get("due") == s["today"] else "ok"})
    return {"title": t("Tasks"), "link": "/tasks", "status": "warn" if s["overdue"] else "ok", "blocks": [
        {"type": "stats", "items": [
            {"type": "stat", "label": t("Doing"), "value": s["doing"]},
            {"type": "stat", "label": t("Due today"), "value": s["due_today"]},
            {"type": "stat", "label": t("Overdue"), "value": s["overdue"], "tone": "error" if s["overdue"] else None}]},
        {"type": "list", "items": items, "empty": t("Nothing due - well done")}]}


def crons(force: bool = False) -> dict:
    from . import crons as cr
    jobs = cr.list_jobs()
    runs = cr.read_runs(limit=500)
    now, zone = time.time(), _zone()
    failed_24h = [r for r in runs if not r.get("ok") and now - (r.get("at") or 0) < 86400]
    # runs per day, last 14 days (ok / failed)
    today = dt.datetime.now(zone).date()
    days = [today - dt.timedelta(days=i) for i in range(13, -1, -1)]
    ok_pts = {d: 0 for d in days}
    ko_pts = {d: 0 for d in days}
    for r in runs:
        d = dt.datetime.fromtimestamp(r.get("at") or 0, zone).date()
        if d in ok_pts:
            (ok_pts if r.get("ok") else ko_pts)[d] += 1
    items = [{"title": r.get("name") or r.get("cron_id"), "subtitle": ago(r.get("at")),
              "value": cr.fmt_duration(r.get("duration_s")), "status": "ok" if r.get("ok") else "error",
              "href": f"/crons?job={r.get('cron_id')}"} for r in runs[:5]]
    blocks: list[dict] = [
        {"type": "stats", "items": [
            {"type": "stat", "label": t("Jobs"), "value": sum(1 for j in jobs if j["enabled"])},
            {"type": "stat", "label": t("Failed (24 h)"), "value": len(failed_24h),
             "tone": "error" if failed_24h else None}]},
        {"type": "list", "items": items, "empty": t("No run yet")}]
    if runs:
        blocks.append({"type": "chart", "kind": "bar", "series": [
            {"name": t("Success"), "points": [[d.isoformat(), ok_pts[d]] for d in days]},
            {"name": t("Failure"), "points": [[d.isoformat(), ko_pts[d]] for d in days]}]})
    return {"title": t("Scheduled jobs"), "link": "/crons", "status": "error" if failed_24h else "ok",
            "blocks": blocks}


LANE_COLORS = ["#3b82f6", "#22d3ee", "#34d399", "#fbbf24", "#a78bfa", "#f472b6", "#fb923c", "#60a5fa"]
MAX_LANES, MAX_PLANNED = 8, 48


def day(force: bool = False) -> dict:
    """Today's schedule: one lane per job on a 00:00-24:00 axis - past runs (ok / failed),
    the running one, the runs still planned today, and "now"."""
    from . import crons as cr
    zone = _zone()
    now = time.time()
    start = dt.datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    end = start + 86400
    runs = [r for r in cr.read_runs(limit=2000) if start <= (r.get("at") or 0) < end]
    by_job: dict[str, list[dict]] = {}
    for r in runs:
        by_job.setdefault(str(r.get("cron_id")), []).append(r)
    lanes, nxt = [], None
    for j in cr.list_jobs():
        past = by_job.get(j["id"], [])
        if not j.get("enabled") and not past:
            continue
        ev = [{"at": r["at"], "state": "ok" if r.get("ok") else "error",
               "label": f"{dt.datetime.fromtimestamp(r['at'], zone):%H:%M} · {cr.fmt_duration(r.get('duration_s'))}"}
              for r in past]
        if cr.is_running(j["id"]):
            ev.append({"at": now, "state": "running", "label": t("Running")})
        planned: list[float] = []
        if j.get("enabled"):
            try:
                for at in cr.iter_runs(j["schedule"], after=now, zone=zone):
                    if at >= end or len(planned) > MAX_PLANNED:
                        break
                    planned.append(at)
            except Exception:  # noqa: BLE001 - a bad expression must not break the dashboard
                planned = []
        dense = len(planned) > MAX_PLANNED or len(ev) > MAX_PLANNED
        if not dense:
            ev += [{"at": at, "state": "planned", "label": f"{dt.datetime.fromtimestamp(at, zone):%H:%M}"} for at in planned]
        if planned and (nxt is None or planned[0] < nxt[0]):
            nxt = (planned[0], j.get("name") or j["id"])
        if not ev and not dense:
            continue
        lanes.append({"name": j.get("name") or j["id"], "sub": cr.humanize(j["schedule"]), "dense": dense,
                      "kind": j.get("kind"), "events": ev if not dense else ev[:MAX_PLANNED],
                      "first": min([e["at"] for e in ev] + planned[:1] or [end]), "href": f"/crons?job={j['id']}"})
    lanes.sort(key=lambda l: l["first"])
    extra = max(0, len(lanes) - MAX_LANES)
    lanes = lanes[:MAX_LANES]
    for i, lane in enumerate(lanes):
        lane["color"] = LANE_COLORS[i % len(LANE_COLORS)]
        lane.pop("first", None)
    failed = sum(1 for r in runs if not r.get("ok"))
    stats = [{"type": "stat", "label": t("Runs today"), "value": len(runs)},
             {"type": "stat", "label": t("Failed today"), "value": failed, "tone": "error" if failed else None}]
    if nxt:
        stats.append({"type": "stat", "label": t("Next"), "value": f"{dt.datetime.fromtimestamp(nxt[0], zone):%H:%M}",
                      "hint": nxt[1]})
    if not lanes and not runs:
        return {"title": t("Today's schedule"), "link": "/crons", "blocks": _next_run_blocks(cr, zone, now, start)}
    blocks: list[dict] = [{"type": "stats", "items": stats}]
    if lanes:
        blocks.append({"type": "timeline", "start": start, "end": end, "now": now, "lanes": lanes,
                       "more": f"+{extra} {t('more jobs')}" if extra else None})
    else:
        blocks.append({"type": "markdown", "text": t("Nothing scheduled today")})
    return {"title": t("Today's schedule"), "link": "/crons", "status": "error" if failed else "ok", "blocks": blocks}


def _next_run_blocks(cr: Any, zone: ZoneInfo, now: float, start: float) -> list[dict]:
    """Empty day: say so, and when the next job runs (or how to get one)."""
    nxt = None
    for j in cr.list_jobs():
        if not j.get("enabled"):
            continue
        try:
            at = next(iter(cr.iter_runs(j["schedule"], after=now, zone=zone)), None)
        except Exception:  # noqa: BLE001
            at = None
        if at and at < now + 8 * 86400 and (nxt is None or at < nxt[0]):
            nxt = (at, j.get("name") or j["id"], j["id"])
    if not nxt:
        from .cmd_core import update_topic
        ask = f"/sessions?path=projects/{update_topic().replace('/', '/topics/', 1)}&new=1"
        return [{"type": "markdown", "text": f"{t('Nothing scheduled today.')} {t('No active scheduled job.')}"},
                {"type": "list", "items": [{"title": t("Ask Harness to schedule one"), "href": ask}]}]
    when = dt.datetime.fromtimestamp(nxt[0], zone)
    days = (when.date() - dt.datetime.fromtimestamp(start, zone).date()).days
    day_label = t("today") if days == 0 else t("tomorrow") if days == 1 else \
        when.strftime("%a") if t("ago") == "ago" else ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."][when.weekday()]
    return [{"type": "markdown", "text": t("Nothing scheduled today.")},
            {"type": "list", "items": [{"title": nxt[1], "subtitle": t("Next run"),
                                        "value": f"{day_label} {when:%H:%M}", "href": f"/crons?job={nxt[2]}"}]}]


def server(force: bool = False) -> dict:
    from . import health
    h = health.collect(force)
    mem, dsk = h["mem"], h["disk"]
    used = mem["total"] - mem["avail"]
    up_d = h["uptime_s"] / 86400
    levels = {i["level"] for i in h["issues"]}
    return {"title": t("Server"), "link": "/settings/system",
            "status": "error" if "error" in levels else "warn" if levels else "ok",
            "blocks": [
                {"type": "progress", "label": t("CPU"), "value": h["cpu_pct"] or 0, "max": 100, "format": "percent",
                 "hint": f"{t('Load')} {' / '.join(f'{x:.2f}' for x in h['load'])}"},
                {"type": "progress", "label": t("Memory"), "value": round(used / 1e9, 1),
                 "max": round(mem["total"] / 1e9, 1) or 1, "unit": "GB",
                 "hint": f"{_gb(mem['avail'])} available" if t("ago") == "ago" else f"{_gb(mem['avail'])} disponibles"},
                {"type": "progress", "label": t("Disk"), "value": dsk["pct"], "max": 100, "format": "percent",
                 "hint": f"{_gb(dsk['free'])} free" if t("ago") == "ago" else f"{_gb(dsk['free'])} libres"},
                *([{"type": "list", "items": [{"title": i["text"], "status": i["level"]} for i in h["issues"]]}]
                  if h["issues"] else []),
                {"type": "markdown", "text": f"{t('Up')} {up_d:.1f} {'d' if t('ago') == 'ago' else 'j'}" if up_d >= 1 else
                 f"{t('Up')} {h['uptime_s'] / 3600:.1f} h"}]}


def backup(force: bool = False) -> dict:
    from . import health
    if not health.backup_configured():
        return {"title": t("Memory backup"), "link": "/settings/backup", "blocks": [
            {"type": "stat", "label": t("Status"), "value": t("Not configured")},
            {"type": "markdown", "text": f"[{t('Set it up')}](/settings/backup)"}]}
    last = health.last_backup()
    repo = (config.load_config().get("backup") or {}).get("repo", "")
    if last is None:
        return {"title": t("Memory backup"), "link": "/settings/backup", "status": "warn", "blocks": [
            {"type": "stat", "label": t("Last backup"), "value": t("Never"), "hint": repo}]}
    age_h = (time.time() - float(last["at"])) / 3600
    status = "error" if last.get("ok") is False else "warn" if age_h > health.BACKUP_MAX_AGE_H else "ok"
    stats = [{"type": "stat", "label": t("Last backup"), "value": ago(last["at"]), "hint": repo,
              "tone": status if status != "ok" else None}]
    if last.get("files") is not None:
        stats.append({"type": "stat", "label": t("Files"), "value": last.get("files")})
    blocks: list[dict] = [{"type": "stats", "items": stats}]
    if last.get("error"):
        blocks.append({"type": "markdown", "text": str(last["error"])[:300]})
    return {"title": t("Memory backup"), "link": "/settings/backup", "status": status, "blocks": blocks}


def telegram(force: bool = False) -> dict:
    try:
        from .telegram import gateway
        st = gateway.status()
    except ImportError:
        st = {"configured": False}
    if not st.get("configured"):
        return {"title": t("Telegram"), "link": "/settings/telegram", "blocks": [
            {"type": "stat", "label": t("Status"), "value": t("Not configured")},
            {"type": "markdown", "text": f"[{t('Set it up')}](/settings/telegram)"}]}
    bot = st.get("bot") or {}
    status = "ok" if st.get("running") and not st.get("last_error") else "warn"
    blocks: list[dict] = [{"type": "stats", "items": [
        {"type": "stat", "label": t("Status"), "value": t("Connected") if st.get("running") else t("Stopped"),
         "tone": None if st.get("running") else "warn"},
        {"type": "stat", "label": t("Bot"), "value": f"@{bot['username']}" if bot.get("username") else "-"}]}]
    if st.get("last_error"):
        blocks.append({"type": "markdown", "text": str(st["last_error"])[:300]})
    return {"title": t("Telegram"), "link": "/settings/telegram", "status": status, "blocks": blocks}


def _clock(at: float) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(at).strftime("%H:%M")


def _reset(at: object) -> str:
    """A reset time: Unix seconds (seen in a turn) or the ISO string of the usage endpoint."""
    if isinstance(at, (int, float)):
        import datetime as _dt
        d = _dt.datetime.fromtimestamp(at)
        return d.strftime("%H:%M") if d.date() == _dt.date.today() else d.strftime("%d/%m %H:%M")
    return str(at)


def _usage_reason(u: dict) -> str:
    """A sentence for why the plan usage is missing (never a bare error code)."""
    reason = u.get("reason") or "?"
    if reason == "no_oauth_credentials":
        return t("Sign Claude in on this server to read the plan usage.")
    if reason == "api_key":
        return t("Plan usage exists only for a Claude subscription (this server uses an API key).")
    if reason == "rate_limited":
        return f"{t('Anthropic limits how often the usage can be read - next reading at')} {_clock(u['retry_at'])}" if u.get("retry_at") \
            else t("Usage data unavailable")
    if reason == "http_401":
        return t("The Claude sign-in was refused: sign in again.")
    return f"{t('Usage data unavailable')} ({reason})"


def usage(force: bool = False) -> dict:
    from . import health
    u = health.usage(force)
    if not u.get("available"):
        return {"title": t("Claude usage"), "link": "/settings/stats", "status": "warn", "blocks": [
            {"type": "markdown", "text": _usage_reason(u)}]}
    blocks = []
    for key, label in (("five_hour", "5-hour window"), ("seven_day", "7-day window")):
        w = u.get(key)
        if w and w.get("pct") is not None:
            blocks.append({"type": "progress", "label": t(label), "value": w["pct"], "max": 100, "format": "percent",
                           "hint": f"{t('resets')} {_reset(w['resets_at'])}" if w.get("resets_at") else None})
    if u.get("stale") and u.get("retry_at"):
        blocks.append({"type": "markdown", "text": f"{t('Last known values - next reading at')} {_clock(u['retry_at'])}"})
    worst = max((b.get("value", 0) for b in blocks if b["type"] == "progress"), default=0)
    return {"title": t("Claude usage"), "status": "error" if worst >= 95 else "warn" if worst >= 80 else "ok",
            "blocks": blocks}


CUSTOMIZE_ID = "customize"
_EXAMPLES = {
    "en": [
        ("shopping-cart", "Today's Shopify sales", "Orders, revenue, best sellers",
         "Add a dashboard widget that shows today's Shopify orders and revenue."),
        ("trending-up", "Visitors on my website", "Plausible, Google Analytics, Cloudflare...",
         "Add a dashboard widget with my website visitors today and over 7 days. Ask me which analytics tool I use."),
        ("credit-card", "This month's Stripe revenue", "Payments, refunds, new customers",
         "Add a dashboard widget with this month's Stripe revenue, refunds and new customers."),
        ("globe", "Are my sites up?", "Checked every few minutes",
         "Add a dashboard widget that checks every 5 minutes that my websites answer, and shows their status."),
        ("star", "My latest customer reviews", "Google, Trustpilot, app stores...",
         "Add a dashboard widget with my latest customer reviews and the average rating. Ask me where my reviews are."),
        ("sparkles", "Something else...", "Describe it, Harness asks the right questions",
         "I would like a new widget on my dashboard. Ask me the questions you need to build it."),
    ],
    "fr": [
        ("shopping-cart", "Mes ventes Shopify du jour", "Commandes, chiffre d'affaires, meilleures ventes",
         "Ajoute un widget au tableau de bord qui affiche mes commandes et mon chiffre d'affaires Shopify du jour."),
        ("trending-up", "Les visiteurs de mon site", "Plausible, Google Analytics, Cloudflare…",
         "Ajoute un widget au tableau de bord avec les visiteurs de mon site aujourd'hui et sur 7 jours. "
         "Demande-moi quel outil de statistiques j'utilise."),
        ("credit-card", "Mon chiffre Stripe du mois", "Paiements, remboursements, nouveaux clients",
         "Ajoute un widget au tableau de bord avec mon chiffre d'affaires Stripe du mois, les remboursements et les nouveaux clients."),
        ("globe", "Mes sites répondent-ils ?", "Vérifiés toutes les quelques minutes",
         "Ajoute un widget au tableau de bord qui vérifie toutes les 5 minutes que mes sites répondent et affiche leur état."),
        ("star", "Mes derniers avis clients", "Google, Trustpilot, stores d'applis…",
         "Ajoute un widget au tableau de bord avec mes derniers avis clients et la note moyenne. Demande-moi où sont mes avis."),
        ("sparkles", "Autre chose…", "Décrivez-le, Harness pose les bonnes questions",
         "Je voudrais un nouveau widget sur mon tableau de bord. Pose-moi les questions utiles pour le créer."),
    ],
}
_CUSTOMIZE_TEXT = {
    "en": {"intro": "**This dashboard is built by talking.** In any session, ask \"add a widget that shows...\": "
                    "Harness writes it in your extensions, it appears here, and updates never touch it. Try one:",
           "pages": "Need more than a card? Ask for a whole page (a client list, an order tracker...): "
                    "[see how](/x/pages).",
           "hide": "Hide this card with **Edit layout**."},
    "fr": {"intro": "**Ce tableau de bord se construit en parlant.** Dans n'importe quelle session, demandez « ajoute "
                    "un widget qui affiche… » : Harness l'écrit dans vos extensions, il apparaît ici, et les mises à "
                    "jour n'y touchent jamais. Essayez :",
           "pages": "Besoin de plus qu'une carte ? Demandez une page entière (fichier clients, suivi de commandes…) : "
                    "[voir comment](/x/pages).",
           "hide": "Masquez ce bloc avec **Modifier la disposition**."},
}


def ask_href(prompt: str) -> str:
    """A new session in the Harness topic with `prompt` already typed in."""
    from urllib.parse import quote
    from .cmd_core import update_topic
    path = "projects/" + update_topic().replace("/", "/topics/", 1)
    return f"/sessions?path={quote(path, safe='/')}&new=1&prompt={quote(prompt, safe='')}"


def customize(force: bool = False) -> dict:
    lang = "fr" if config.load_config().get("language") == "fr" else "en"
    txt = _CUSTOMIZE_TEXT[lang]
    guide = (config.workspace() / "extensions" / "pages" / "manifest.json").is_file()   # the "Your pages" guide
    outro = f"{txt['pages']} {txt['hide']}" if guide else txt["hide"]
    items = [{"icon": icon, "title": title, "subtitle": sub, "href": ask_href(prompt)}
             for icon, title, sub, prompt in _EXAMPLES[lang]]
    return {"title": t("Make it yours"), "blocks": [
        {"type": "markdown", "text": txt["intro"]},
        {"type": "list", "grid": True, "items": items},
        {"type": "markdown", "text": outro}]}


def default_hidden() -> set[str]:
    """Shown on demand only (Edit layout): duplicates of other cards, and modules that are not set up."""
    hidden = {"crons", "backup", "telegram", "shopify"}
    try:
        from . import shopify as shop
        if shop.configured():
            hidden.discard("shopify")
    except Exception:  # noqa: BLE001
        pass
    return hidden


def shopify(force: bool = False) -> dict:
    from . import shopify as shop
    return shop.card(force)


# ---- registry -------------------------------------------------------------------------------
def _stat_sig(p: Any) -> tuple | None:
    try:
        st = os.stat(p)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _crons_sig() -> tuple:
    """What the crons / day cards are computed from: jobs.json, runs.jsonl (appended by `maxxing cron
    run`, another process), the lock files (truncated when a run starts) and config.json (language,
    time zone)."""
    from . import crons as cr
    locks = []
    try:
        with os.scandir(config.state_dir("crons", "locks")) as it:
            locks = sorted((e.name, e.stat().st_mtime_ns) for e in it)
    except OSError:
        pass
    return (_stat_sig(cr.jobs_path()), _stat_sig(cr.runs_path()), _stat_sig(config.config_path()), tuple(locks))


@dataclass(frozen=True)
class Builtin:
    id: str
    title: str
    icon: str
    span: int
    fn: Callable[[bool], dict]
    available: Callable[[], bool] = lambda: True
    sig: Callable[[], tuple] | None = None     # cached while unchanged, at most CARD_CACHE_S (force: recompute)


CARD_CACHE_S = 10.0
_card_lock = threading.Lock()
_cards: dict[str, tuple[float, tuple, dict]] = {}   # id -> (at, sig, card)


# Default order (a saved layout wins): activity + server, the day + tasks, then the rest; extension widgets
# follow, and "Make it yours" always comes last until the user moves it.
BUILTINS: list[Builtin] = [
    Builtin("activity", "Activity", "messages-square", 2, activity),
    Builtin("server", "Server", "server", 1, server),
    Builtin("day", "Today's schedule", "calendar-clock", 2, day, sig=_crons_sig),
    Builtin("tasks", "Tasks", "list-checks", 1, tasks),
    Builtin("usage", "Claude usage", "gauge", 1, usage,
            lambda: bool(config.load_config().get("usage_widget"))),
    Builtin("crons", "Scheduled jobs", "clock", 1, crons, sig=_crons_sig),
    Builtin("backup", "Memory backup", "database-backup", 1, backup),
    Builtin("telegram", "Telegram", "send", 1, telegram),
    Builtin("shopify", "Shopify", "shopping-bag", 2, shopify),
    Builtin(CUSTOMIZE_ID, "Make it yours", "sparkles", 3, customize),
]


def available() -> list[Builtin]:
    return [b for b in BUILTINS if b.available()]


def card(wid: str, force: bool = False) -> dict[str, Any]:
    """Compute one built-in card (raises KeyError if unknown, other errors propagate)."""
    b = next((x for x in BUILTINS if x.id == wid), None)
    if b is None:
        raise KeyError(wid)
    sig = b.sig() if b.sig else None
    if sig is not None and not force:
        with _card_lock:
            hit = _cards.get(wid)
        if hit and hit[1] == sig and time.time() - hit[0] < CARD_CACHE_S:
            return copy.deepcopy(hit[2])
    c = strip_none(b.fn(force))
    c.setdefault("updated", time.time())
    if sig is not None:
        with _card_lock:
            _cards[wid] = (time.time(), sig, copy.deepcopy(c))
    return c


def invalidate_cards() -> None:
    with _card_lock:
        _cards.clear()


def strip_none(v: Any) -> Any:
    """Drop None values from dicts (optional Card fields are absent, never null)."""
    if isinstance(v, dict):
        return {k: strip_none(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [strip_none(x) for x in v]
    return v
