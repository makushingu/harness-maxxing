"""The Agents list's Mark all as read button (source checks, like test_web_mobile.py)."""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def test_the_agents_list_marks_every_unread_agent_and_group_read_at_once():
    src = (WEB / "features" / "agents" / "AgentsList.tsx").read_text()
    # shown only while something is unread, among what the topic / search narrowing leaves (not the state chip)
    assert "unread.agents.length + unread.groups.length > 0 &&" in src
    assert re.search(r"agents: matching\.filter\(\(a\) => \(a\.thread_unread \|\| 0\) > 0\)", src)
    assert re.search(r"groups: matchingRooms\.filter\(\(g\) => g\.unread > 0\)", src)
    assert 'data-testid="agents-mark-all-read"' in src and "markAll.mutate(unread)" in src
    assert "aria-label={t('agents.side.markAllRead')}" in src
    # a real touch target on a phone (icon-sm = 40 px under md)
    assert re.search(r'size="icon-sm"[^>]*\n[^>]*onClick=\{\(\) => markAll', src)

    q = (WEB / "lib" / "queries" / "agentGroups.ts").read_text()
    hook = q[q.index("export function useMarkAllSeen"):]
    hook = hook[:hook.index("\n}\n")]
    # the same POST /seen as opening each one, all of them even when one fails, then one refresh of both lists
    assert "agentUrl(p, '/seen')" in hook and "groupUrl(p, '/seen')" in hook
    assert "Promise.allSettled" in hook and "throw failed.reason" in hook
    assert "invalidate: [agentKeys.list, groupKeys.list]" in hook
    assert "thread_unread: 0" in hook and "unread: 0" in hook

    for lang in ("en", "fr"):
        assert "'agents.side.markAllRead':" in (WEB / "i18n" / f"{lang}.ts").read_text()
