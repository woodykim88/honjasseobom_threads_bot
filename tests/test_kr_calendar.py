from datetime import date

from src import casual, compose, kr_calendar as cal, schedule
from src.casual import CasualPost
from src.models import FactCheck, ThreadPost
from tests.helpers import ARTICLES, BODY, HOOK, TIPS, fake_llm, selection

MODELS = compose.Models('w', 'f')
SUNDAY_BEFORE_SUBSTITUTE = '2026-10-04T20:00'  # 내일 10/5 월요일은 개천절 대체공휴일


def test_substitute_holiday_is_day_off():
    assert cal.day_off_name(date(2026, 10, 5)) == '개천절 대체공휴일'
    assert cal.is_day_off(date(2026, 10, 3)) and not cal.is_day_off(date(2026, 10, 6))


def test_describe_sunday_before_substitute_monday():
    text = cal.describe(date(2026, 10, 4))
    assert '내일(10월 5일 월요일)은 개천절 대체공휴일' in text and '출근하지 않아' in text
    assert '내일은 출근' in cal.describe(date(2026, 10, 11))


def test_commute_claim_flagged_only_when_tomorrow_off():
    assert cal.commute_issues('내일 출근이면 오늘 일찍 쉬어야지', date(2026, 10, 4))
    assert not cal.commute_issues('내일 출근이면 오늘 일찍 쉬어야지', date(2026, 10, 11))
    assert not cal.commute_issues('월요일은 쉬는 날이라 출근 안 해서 좋아', date(2026, 10, 4))


def test_casual_context_has_calendar_fact_and_keeps_first_line():
    now = schedule.slot_datetime('2026-10-04T12:30')
    line = casual.context_line(now)
    assert line.startswith('오늘: 10월 04일 일요일, 가을')
    assert '달력 사실' in line and '어기지 마' in line and '개천절 대체공휴일' in line


def test_casual_issues_flag_commute_on_holiday_eve():
    now = schedule.slot_datetime('2026-10-04T12:30')
    text = '일요일 밤이라 내일 출근 걱정되지? 너는 뭐 해?'
    assert any('쉬는 날' in i for i in casual.issues(text, now))
    assert not any('쉬는 날' in i for i in casual.issues(text, schedule.slot_datetime('2026-10-11T12:30')))


def _news(tips: str):
    llm, client = fake_llm({'SelectionResult': [selection((0, 8))], 'ThreadPost': [ThreadPost(hook=HOOK, tips=tips)],
                            'FactCheck': [FactCheck(claims=[])]})
    draft = compose.compose(llm, MODELS, (), lambda: list(ARTICLES), lambda a: BODY, '2026-10-04',
                            slot=SUNDAY_BEFORE_SUBSTITUTE)
    return draft, client


def test_news_prompt_carries_calendar_fact():
    _, client = _news(TIPS)
    writer_input = next(r['input'] for r in client.requests if r['text_format'].__name__ == 'ThreadPost')
    assert '달력 사실' in writer_input and '개천절 대체공휴일' in writer_input


def test_news_commute_line_is_dropped_not_skipped():
    tips = TIPS.replace('2. 약정', '2. 내일 월요일 출근 전에 꼭 확인하기\n2. 약정')
    draft, _ = _news(tips)
    assert '출근' not in draft.text and draft.rescued
    assert '1. 가입할 때 해지 조건' in draft.parts[1]


def test_casual_rewrites_when_commute_claim_then_passes():
    bad = CasualPost(text='일요일 밤, 내일 출근 생각하면 잠 오냐? ㅋㅋ')
    good = CasualPost(text='연휴 하루 더 남았네, 오늘 뭐 먹을래? 🍜')
    llm, client = fake_llm({'CasualPost': [bad, good]})
    text, canned = casual.compose_casual(llm, 'w', (), schedule.slot_datetime('2026-10-04T12:30'), 'k', ['q?'])
    assert text == good.text and not canned and '쉬는 날' in client.requests[1]['input']
