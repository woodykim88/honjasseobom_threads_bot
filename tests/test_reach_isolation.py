"""조회수 원인 좁히기용 쉬는 날 설정 (2026-10-24 도입, 10/30 시험 종료 후 빈 값): 넣은 날만 토픽 태그·상품 글을 끈다."""
from datetime import date

from src import channel, compose, threads


def test_topic_tag_off_on_isolation_dates(monkeypatch):
    monkeypatch.setattr(channel, 'TOPIC_TAG_OFF_DATES', ('2026-10-25',))
    assert threads._topic_tag(date(2026, 10, 25)) == ''
    assert threads._topic_tag(date(2026, 10, 26)) == '자취'


def test_product_off_on_isolation_dates(monkeypatch):
    monkeypatch.setattr(channel, 'PRODUCT_OFF_DATES', ('2026-10-27',))
    assert not compose.is_product_day(date(2026, 10, 27))
    assert compose.is_product_day(date(2026, 10, 28))


def test_isolation_experiment_finished():
    assert channel.TOPIC_TAG_OFF_DATES == () and channel.PRODUCT_OFF_DATES == ()
