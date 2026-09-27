"""구제 발행: 모든 재작성이 검수에 떨어져도 회차를 건너뛰지 않는다 (2026-09-27 사용자 지시, 인스타 3채널과 같은 원칙).

검수를 끄는 게 아니라, 가장 나은 원고에서 문제가 된 줄(근거 없는 사실, 금지 표현, 1인칭 후기, 링크·해시태그)을
빼고 길이를 맞춰 낸다. 틀린 정보는 싣지 않고, 빠진 만큼 글이 짧아질 뿐이다.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from src import quality
from src.threads import MAX_TEXT_CHARS

MIN_HOOK_CHARS = 30
MIN_TIPS_CHARS = 60
MIN_MATCH_CHARS = 6
_LINK_OR_TAG_RE = re.compile(r'https?://|www\.|#')


def _normalize(text: str) -> str:
    return re.sub(r'\s+', '', text).strip('"\'“”‘’')


def is_bad_line(line: str, bad_sentences: Sequence[str]) -> bool:
    if quality.rule_issues(line):
        return True
    if _LINK_OR_TAG_RE.search(line):
        return True
    flat = _normalize(line)
    for sentence in bad_sentences:
        s = _normalize(sentence)
        if len(s) >= MIN_MATCH_CHARS and (s in flat or (len(flat) >= MIN_MATCH_CHARS and flat in s)):
            return True
    return False


def _fit(lines: list[str], limit: int, keep_last: bool) -> list[str]:
    """limit자 안에 들어올 때까지 뒤에서부터 줄을 뺍니다. keep_last면 마지막 줄(질문 마무리)은 남깁니다."""
    kept = list(lines)
    while kept and len('\n'.join(kept)) > limit:
        kept.pop(-2 if keep_last and len(kept) > 2 else -1)
    return kept


def clean_part(text: str, bad_sentences: Sequence[str], limit: int, keep_last: bool = False) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip() and not is_bad_line(ln, bad_sentences)]
    return '\n'.join(_fit(lines, limit, keep_last))


def rescue(hook: str, tips: str, bad_sentences: Sequence[str], tail: str) -> tuple[str, str] | None:
    """문제 줄을 뺀 (첫 글, 답글+출처)를 반환합니다. 남는 내용이 너무 적으면 None."""
    clean_hook = clean_part(hook, bad_sentences, quality.LIMITS['hook'])
    tips_limit = min(quality.LIMITS['tips'], MAX_TEXT_CHARS - len(tail))
    clean_tips = clean_part(tips, bad_sentences, tips_limit, keep_last=True)
    if len(clean_hook) < MIN_HOOK_CHARS or len(clean_tips) < MIN_TIPS_CHARS:
        return None
    return clean_hook, clean_tips + tail
