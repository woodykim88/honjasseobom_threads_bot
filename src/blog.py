"""woodyway88.com(구글 블로그) 공개 피드에서 생활경제·생활가이드 글을 읽는다 (2026-10-11 사용자 결정).

- 블로거가 공개하는 JSON 피드만 쓴다 (예약 발행 중인 글은 피드에 없다).
- AI 글은 이 채널 주제가 아니라서 라벨로 걸러, 생활 라벨이 있는 글만 스레드 연작 재료로 쓴다.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass

from src.http_client import HttpGet

FEED_URL = 'https://www.woodyway88.com/feeds/posts/default?alt=json&max-results=150'
LIFE_LABELS = ('생활가이드', '생활경제', '지원금·혜택', '재테크', '절약꿀팁')
AI_LABELS = ('AI활용', 'AI사용법', 'AI스킬', 'IT트렌드', '업무생산성', '커리어')
# 2026-10-22: 거시 금융·지역 행정·노년층 글은 자취 독자와 멀어 조회가 낮았다(경자청 3회, 증권사 전산장애 31회). 제목에 있으면 뺀다.
OFF_TOPIC_WORDS = ('증권', '금리', '물가', 'PCE', '환율', '주가', '코스피', '투자', '경자청', '경제자유구역',
                   '어르신', '노인', '상속')
MAX_BODY_CHARS = 6000
# 이 날부터 블로그 그림이 풍자 일러스트 스타일이고 JPEG 사본이 있다. 연작은 이런 글을 먼저 고른다 (2026-10-22)
STYLE_SINCE = '2026-10-21'
_TAG_RE = re.compile(r'<(script|style)[^>]*>.*?</\1>|<[^>]+>', re.S)
_BREAK_RE = re.compile(r'</(p|div|li|h[1-6]|tr)>|<br\s*/?>', re.I)
# 블로그 첫 본문 그림(-b1.webp). 구글 블로그 봇이 같은 경로에 Threads용 JPEG 사본(-b1.jpg)을 둔다 (2026-10-22)
_BODY_IMAGE_RE = re.compile(r'(https://[^"\s]+-b1)\.webp')


@dataclass(frozen=True)
class BlogPost:
    title: str
    url: str
    labels: tuple[str, ...]
    text: str
    image_url: str = ''  # 연작 첫 글에 붙일 블로그 그림 (JPEG). 없으면 글만
    published: str = ''  # 블로그 발행일 YYYY-MM-DD


def html_to_text(raw: str) -> str:
    text = html.unescape(_TAG_RE.sub('', _BREAK_RE.sub('\n', raw)))
    lines = (re.sub(r'[ \t]+', ' ', ln).strip() for ln in text.splitlines())
    return '\n'.join(ln for ln in lines if ln)[:MAX_BODY_CHARS]


def body_image_url(raw: str) -> str:
    match = _BODY_IMAGE_RE.search(raw)
    return f'{match.group(1)}.jpg' if match else ''


def is_life_post(labels: tuple[str, ...]) -> bool:
    return any(label in LIFE_LABELS for label in labels) and not any(label in AI_LABELS for label in labels)


def is_on_topic(title: str) -> bool:
    return not any(word in title for word in OFF_TOPIC_WORDS)


def parse_feed(payload: str) -> list[BlogPost]:
    """피드 JSON → 생활 글 목록 (최신순 그대로). 형식이 달라졌거나 깨졌으면 빈 목록."""
    try:
        entries = json.loads(payload).get('feed', {}).get('entry', [])
    except (ValueError, AttributeError):
        return []
    posts = []
    for entry in entries:
        url = next((link.get('href', '') for link in entry.get('link', []) if link.get('rel') == 'alternate'), '')
        labels = tuple(c.get('term', '') for c in entry.get('category', []))
        title = entry.get('title', {}).get('$t', '').strip()
        raw = entry.get('content', {}).get('$t', '')
        text = html_to_text(raw)
        if url.startswith('https://') and title and text and is_life_post(labels) and is_on_topic(title):
            published = entry.get('published', {}).get('$t', '')[:10]
            posts.append(BlogPost(title=title, url=url, labels=labels, text=text, image_url=body_image_url(raw),
                                  published=published))
    return posts


def fetch_posts(http_get: HttpGet) -> list[BlogPost]:
    return parse_feed(http_get(FEED_URL))
