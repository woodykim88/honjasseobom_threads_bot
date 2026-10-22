from src import casual, schedule


def test_context_line_tells_time_of_day():
    line = casual.context_line(schedule.slot_datetime('2026-10-22T12:30'))
    assert '12:30' in line and '점심' in line


def test_daytime_post_rejects_night_words():
    noon = schedule.slot_datetime('2026-10-22T12:30')
    assert any('시간대' in i for i in casual.issues('목요일 밤엔 냉장고 문 열고 고민하게 되지? ㅋ', noon))
    assert any('시간대' in i for i in casual.issues('저녁엔 뭐 먹을지 벌써 고민돼?', noon))


def test_daytime_post_allows_neutral_or_future_words():
    noon = schedule.slot_datetime('2026-10-22T12:30')
    assert not any('시간대' in i for i in casual.issues('점심 메뉴 국물 vs 볶음, 너는 뭐 골라?', noon))


def test_evening_post_allows_night_words():
    evening = schedule.slot_datetime('2026-10-22T20:00')
    assert not any('시간대' in i for i in casual.issues('목요일 밤엔 냉장고 문 열고 고민하게 되지?', evening))


def test_living_cost_format_is_favored():
    picks = [casual.pick_format(f'2026-10-{d:02d}T12:30') for d in range(1, 31)]
    picks += [casual.pick_format(f'2026-11-{d:02d}T20:00') for d in range(1, 31)]
    living = sum('생활비' in p for p in picks)
    assert living > max(sum(p == f for p in picks) for f in casual.FORMATS if '생활비' not in f)
