"""기사 후보에서 이미 쓴 기사·민감 주제·비슷한 주제를 걸러내고, LLM으로 Threads 뉴스 적합도를 채점한다."""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from difflib import SequenceMatcher

from src.channel import SENSITIVE_PATTERNS
from src.history import HistoryEntry
from src.llm import LLMClient, load_prompt
from src.models import Candidate, SelectionResult

MIN_SCORE = 6
FALLBACK_MIN_SCORE = 4  # 기준을 넘는 기사가 없을 때의 하한 (안전 때문에 1~3점으로 막은 기사는 제외)
TITLE_SIMILARITY_THRESHOLD = 0.6
MAX_CANDIDATES = 60   # 선별 LLM 입력 상한 (최신 기사부터)
RECENT_TITLES = 20    # 최근에 쓴 주제 (중복 판단용)

_SENSITIVE_RE = re.compile('|'.join(SENSITIVE_PATTERNS)) if SENSITIVE_PATTERNS else None


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.replace(' ', ''), b.replace(' ', '')).ratio()


def is_sensitive(candidate: Candidate) -> bool:
    return bool(_SENSITIVE_RE and _SENSITIVE_RE.search(candidate.title))


def filter_candidates(candidates: Sequence[Candidate], history: Sequence[HistoryEntry]) -> list[Candidate]:
    """이미 쓴 기사, 민감 주제, 최근 글과 제목이 너무 비슷한 기사를 뺍니다. 최신 기사부터 정렬합니다."""
    used = {e.doc_id for e in history if e.doc_id}
    recent = [e.title for e in history if e.title][-RECENT_TITLES:]
    kept = []
    for c in sorted(candidates, key=lambda c: c.date, reverse=True):
        if c.doc_id in used:
            continue
        if is_sensitive(c):
            print(f'[차단] 민감 주제: {c.title[:50]}')
            continue
        if any(title_similarity(c.title, t) >= TITLE_SIMILARITY_THRESHOLD for t in recent):
            print(f'[차단] 최근 주제와 비슷함: {c.title[:50]}')
            continue
        kept.append(c)
    return kept[:MAX_CANDIDATES]


def format_candidates(candidates: Sequence[Candidate]) -> str:
    return '\n'.join(f'[{i}] {c.title} ({c.publisher}, {c.date})\n    {c.summary[:300]}'
                     for i, c in enumerate(candidates))


def rank_candidates(
    llm: LLMClient, model: str, candidates: Sequence[Candidate], history: Sequence[HistoryEntry],
    today: str, min_score: int = MIN_SCORE, fallback_min_score: int = FALLBACK_MIN_SCORE,
) -> list[Candidate]:
    """min_score 이상인 후보를 점수 높은 순으로 반환합니다. 하나도 없으면 fallback_min_score 이상으로 낮춥니다.
    회차를 건너뛰지 않기 위해서다. 독자 포인트(angle)를 후보에 붙입니다."""
    if not candidates:
        return []
    titles = [e.title for e in history if e.title][-RECENT_TITLES:]
    recent = '\n'.join(f'- {t}' for t in titles) or '(아직 없음)'
    user_input = f'오늘 날짜: {today}\n\n최근에 올린 글 (같은 주제 피하기):\n{recent}\n\n후보 목록:\n{format_candidates(candidates)}'
    result = llm.parse(model, load_prompt('selector'), user_input, SelectionResult)
    best: dict[int, tuple[int, Candidate]] = {}
    for s in result.scores:
        if 0 <= s.index < len(candidates) and s.score >= fallback_min_score and s.index not in best:
            best[s.index] = (s.score, replace(candidates[s.index], angle=s.angle.strip()))
    ordered = sorted(best.values(), key=lambda pair: pair[0], reverse=True)
    passed = [c for score, c in ordered if score >= min_score]
    if not passed and ordered:
        print(f'[선별] {min_score}점 넘는 기사가 없어 {fallback_min_score}점 이상으로 낮춥니다.')
    return passed or [c for _, c in ordered]
