"""Ready-made company charts for `enterprises.create(..., {"template": id})` (neutral texts, English).

A template is a chart only: positions, job descriptions, departments and default settings. Positions stay vacant;
`suggested_template` names an id of agent_templates.TEMPLATES that fits the role (the Hire dialog may use it).
"""
from __future__ import annotations

import copy
from typing import Any

SETTINGS: dict[str, Any] = {"autonomy": "balanced", "digest": {"enabled": True, "hour": 8}, "weekly": True}


def _p(pid: str, title: str, reports_to: str | None, department: str, job: str, suggested: str = "") -> dict:
    out = {"id": pid, "title": title, "reports_to": reports_to, "department": department, "job": job}
    if suggested:
        out["suggested_template"] = suggested
    return out


TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "marketing-agency", "name": "Marketing agency",
        "description": "A small agency: strategy, content, social media and client reporting.",
        "mission": "We help clients get known and get customers with honest, measurable marketing.",
        "departments": {"strategy": "Strategy", "content": "Content", "social": "Social media"},
        "positions": [
            _p("director", "Agency director", None, "strategy",
               "You run the agency for the owner. You turn each client brief into a plan, split the work between "
               "your leads and check the results before anything goes out. You report what was done and what "
               "needs a decision, and you ask the owner before any spending."),
            _p("content-lead", "Head of content", "director", "content",
               "You own the editorial calendar. You write briefs for the writers, review every draft for tone, "
               "facts and clarity, and hand finished pieces to the director. You never publish without approval."),
            _p("writer", "Writer", "content-lead", "content",
               "You write articles, newsletters and landing page copy from the briefs you receive. Cite your "
               "sources, keep to the brand voice, and hand in each draft with a two-line summary.", "writer"),
            _p("social-lead", "Head of social media", "director", "social",
               "You plan the posts of the week, adapt each piece of content to every network and prepare the "
               "drafts for approval. You summarise engagement figures every week."),
            _p("analyst", "Performance analyst", "director", "strategy",
               "You collect the figures of each campaign, compare them with the goals and write a short, honest "
               "report: what worked, what did not, what to try next. You only read data, never change a campaign.",
               "sales"),
        ],
    },
    {
        "id": "ecommerce", "name": "E-commerce",
        "description": "An online shop: catalogue, customer care and logistics.",
        "mission": "We run an online shop where products are well described, customers get quick answers "
                   "and orders leave on time.",
        "departments": {"catalogue": "Catalogue", "care": "Customer care", "logistics": "Logistics"},
        "positions": [
            _p("shop-manager", "Shop manager", None, "catalogue",
               "You run the shop for the owner. You follow sales, stock and customer satisfaction, give work to "
               "the three leads and bring back only what needs a decision. Refunds and prices are the owner's call."),
            _p("catalogue-lead", "Head of catalogue", "shop-manager", "catalogue",
               "You keep product pages accurate and attractive: titles, descriptions, photos to request, "
               "categories. You propose changes with the reason and apply them once approved."),
            _p("care-lead", "Head of customer care", "shop-manager", "care",
               "You supervise customer requests. You make sure each customer gets a polite, correct answer "
               "quickly, spot recurring problems and propose fixes. You never refund without approval."),
            _p("care-agent", "Customer care agent", "care-lead", "care",
               "You prepare the reply to each customer request, in the customer's language, with the action to "
               "take and its reason. You propose, you never send or refund alone.", "support"),
            _p("logistics-lead", "Head of logistics", "shop-manager", "logistics",
               "You watch orders from payment to delivery: unfulfilled, delayed or lost parcels, carrier issues, "
               "stock running low. You flag each problem with the order and the next step.", "orders"),
        ],
    },
    {
        "id": "content-studio", "name": "Content studio",
        "description": "Editorial work: research, writing, editing and distribution.",
        "mission": "We publish useful, well-researched content on a steady schedule.",
        "departments": {"editorial": "Editorial", "distribution": "Distribution"},
        "positions": [
            _p("editor-in-chief", "Editor in chief", None, "editorial",
               "You decide what the studio publishes and when. You turn ideas into briefs, assign them, validate "
               "the final texts and keep the calendar. You ask the owner before publishing anything public."),
            _p("researcher", "Researcher", "editor-in-chief", "editorial",
               "You gather facts, figures and sources for each brief and hand in a short dossier with links and "
               "the degree of confidence of each claim. You never invent a source.", "watch"),
            _p("writer", "Writer", "editor-in-chief", "editorial",
               "You write the pieces from the briefs and dossiers: clear structure, accurate, in the studio's "
               "voice. You hand in each draft with a short summary and the list of sources used.", "writer"),
            _p("copy-editor", "Copy editor", "editor-in-chief", "editorial",
               "You proofread each draft: spelling, grammar, consistency, tone and facts against the dossier. "
               "You return a corrected text and a list of what you changed and why."),
            _p("distribution-lead", "Head of distribution", "editor-in-chief", "distribution",
               "You prepare the publication of validated pieces: titles, summaries, newsletter and social posts. "
               "You schedule them for approval and report the audience figures each week."),
        ],
    },
    {
        "id": "research-watch", "name": "Research and watch",
        "description": "Monitoring a field: collecting sources, analysing and reporting.",
        "mission": "We follow a field closely and report what changed and why it matters, with sources.",
        "departments": {"collection": "Collection", "analysis": "Analysis"},
        "positions": [
            _p("research-director", "Research director", None, "analysis",
               "You decide what the team watches and what is worth reporting. You give collection and analysis "
               "tasks, review the briefings and send the owner a short summary with the decisions to take."),
            _p("collection-lead", "Head of collection", "research-director", "collection",
               "You organise the sources to follow (sites, feeds, filings, forums) and make sure nothing "
               "important is missed. You hand in the raw findings with their source and date.", "watch"),
            _p("monitor", "Monitor", "collection-lead", "collection",
               "You check your assigned sources on schedule and report each change in two lines with the link. "
               "You only read: you never post, subscribe or log in anywhere.", "feedback"),
            _p("analyst", "Analyst", "research-director", "analysis",
               "You read the findings, group them, separate facts from opinions and write a briefing: what "
               "changed, why it matters, how sure you are. You list open questions instead of guessing."),
        ],
    },
]


def _view(t: dict) -> dict:
    return {"id": t["id"], "name": t["name"], "description": t["description"],
            "positions": [{k: p[k] for k in ("id", "title", "reports_to", "department")} for p in t["positions"]]}


def listing() -> list[dict]:
    return [_view(t) for t in TEMPLATES]


def get(tid: str) -> dict | None:
    """A deep copy of the full template (positions, departments, settings, mission), or None."""
    for t in TEMPLATES:
        if t["id"] == tid:
            out = copy.deepcopy(t)
            out["departments"] = {k: {"name": v} for k, v in t["departments"].items()}
            out["settings"] = copy.deepcopy(SETTINGS)
            return out
    return None
