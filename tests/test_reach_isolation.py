"""혼자써봄 조회수 급락 원인 좁히기 (2026-10-24): 10/25~26 토픽 태그 끔, 10/27~28 쿠팡 상품 글 쉼."""
from datetime import date

from src import compose, threads


def test_topic_tag_off_on_isolation_dates():
    assert threads._topic_tag(date(2026, 10, 25)) == '' and threads._topic_tag(date(2026, 10, 26)) == ''
    assert threads._topic_tag(date(2026, 10, 27)) == '자취' and threads._topic_tag(date(2026, 10, 24)) == '자취'


def test_product_off_on_isolation_dates():
    assert not compose.is_product_day(date(2026, 10, 27)) and not compose.is_product_day(date(2026, 10, 28))
    assert compose.is_product_day(date(2026, 10, 26)) and compose.is_product_day(date(2026, 10, 29))
