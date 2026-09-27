"""언론사 공식 RSS에서 기사 후보를 모으고, 고른 기사의 본문을 가져온다 (인스타 건강노트 수집기에서 이식).

- 네이버 뉴스는 robots.txt가 자동 수집·AI 활용을 금지해서 쓰지 않는다. 언론사가 직접 배포하는 RSS만 읽는다.
- 기사 사진은 쓰지 않는다. 본문 텍스트는 사실 근거로만 쓰고 문장은 새로 쓴다 (출처는 코드가 붙인다).
"""
from __future__ import annotations

import hashlib
import html
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import requests

from src.channel import EXCLUDED_TITLE_WORDS, FEEDS, Feed
from src.http_client import HttpGet
from src.models import Candidate
from src.schedule import KST

MAX_AGE_DAYS = 5
PER_FEED_LIMIT = 20  # RSS는 최신순이라 앞에서부터 자른다 (선별 LLM 입력을 적당히 유지)
MIN_TEXT_CHARS = 500
MAX_TEXT_CHARS = 6000
MAX_SUMMARY_CHARS = 300
REQUEST_INTERVAL_SECONDS = 0.5

_TAG_RE = re.compile(r'<[^>]+>')
_DC_DATE = '{http://purl.org/dc/elements/1.1/}date'


def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(_TAG_RE.sub(' ', text or ''))).strip()


def parse_date(raw: str) -> datetime | None:
    """RSS 날짜 세 가지 형식: RFC 822, ISO 8601, '2026-09-27 08:00:00'(시간대 없으면 한국 시간)."""
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def doc_id_for(link: str) -> str:
    return hashlib.sha256(link.encode()).hexdigest()[:12]


def parse_feed(xml_text: str, feed: Feed, now: datetime) -> list[Candidate]:
    """RSS 항목을 후보로 바꿉니다. 오래된 기사, 제외 단어가 든 제목은 뺍니다."""
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    items = []
    for item in ET.fromstring(xml_text.lstrip()).iter('item'):
        title, link = _clean(item.findtext('title', '')), (item.findtext('link') or '').strip()
        published = parse_date(item.findtext('pubDate') or item.findtext(_DC_DATE) or '')
        if not title or not link.startswith('http') or published is None or published < cutoff:
            continue
        if any(w in title for w in EXCLUDED_TITLE_WORDS):
            continue
        summary = _clean(item.findtext('description', ''))
        summary = summary.split('The post ')[0][:MAX_SUMMARY_CHARS]  # 워드프레스 RSS 꼬리말 제거
        items.append(Candidate(doc_id=doc_id_for(link), title=title, summary=summary,
                               date=published.astimezone(KST).strftime('%Y.%m.%d'), link=link,
                               publisher=feed.publisher))
    return items[:PER_FEED_LIMIT]


def fetch_candidates(
    get: HttpGet, now: datetime, feeds: Sequence[Feed] = FEEDS, sleep: Callable[[float], None] = time.sleep
) -> list[Candidate]:
    """매체별 RSS를 읽어 후보를 모읍니다. 한 곳이 실패해도 나머지로 진행합니다."""
    result: dict[str, Candidate] = {}
    for feed in feeds:
        try:
            found = parse_feed(get(feed.url), feed, now)
        except (requests.RequestException, ET.ParseError) as e:
            print(f'[수집] {feed.publisher} RSS 실패 ({e.__class__.__name__}) → 건너뜀')
            continue
        print(f'[수집] {feed.publisher} {len(found)}건')
        for c in found:
            result.setdefault(c.doc_id, c)
        sleep(REQUEST_INTERVAL_SECONDS)
    return list(result.values())


def extract_body(page_html: str, url: str) -> str:
    """기사 본문만 추출합니다 (메뉴·댓글·표 제외)."""
    import trafilatura

    text = trafilatura.extract(page_html, url=url, include_comments=False, include_tables=False) or ''
    return text[:MAX_TEXT_CHARS]


def fetch_body(get: HttpGet, candidate: Candidate) -> str | None:
    """본문이 너무 짧으면(사진 기사·유료 기사 등) None."""
    try:
        text = extract_body(get(candidate.link), candidate.link)
    except requests.RequestException as e:
        print(f'[건너뜀] 본문 요청 실패 ({e.__class__.__name__})')
        return None
    return text if len(text) >= MIN_TEXT_CHARS else None
