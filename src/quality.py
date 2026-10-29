"""게시 전 자동 검수: 길이, 과장 표현(채널별), 1인칭 사용 후기 표현, 기사 본문 대조 사실 검증."""
from __future__ import annotations

import re

from src.channel import BANNED_WORDS
from src.llm import LLMClient, load_prompt
from src.models import FactCheck
from src.threads import MAX_TEXT_CHARS

LIMITS = {'hook': 200, 'tips': 470, 'pitch': 220}  # 첫 글은 100자 안팎으로 짧게 (노하우: 긴 글은 광고처럼 보임)
# "진짜 써 본 것처럼" 보이는 1인칭 사용 후기 표현 (추천·큐레이션 톤만 허용)
FIRST_PERSON_PATTERNS = (
    r'(먹어|써|사용해|입어|신어|마셔|발라|해)\s?(봤|보니|봤는데|봤더니)', r'내가\s?(먹|써|샀|사용|입|신|마셔)',
    r'직접\s?(먹|써|사용|구매)', r'재구매', r'인생템', r'실사용', r'솔직\s?후기', r'내돈내산',
)
_FIRST_PERSON_RE = re.compile('|'.join(FIRST_PERSON_PATTERNS))
_LINK_RE = re.compile(r'https?://|www\.')
# 2026-10-30 조사 교훈: Meta는 "리포스트해·태그해·댓글 달아" 같은 직접 참여 부탁을 강등하고, 잦으면 프로필 추천을 막는다.
ENGAGEMENT_ASK = re.compile(r'(리포스트|태그|공유|좋아요|팔로우|댓글)\s?(해\s?줘|해\s?둬|해\s?둠|해\s?두|ㄱㄱ|눌러|달아|남겨|부탁|하면)')
# AI가 쓴 티가 나는 보고서 말투 (요약체는 스크롤을 넘기게 만든다)
AI_TONE = ('알아보겠습니다', '살펴보겠습니다', '정리해 드릴게요', '정리해 드릴께요', '결론적으로', '요약하자면')
# 사실검증의 생각하는 양 (None = 모델 기본값). 9/28 'low'로 해 봤더니 후킹 문장·비유까지 '근거 없는 사실'로
# 잡아 원고 재작성(비싼 원고 모델 호출)이 늘어서 기본값으로 되돌렸다.
CHECK_EFFORT: str | None = None


def part_issues(name: str, body: str, tail: str = '') -> list[str]:
    """한 파트(첫 글·답글)의 길이 검사. tail은 코드가 그 파트에 붙일 링크·고지·출처."""
    issues = []
    if not body.strip():
        issues.append(f'{name}이(가) 비어 있습니다.')
    if len(body) > LIMITS[name]:
        issues.append(f'{name}이(가) {LIMITS[name]}자를 넘습니다 (현재 {len(body)}자). 더 짧게 쓰세요.')
    if len(body) + len(tail) > MAX_TEXT_CHARS:
        issues.append(f'{name}에 링크·안내 문구까지 합치면 {MAX_TEXT_CHARS}자를 넘습니다. 줄이세요.')
    return issues


def ending_issues(tips: str) -> list[str]:
    """답글 마지막 줄은 쉬운 질문으로 끝나야 한다 (댓글 유도)."""
    lines = [ln for ln in tips.strip().splitlines() if ln.strip()]
    if not lines or '?' not in lines[-1]:
        return ['답글 마지막 줄을 누구나 한 줄로 답할 수 있는 가벼운 질문(물음표)으로 끝내세요.']
    return []


def rule_issues(body: str, tail: str = '') -> list[str]:
    """글 전체(모든 파트를 합친 본문)의 표현 검사."""
    issues = []
    if not body.strip():
        issues.append('본문이 비어 있습니다.')
    banned = [w for w in BANNED_WORDS if w in body]
    if banned:
        issues.append(f'과장·단정 표현을 빼세요: {", ".join(banned)}')
    found = _FIRST_PERSON_RE.search(body)
    if found:
        issues.append(f'써 본 것처럼 보이는 1인칭 후기 표현("{found.group(0)}")을 빼고 뉴스 전달 톤으로 쓰세요.')
    if _LINK_RE.search(body):
        issues.append('본문에 링크를 넣지 마세요 (코드가 붙입니다).')
    if body.count('#') > 0:
        issues.append('해시태그는 쓰지 마세요.')
    ask = ENGAGEMENT_ASK.search(body)
    if ask:
        issues.append(f'직접 참여 부탁("{ask.group(0)}")을 빼세요. Meta가 노출을 줄입니다. 공감·질문으로만 반응을 부르세요.')
    tone = [w for w in AI_TONE if w in body]
    if tone:
        issues.append(f'보고서·AI 말투를 빼고 친구한테 말하듯 쓰세요: {", ".join(tone)}')
    return issues


def fact_problems(llm: LLMClient, model: str, body: str, source: str) -> tuple[list[str], list[str]]:
    """(탈락 사유, 근거 없는 문장). 문장 목록은 구제 발행에서 뺄 줄을 찾는 데 쓴다."""
    user_input = f'--- 기사 본문 ---\n{source}\n\n--- Threads 글 ---\n{body}'
    result = llm.parse(model, load_prompt('factcheck'), user_input, FactCheck, effort=CHECK_EFFORT)
    bad = [c for c in result.claims if c.kind == 'unsupported_fact']
    return [f'원문에 근거 없는 사실: "{c.sentence}" ({c.reason})' for c in bad], [c.sentence for c in bad]


def check_facts(llm: LLMClient, model: str, body: str, source: str) -> list[str]:
    return fact_problems(llm, model, body, source)[0]
