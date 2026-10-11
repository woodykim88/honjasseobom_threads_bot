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
MAX_BODY_CHARS = 6000
_TAG_RE = re.compile(r'<(script|style)[^>]*>.*?</\1>|<[^>]+>', re.S)
_BREAK_RE = re.compile(r'</(p|div|li|h[1-6]|tr)>|<br\s*/?>', re.I)


@dataclass(frozen=True)
class BlogPost:
    title: str
    url: str
    labels: tuple[str, ...]
    text: str


def html_to_text(raw: str) -> str:
    text = html.unescape(_TAG_RE.sub('', _BREAK_RE.sub('\n', raw)))
    lines = (re.sub(r'[ \t]+', ' ', ln).strip() for ln in text.splitlines())
    return '\n'.join(ln for ln in lines if ln)[:MAX_BODY_CHARS]


def is_life_post(labels: tuple[str, ...]) -> bool:
    return any(label in LIFE_LABELS for label in labels) and not any(label in AI_LABELS for label in labels)


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
        text = html_to_text(entry.get('content', {}).get('$t', ''))
        if url.startswith('https://') and title and text and is_life_post(labels):
            posts.append(BlogPost(title=title, url=url, labels=labels, text=text))
    return posts


def fetch_posts(http_get: HttpGet) -> list[BlogPost]:
    return parse_feed(http_get(FEED_URL))
