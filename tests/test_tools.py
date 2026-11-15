"""계산기 연결 글 (2026-11-16 사용자 결정: 혼자써봄을 정보마스터 계산기 유입 창구로, 12:30 하루 1편 2주 시험)."""
from datetime import date

from src import channel, compose, tools
from src.history import HistoryEntry
from src.tools import ToolPost
from tests.helpers import fake_llm

MODELS = compose.Models('w', 'f')


def _used(*slugs):
    return tuple(HistoryEntry(slot=f'2026-11-{i + 1:02d}T12:30', status='PUBLISHED', title='t',
                              seed=tools.KIND, doc_id=f'{tools.KIND}:{s}') for i, s in enumerate(slugs))


def test_tool_link_has_utm_and_site_address():
    tool = tools.TOOLS[0]
    url = tools.tool_url(tool)
    assert url.startswith(f'https://tools.woodyway88.com/{tool.slug}/')
    assert 'utm_source=threads' in url and 'utm_campaign=honjasseobom' in url


def test_every_tool_slug_is_unique_and_has_fallback_question():
    slugs = [t.slug for t in tools.TOOLS]
    assert len(slugs) == len(set(slugs))
    assert all('?' in t.fallback for t in tools.TOOLS)


def test_pick_skips_recently_used_tools():
    recent = [t.slug for t in tools.TOOLS[:tools.RECENT_SKIP]]
    picks = {tools.pick_tool(_used(*recent), date(2026, 11, d), f'2026-11-{d:02d}T12:30').slug for d in range(1, 29)}
    assert not picks & set(recent)


def test_pick_prefers_in_season_tools():
    picks = [tools.pick_tool((), date(2026, 11, d), f'2026-11-{d:02d}T12:30') for d in range(1, 31)]
    in_season = sum(11 in t.months for t in picks)
    assert in_season > len(picks) / 2


def test_pick_never_offers_out_of_season_only_tool():
    for d in range(1, 31):
        tool = tools.pick_tool((), date(2026, 7, d), f'2026-07-{d:02d}T12:30')
        assert not tool.months or 7 in tool.months


def test_tool_slot_writes_post_with_link_only_in_reply(monkeypatch):
    monkeypatch.setattr(channel, 'TOOL_HOURS', (12,))
    monkeypatch.setattr(channel, 'CASUAL_EXTRA_HOURS', ())
    llm, client = fake_llm({'ToolPost': [ToolPost(text='점심인데 발밑 전기히터가 하루 종일 돌아가는 중 ㅋㅋ 한 달 전기세 얼마 나올 것 같아?')]})
    draft = compose.compose(llm, MODELS, (), lambda: [], lambda a: None, '2026-11-17', 12, lambda: [],
                            '2026-11-17T12:30')
    assert draft.kind == tools.KIND and draft.key.startswith(f'{tools.KIND}:')
    first, reply = draft.parts
    assert 'http' not in first and 'tools.woodyway88.com' in reply
    assert draft.source_url in reply and not draft.rescued and len(client.requests) == 1


def test_tool_post_falls_back_to_prepared_question(monkeypatch):
    monkeypatch.setattr(channel, 'TOOL_HOURS', (12,))
    monkeypatch.setattr(channel, 'CASUAL_EXTRA_HOURS', ())
    bad = ToolPost(text='여기서 계산해 https://x.com')
    llm, _ = fake_llm({'ToolPost': [bad, bad]})
    draft = compose.compose(llm, MODELS, (), lambda: [], lambda a: None, '2026-11-17', 12, lambda: [],
                            '2026-11-17T12:30')
    tool = next(t for t in tools.TOOLS if draft.key == f'{tools.KIND}:{t.slug}')
    assert draft.rescued and draft.parts[0] == tool.fallback
