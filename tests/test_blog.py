"""20:00 블로그 연작 슬롯 (src/blog.py, compose.compose_blog)."""
import json
from datetime import date

import pytest

from src import blog, channel, compose, history
from src.models import ThreadPost
from tests.test_threads_bot import OK_FACTS
from tests.helpers import ARTICLES, BODY, HOOK, TIPS, fake_llm, selection

MODELS = compose.Models('w', 'f')
ENTRY = {
    'title': {'$t': '실업급여 신청 방법'},
    'link': [{'rel': 'alternate', 'href': 'https://www.woodyway88.com/2026/10/a.html'}],
    'category': [{'term': '생활가이드'}, {'term': '지원금·혜택'}],
    'content': {'$t': '<p>퇴사 후 <b>고용24</b>에서 신청해요.</p><script>x()</script><p>180일 이상 일해야 해요.</p>'},
}
AI_ENTRY = {**ENTRY, 'title': {'$t': '클로드 코드'}, 'category': [{'term': 'AI스킬'}],
            'link': [{'rel': 'alternate', 'href': 'https://www.woodyway88.com/2026/10/b.html'}]}
MIXED_ENTRY = {**ENTRY, 'category': [{'term': '생활경제'}, {'term': '업무생산성'}]}
FEED = json.dumps({'feed': {'entry': [ENTRY, AI_ENTRY, MIXED_ENTRY]}})
BLOG_POST = ThreadPost(hook=HOOK, tips=TIPS, pitch='표로 정리한 건 블로그에 있어\n너는 이거 알고 있었어?')


def post_of(url='https://www.woodyway88.com/2026/10/a.html'):
    return blog.BlogPost('실업급여 신청 방법', url, ('생활가이드',), '퇴사 후 고용24에서 신청해요. ' * 20)


def test_parse_feed_keeps_only_life_posts_and_strips_html():
    posts = blog.parse_feed(FEED)
    assert [p.title for p in posts] == ['실업급여 신청 방법'] and 'x()' not in posts[0].text
    assert posts[0].text == '퇴사 후 고객24에서 신청해요.\n180일 이상 일해야 해요.'.replace('고객', '고용')


@pytest.mark.parametrize('payload', ['', 'not json', '{"feed": {}}', '[]'])
def test_parse_feed_survives_bad_payload(payload):
    assert blog.parse_feed(payload) == []


def test_next_blog_post_skips_used_and_starts_from_oldest():
    newest, oldest = post_of('https://w/new'), post_of('https://w/old')
    used = (history.HistoryEntry('s', history.PUBLISHED, doc_id='https://w/old', seed='blog'),)
    assert compose.next_blog_post([newest, oldest], ()) == oldest
    assert compose.next_blog_post([newest, oldest], used) == newest
    assert compose.next_blog_post([oldest], used) is None


def test_blog_day_alternates():
    days = [date(2026, 10, 11), date(2026, 10, 12), date(2026, 10, 13)]
    flags = [compose.is_blog_day(d) for d in days]
    assert flags[0] != flags[1] and flags[0] == flags[2]


def compose_at(day_str, hour, blog_posts, responses):
    llm, client = fake_llm(responses)
    draft = compose.compose(llm, MODELS, (), lambda: list(ARTICLES), lambda a: BODY, day_str, hour,
                            slot=f'{day_str}T{hour:02d}:00', load_blog_posts=lambda: blog_posts)
    return draft, client


def blog_day():
    return next(f'2026-10-{d}' for d in (12, 13) if compose.is_blog_day(date(2026, 10, d)))


def other_day():
    return next(f'2026-10-{d}' for d in (12, 13) if not compose.is_blog_day(date(2026, 10, d)))


def test_blog_slot_on_blog_day_posts_series_with_link_in_last_reply(monkeypatch):
    monkeypatch.setattr(channel, 'BLOG_HOUR', 20)
    facts = OK_FACTS
    draft, _ = compose_at(blog_day(), 20, [post_of()], {'ThreadPost': [BLOG_POST], 'FactCheck': [facts]})
    assert draft.kind == compose.BLOG and len(draft.parts) == 3
    assert draft.parts[2].endswith('📖 실업급여 신청 방법\nhttps://www.woodyway88.com/2026/10/a.html')
    assert 'https://' not in draft.parts[0] + draft.parts[1]


def test_blog_slot_on_other_day_is_casual(monkeypatch):
    from src.casual import CasualPost
    monkeypatch.setattr(channel, 'BLOG_HOUR', 20)
    monkeypatch.setattr(channel, 'CASUAL_HOUR', 12)
    draft, _ = compose_at(other_day(), 20, [post_of()], {'CasualPost': [CasualPost(text='라면 vs 햇반, 급할 땐 뭐부터 집어?')]})
    assert draft.kind == 'casual'


def test_blog_slot_falls_back_to_casual_when_no_posts(monkeypatch):
    from src.casual import CasualPost
    monkeypatch.setattr(channel, 'BLOG_HOUR', 20)
    draft, _ = compose_at(blog_day(), 20, [], {'CasualPost': [CasualPost(text='라면 vs 햇반, 급할 땐 뭐부터 집어?')]})
    assert draft.kind == 'casual'


@pytest.mark.parametrize('title', ['미국 PCE 물가 3.4%, 금리 인상 동력은?', '증권사 전산장애, 3년 피해액 73억원',
                                   '부산진해경자청 투자 상담, 기관을 제한 없이 고른다', '어르신 독감 예방접종, 나이별 시작일'])
def test_parse_feed_drops_posts_off_channel_topic(title):
    entry = {**ENTRY, 'title': {'$t': title}, 'category': [{'term': '생활경제'}, {'term': '재테크'}]}
    assert blog.parse_feed(json.dumps({'feed': {'entry': [entry]}})) == []
