"""계산기 연결 글 (2026-11-16 사용자 결정): 혼자써봄을 정보마스터 계산기(tools.woodyway88.com) 유입 창구로 쓴다.

channel.TOOL_HOURS 슬롯(12:30)에 하루 1편. 첫 글은 링크 없는 생활비 공감 질문(조회가 가장 잘 나오는 형식),
답글에 코드가 계산기 주소(utm 포함)를 붙인다. Threads는 첫 글 링크를 덜 퍼뜨리는 경향이 있어 답글에만 둔다.
2주 시험(~11/30): GA utm_source=threads 유입이 거의 없으면 혼자써봄도 중단한다.
"""
from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import BaseModel, Field

from src import casual
from src.history import HistoryEntry
from src.llm import LLMClient, load_prompt

KIND = 'tool'
SITE = 'https://tools.woodyway88.com'
UTM = 'utm_source=threads&utm_medium=social&utm_campaign=honjasseobom'
RECENT_SKIP = 7       # 최근 계산기 글 7편에 쓴 계산기는 다시 고르지 않는다
SEASON_WEIGHT = 5     # 제철 계산기(난방·연말정산 등)를 연중 계산기보다 이만큼 자주
MAX_ATTEMPTS = 2
BANNED = ('http', 'www.', '계산기', '링크', '클릭', '주소')


@dataclass(frozen=True)
class Tool:
    slug: str
    topic: str                 # 글감 설명 (모델에게 주는 소재)
    cta: str                   # 답글 문구 (주소 앞)
    fallback: str              # 모델 글이 두 번 다 떨어지면 쓸 준비된 질문
    months: tuple[int, ...] = ()  # 제철 달. 비어 있으면 연중


TOOLS: tuple[Tool, ...] = (
    Tool('heater-electricity-cost-calculator', '전기히터·온풍기·전기장판 한 달 전기요금',
         '내 난방기 한 달 전기세, 와트랑 시간만 넣으면 바로 나와', '전기장판 vs 히터, 너는 겨울에 뭐 켜고 버텨?', (11, 12, 1, 2)),
    Tool('year-end-tax-calculator', '연말정산 환급액 (13월의 월급 vs 토해내기)',
         '올해 연말정산 환급, 연봉이랑 카드값으로 미리 계산해 봐', '연말정산 너는 받는 파야 토해내는 파야?', (11, 12, 1, 2)),
    Tool('card-deduction-calculator', '연말정산 신용카드·체크카드 공제 (남은 두 달 카드 전략)',
         '카드 공제 25% 문턱 넘었는지, 체크카드로 바꾸면 얼마 더 받는지 확인해 봐', '연말엔 신용카드파 vs 체크카드파?', (10, 11, 12)),
    Tool('annual-leave-calculator', '연말 남은 연차 일수·연차수당',
         '입사일만 넣으면 내 연차 일수랑 연차수당 나와', '올해 남은 연차 몇 개야?', (11, 12)),
    Tool('car-tax-prepay-calculator', '1월 자동차세 연납 할인',
         '자동차세 1월에 한 번에 내면 얼마 아끼는지 계산해 봐', '자동차세 한 번에 내는 파 vs 나눠 내는 파?', (12, 1)),
    Tool('appliance-electricity-cost-calculator', '냉장고·건조기·식기세척기 같은 가전 한 달 전기세',
         '우리 집 가전 한 달 전기세, 하나씩 넣어 보면 범인이 나와', '우리 집 전기 먹는 하마 1위는 뭐야?'),
    Tool('salary-take-home-calculator', '연봉 실수령액 (월급에서 세금·4대보험 빠지는 돈)',
         '연봉 넣으면 통장에 실제로 꽂히는 월급 나와', '월급날 통장 보고 첫마디 뭐야?'),
    Tool('transit-refund-calculator', '대중교통비 환급 (모두의카드)',
         '한 달 교통비 넣으면 모두의카드로 얼마 돌려받는지 나와', '한 달 교통비 얼마쯤 나와?'),
    Tool('weekly-holiday-pay-calculator', '알바 주휴수당',
         '시급이랑 근무시간만 넣으면 주휴수당 바로 나와', '알바할 때 주휴수당 제대로 받아 봤어?'),
    Tool('jeonse-loan-interest-calculator', '전세대출 이자 (월세로 치면 얼마인지)',
         '전세대출 이자, 월세로 바꾸면 얼마인지까지 비교해 봐', '전세파 vs 월세파, 너는 어느 쪽이야?'),
    Tool('freelancer-3-3-tax-calculator', '프리랜서 3.3% 떼고 남는 돈',
         '3.3% 떼고 실제 받는 돈, 5월 환급 예상까지 나와', '프리랜서 입금 알림 볼 때 첫 감정은?'),
    Tool('unemployment-benefit-calculator', '실업급여 하루 얼마·몇 개월',
         '실업급여 하루 얼마, 몇 달 받는지 바로 나와', '퇴사하면 제일 먼저 하고 싶은 거 뭐야?'),
    Tool('income-tax-interim-prepayment-calculator', '11월 종합소득세 중간예납 고지서 (11월 30일 마감, 추계액 신고)',
         '중간예납 고지서 금액이랑 추계액 신고 중 뭐가 나은지 바로 비교돼', '11월에 세금 고지서 받아 본 사람 있어?', (11,)),
    Tool('minimum-wage-calculator', '2027 최저임금 오르면 내 월급 얼마나 바뀌는지',
         '주 근무시간 넣으면 2026·2027 최저임금 월급 바로 비교돼', '내년 최저시급 1만 700원, 체감돼?', (12, 1)),
    Tool('severance-pay-calculator', '연말·연초 퇴사 전 퇴직금',
         '입사일이랑 월급 넣으면 퇴직금 대략 얼마인지 나와', '퇴사 타이밍, 연말 vs 보너스 받고?', (12, 1, 2)),
    Tool('meeting-cost-calculator', '회의 한 번에 드는 돈 (참석자 연봉 × 시간)',
         '오늘 회의 한 번에 회사 돈 얼마 썼는지 계산해 봐', '오늘 회의 몇 개 들어갔어?'),
)


