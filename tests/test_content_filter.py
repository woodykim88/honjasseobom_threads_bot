"""모델 콘텐츠 필터에 걸린 기사는 건너뛰고 다음 기사로 (2026-10-24 건강노트 08:00 실패)."""
from src import compose, openai_fallback
from src.models import ThreadPost
from tests.helpers import ARTICLES, BODY, HOOK, TIPS, fake_llm, selection
from tests.test_threads_bot import OK_FACTS


class FilteredError(Exception):
    status_code = 400


FILTERED = FilteredError("Error code: 400 - The response was filtered due to the prompt triggering "
                         "Azure OpenAI's content management policy.")


def test_is_content_filtered():
    assert openai_fallback.is_content_filtered(FILTERED)
    assert not openai_fallback.is_content_filtered(FilteredError('Error code: 400 - invalid schema'))


def test_news_skips_filtered_article_and_uses_next(monkeypatch):
    llm, client = fake_llm({'SelectionResult': [selection((0, 9), (1, 8))],
                            'ThreadPost': [ThreadPost(hook=HOOK, tips=TIPS)], 'FactCheck': [OK_FACTS]})
    parse, calls = client._parse, []

    def flaky(**kwargs):
        calls.append(kwargs['text_format'].__name__)
        if calls.count('ThreadPost') == 1 and kwargs['text_format'] is ThreadPost:
            raise FILTERED
        return parse(**kwargs)

    client.responses.parse = flaky
    draft = compose.compose(llm, compose.Models('w', 'f'), (), lambda: list(ARTICLES), lambda a: BODY, '2026-09-26')
    assert draft.kind == compose.NEWS and draft.key == ARTICLES[1].doc_id
