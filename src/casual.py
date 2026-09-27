"""일상글: 하루 한 번(channel.CASUAL_HOUR 슬롯) 링크·광고 없는 짧은 대화형 글 (2026-09-27 사용자 결정).

정보·광고 글 사이에 섞여 계정이 광고만 올리는 곳으로 보이지 않게 하고, 댓글을 부른다.
지어낸 경험("어제 퇴근길에 ~했는데")은 쓰지 않는다: 사람인 척하는 자동 계정은 Meta 정책상 위험하다.
질문·밸런스 게임·날씨/요일/계절 한마디·채널 주제 공감글만 쓴다. 검수에 떨어져도 준비된 질문으로 반드시 올린다.
"""
from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from src import quality
from src.history import HistoryEntry
from src.llm import LLMClient, load_prompt

KIND = 'casual'
MAX_CHARS = 150
MAX_ATTEMPTS = 2
RECENT = 10
WEEKDAYS = '월화수목금토일'
SEASONS = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄', 6: '여름', 7: '여름', 8: '여름',
           9: '가을', 10: '가을', 11: '가을'}
FORMATS = ('누구나 한 줄로 답할 수 있는 질문', '두 가지 중 고르기 (A vs B)', '오늘 요일·계절에 맞춘 공감 한마디 + 질문',
           '채널 주제와 가까운 작은 공감 + 질문')


class CasualPost(BaseModel):
    text: str = Field(description='일상글 한 개, 30~120자, 물음표로 끝나는 질문 포함')


def context_line(now: datetime) -> str:
    return f'오늘: {now:%m월 %d일} {WEEKDAYS[now.weekday()]}요일, {SEASONS[now.month]}'


def issues(text: str) -> list[str]:
    found = quality.rule_issues(text)
    if len(text) > MAX_CHARS:
        found.append(f'{MAX_CHARS}자를 넘습니다 (현재 {len(text)}자). 더 짧게 쓰세요.')
    if '?' not in text:
        found.append('누구나 답할 수 있는 질문(물음표)을 넣으세요.')
    return found


def fallback(seed: str, questions: Sequence[str]) -> str:
    """AI 글이 두 번 다 떨어지면 준비된 질문 중 하나 (회차를 건너뛰지 않기 위해)."""
    return random.Random(seed).choice(questions)


def compose_casual(llm: LLMClient, model: str, history: Sequence[HistoryEntry], now: datetime, slot: str,
                   questions: Sequence[str]) -> tuple[str, bool]:
    """(글, 준비된 질문을 썼는지)를 반환합니다."""
    recent = [e.caption for e in history if e.seed == KIND and e.caption][-RECENT:]
    fmt = random.Random(slot).choice(FORMATS)
    user_input = (f'{context_line(now)}\n이번 형식: {fmt}\n'
                  '최근에 올린 일상글 (겹치지 않게):\n' + ('\n'.join(f'- {t}' for t in recent) or '(없음)'))
    feedback: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        extra = ('\n\n이전 글이 검수에서 떨어졌어. 고쳐서 다시 써:\n' + '\n'.join(f'- {f}' for f in feedback)) if feedback else ''
        text = llm.parse(model, load_prompt('casual'), user_input + extra, CasualPost).text.strip()
        feedback = issues(text)
        if not feedback:
            print(f'[일상글 통과] 시도 {attempt}')
            return text, False
        print(f'[일상글 탈락] 시도 {attempt}: ' + ' / '.join(feedback))
    return fallback(slot, questions), True