class ToolPost(BaseModel):
    text: str = Field(description='공감글 한 개, 30~120자, 물음표로 끝나는 질문 포함, 링크 없음')


def tool_url(tool: Tool) -> str:
    return f'{SITE}/{tool.slug}/?{UTM}'


def reply_text(tool: Tool) -> str:
    return f'{tool.cta} 👉 {tool_url(tool)}'


def _in_season(tool: Tool, month: int) -> bool:
    return not tool.months or month in tool.months


def pick_tool(history: Sequence[HistoryEntry], day: date, slot: str) -> Tool:
    """최근에 쓴 계산기를 빼고, 제철 계산기를 SEASON_WEIGHT배로 뽑는다. 다 썼으면 제철 전체에서."""
    recent = [e.doc_id for e in history if e.seed == KIND and e.doc_id][-RECENT_SKIP:]
    season = [t for t in TOOLS if _in_season(t, day.month)]
    fresh = [t for t in season if f'{KIND}:{t.slug}' not in recent] or season
    weights = [SEASON_WEIGHT if t.months else 1 for t in fresh]
    return random.Random(slot).choices(fresh, weights=weights)[0]


def issues(text: str, now: datetime) -> list[str]:
    found = casual.issues(text, now)
    found += [f'"{w}"는 쓰지 마 (주소는 코드가 답글에 붙여).' for w in BANNED if w in text]
    return found


def compose_tool(llm: LLMClient, model: str, history: Sequence[HistoryEntry], now: datetime,
                 slot: str) -> tuple[Tool, str, bool]:
    """(계산기, 첫 글, 준비된 질문을 썼는지)."""
    tool = pick_tool(history, now.date(), slot)
    recent = [e.caption.split('\n')[0] for e in history if e.seed == KIND and e.caption][-RECENT_SKIP:]
    user_input = (f'{casual.context_line(now)}\n이번 소재: {tool.topic}\n'
                  '최근 계산기 글 첫 줄 (겹치지 않게):\n' + ('\n'.join(f'- {t}' for t in recent) or '(없음)'))
    feedback: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        extra = ('\n\n이전 글이 검수에서 떨어졌어. 고쳐서 다시 써:\n' + '\n'.join(f'- {f}' for f in feedback)) if feedback else ''
        text = llm.parse(model, load_prompt('tool'), user_input + extra, ToolPost).text.strip()
        feedback = issues(text, now)
        if not feedback:
            print(f'[계산기 글 통과] {tool.slug} 시도 {attempt}')
            return tool, text, False
        print(f'[계산기 글 탈락] 시도 {attempt}: ' + ' / '.join(feedback))
    return tool, tool.fallback, True
