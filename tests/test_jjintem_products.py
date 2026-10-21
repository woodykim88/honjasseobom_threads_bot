"""21:00 찐템노트(쇼핑 쇼츠) 상품 글 (2026-10-21)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from src import channel, compose, schedule
from src import products as products_mod
from src.models import FactCheck, ThreadPost
from tests.helpers import ARTICLES, BODY, HOOK, TIPS, fake_llm

KST = timezone(timedelta(hours=9))
MODELS = compose.Models('w', 'f')
FEED = [
    {'no': 5, 'product': '코멧 전자레인지 찜기 세트', 'link': 'https://link.coupang.com/a/x5', 'publish_at': '2026-10-21 19:00',
     'yt_url': 'https://youtube.com/shorts/rgL3H0nshqY', 'facts': '초보: 냄비에 물 끓이기\n고수: 작은 통은 계란찜'},
    {'no': 4, 'product': '무소음 문틈막이', 'link': 'https://link.coupang.com/a/x4', 'publish_at': '2026-10-21 12:30',
     'yt_url': '', 'facts': '초보: 수건 끼우기'},
    {'no': 6, 'product': '결로 테이프', 'link': 'https://link.coupang.com/a/x6', 'publish_at': '2026-10-22 12:30',
     'yt_url': '', 'facts': '아직 공개 전'},
    {'no': 9, 'product': '콜라겐 젤리', 'link': 'https://link.coupang.com/a/x9', 'publish_at': '2026-10-20 12:30', 'facts': ''},
]
PITCH = '냄비 없이 찌고 싶은 사람한테 딱이야. 30초 영상으로도 정리해 뒀어\n너는 뭐 제일 자주 쪄?'


@pytest.fixture
def feed_file(tmp_path):
    path = tmp_path / 'jjintem_feed.json'
    path.write_text(json.dumps(FEED, ensure_ascii=False), encoding='utf-8')
    return path


def test_feed_keeps_only_published_and_allowed_products(feed_file):
    now = datetime(2026, 10, 21, 21, 0, tzinfo=KST)
    found = products_mod.load_jjintem_feed(now, feed_file)
    assert [p.name for p in found] == ['무소음 문틈막이', '코멧 전자레인지 찜기 세트']  # 공개 전·제외 품목 빠짐, 오래된 것부터
    assert found[1].video_url.endswith('rgL3H0nshqY') and '계란찜' in found[1].facts


def test_feed_missing_file_is_empty(tmp_path):
    assert products_mod.load_jjintem_feed(datetime.now(KST), tmp_path / 'none.json') == []


def test_slot_21_posts_newest_jjintem_product_with_video_and_factcheck(feed_file, monkeypatch):
    monkeypatch.setattr(channel, 'PRODUCT_HOUR', 21)
    monkeypatch.setattr(channel, 'PRODUCT_DAY_PARITY', None)
    monkeypatch.setattr(channel, 'PRODUCT_FROM_END', True)
    found = products_mod.load_jjintem_feed(datetime(2026, 10, 21, 21, 0, tzinfo=KST), feed_file)
    post = ThreadPost(hook=HOOK, tips=TIPS, pitch=PITCH)
    llm, client = fake_llm({'ThreadPost': [post], 'FactCheck': [FactCheck(claims=[])]})
    draft = compose.compose(llm, MODELS, (), lambda: list(ARTICLES), lambda a: BODY, '2026-10-21', 21, lambda: found)
    assert draft.kind == compose.PRODUCT and draft.key == 'https://link.coupang.com/a/x5'
    assert '🎬 30초 영상으로 보기\nhttps://youtube.com/shorts/rgL3H0nshqY' in draft.parts[2]
    assert draft.parts[2].endswith(compose.COUPANG_DISCLOSURE)
    assert len(client.requests) == 2  # 글쓰기 + 캡션 대조 사실 검증
    assert '찐템노트 영상 캡션' in str(client.requests[0])


def test_four_slots_allowed():
    assert schedule.parse_times('08:00,12:30,20:00,21:00') == ((8, 0), (12, 30), (20, 0), (21, 0))
    with pytest.raises(schedule.ScheduleError):
        schedule.parse_times('07:00,08:00,12:30,20:00,21:00')
