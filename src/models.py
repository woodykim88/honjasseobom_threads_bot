"""기사 후보와 LLM 구조화 응답 스키마."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Candidate:
    """언론사 공식 RSS 기사. 사실만 근거로 쓰고 문장은 새로 쓴다 (출처 줄은 코드가 붙인다)."""

    doc_id: str          # 기사 주소의 해시 12자 (중복 방지 키)
    title: str
    summary: str         # RSS 요약문 (선별 판단용)
    date: str            # 2026.09.27
    link: str
    publisher: str
    angle: str = ''      # 선별 LLM이 붙인 "독자가 얻을 포인트"


class CandidateScore(BaseModel):
    index: int = Field(description='후보 목록의 번호')
    score: int = Field(description='Threads 뉴스 적합도 1~10점')
    reason: str = Field(description='점수 근거 한 문장')
    angle: str = Field(description='독자가 오늘 바로 써먹을 포인트 30자 내외')


class SelectionResult(BaseModel):
    scores: list[CandidateScore]


class ThreadPost(BaseModel):
    """스레드 이어쓰기: 첫 글(후킹) → 답글(자세히 정리) → (제품이면) 답글(추천). 출처·링크·고지는 코드가 붙인다."""

    hook: str = Field(description='첫 글: 궁금하게 만드는 도입 + 핵심 사실 하나, 150~300자')
    tips: str = Field(description='답글: 기사 내용을 번호 매겨 3~5개로 정리 + 마무리 한마디, 250~450자')
    pitch: str = Field(default='', description='제품 글만: 두 번째 답글의 추천 1~2줄 + 질문, 최대 200자 (뉴스 글은 빈 문자열)')


ClaimKind = Literal['supported_fact', 'unsupported_fact', 'general_advice']


class ClaimCheck(BaseModel):
    sentence: str = Field(description='검사한 문장 (짧게 인용)')
    kind: ClaimKind = Field(description='supported_fact / unsupported_fact / general_advice')
    reason: str = Field(description='판단 근거 한 문장')


class FactCheck(BaseModel):
    claims: list[ClaimCheck] = Field(description='글 속 문장의 분류 결과')
