from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from src.llm import LLMClient
from src.models import Candidate, CandidateScore, SelectionResult
from src.providers import OpenAITextBackend

AT_20 = datetime(2026, 9, 26, 11, 2, tzinfo=timezone.utc)   # KST 20:02
AT_08 = datetime(2026, 9, 26, 23, 1, tzinfo=timezone.utc)   # KST 다음날 08:01


class FakeOpenAI:
    def __init__(self, responses: dict[str, list[Any]]) -> None:
        self._responses = {k: list(v) for k, v in responses.items()}
        self.requests: list[dict[str, Any]] = []
        self.responses = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        return SimpleNamespace(output_parsed=self._responses[kwargs['text_format'].__name__].pop(0))


def fake_llm(responses: dict[str, list[Any]]) -> tuple[LLMClient, FakeOpenAI]:
    client = FakeOpenAI(responses)
    return LLMClient(OpenAITextBackend(client), max_calls=16), client


ARTICLES = [
    Candidate('a1', '구독 해지 위약금 분쟁 늘어', '해지 위약금 분쟁이 1년 새 늘었다', '2026.09.26',
              'https://news.example/a1', '컨슈머치'),
    Candidate('a2', '세제 가격 올라', '세제 가격이 5% 올랐다', '2026.09.25', 'https://news.example/a2', '소비자경제'),
]
BODY = '구독 서비스 해지 위약금 분쟁이 1년 새 30% 늘었다. ' * 30
HOOK = '구독 해지하려다 위약금 폭탄 맞은 적 있음? 😵\n분쟁이 1년 새 30%나 늘었대. 정리는 댓글에 👇'
TIPS = '1. 가입할 때 해지 조건 캡처해 두기\n2. 약정 기간 끝나는 날 달력에 적기\n3. 분쟁 생기면 소비자상담센터부터\n저장해 두고 구독 정리할 때 꺼내 봐 🙌'
GOOD_BODY = HOOK + '\n' + TIPS


def selection(*scores):
    return SelectionResult(scores=[CandidateScore(index=i, score=s, reason='r', angle='포인트') for i, s in scores])


class Resp:
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status_code = status
        self._payload = payload
        self.content = b'1'

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))
