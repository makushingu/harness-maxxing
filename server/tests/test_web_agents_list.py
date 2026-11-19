"""The Agents list's Mark all as read button (source checks, like test_web_mobile.py)."""
from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def test_the_agents_list_marks_every_unread_agent_and_group_read_at_once():
    src = (WEB / "features" / "agents" / "AgentsList.tsx").read_text()
    # only while something is unread, among what the topic and the search leave (whatever the state chip)
    assert "agents: matching.filter((a) => a.thread_unread)" in src
    assert "groups: matchingRooms.filter((g) => g.unread)" in src
    assert "unread.agents.length + unread.groups.length > 0 &&" in src
    assert 'data-testid="agents-mark-all-read"' in src and "markAll.mutate(unread)" in src

    q = (WEB / "lib" / "queries" / "agentGroups.ts").read_text()
    hook = q[q.index("export function useMarkAllSeen") :]
    hook = hook[: hook.index("\n}\n")]
    # the same POST /seen as opening each one, the badges at 0 at once, then both lists refreshed
    assert "agentUrl(p, '/seen')" in hook and "groupUrl(p, '/seen')" in hook
    assert "invalidate: [agentKeys.list, groupKeys.list]" in hook
    assert "thread_unread: 0" in hook and "unread: 0" in hook

    for lang in ("en", "fr"):
        assert "'agents.side.markAllRead':" in (WEB / "i18n" / f"{lang}.ts").read_text()
