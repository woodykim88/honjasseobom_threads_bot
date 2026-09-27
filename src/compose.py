"""글 한 편 만들기: RSS 기사 후보 → 선별 → 본문 → 스레드(첫 글 + 답글) → 규칙·원문 대조 검수.

출처 줄(매체명·기사 링크)은 LLM이 아니라 코드가 붙인다 (빠뜨리거나 지어낼 수 없게).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from src import quality, selector
from src.history import HistoryEntry
from src.llm import LLMClient, load_prompt
from src.models import Candidate, ThreadPost

MAX_WRITE_ATTEMPTS = 2
MAX_ARTICLE_ATTEMPTS = 3  # 본문을 못 가져오거나 검수에 떨어지면 다음 순위 기사로


class PipelineError(Exception):
    """게시할 글을 만들지 못했을 때."""


@dataclass(frozen=True)
class Models:
    writer: str
    fast: str


@dataclass(frozen=True)
class Draft:
    key: str                  # 중복 방지 키 (기사 주소 해시)
    title: str                # 기록용 이름 (기사 제목)
    parts: tuple[str, ...]    # 첫 글, 답글 — 최종 게시 문구
    source_url: str

    @property
    def text(self) -> str:
        """기록·미리보기용: 파트를 구분선으로 이어 붙인 전체 글."""
        return '\n\n— — —\n\n'.join(self.parts)


def source_tail(article: Candidate) -> str:
    return f'\n\n📰 출처: {article.publisher}\n{article.link}'


def check_post(post: ThreadPost, tail: str) -> list[str]:
    issues = quality.part_issues('hook', post.hook) + quality.part_issues('tips', post.tips, tail)
    return issues + quality.rule_issues(f'{post.hook}\n{post.tips}')


def write_checked(llm: LLMClient, models: Models, article: Candidate, body: str) -> tuple[str, ...] | None:
    tail = source_tail(article)
    user_input = (f'매체: {article.publisher}\n기사 제목: {article.title}\n독자 포인트: {article.angle}\n'
                  f'--- 기사 본문 ---\n{body}')
    feedback: tuple[str, ...] = ()
    for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
        extra = ('\n\n이전 글이 자동 검수에서 탈락했어. 아래를 고쳐서 다시 써:\n' + '\n'.join(f'- {f}' for f in feedback)) if feedback else ''
        post = llm.parse(models.writer, load_prompt('writer'), user_input + extra, ThreadPost)
        issues = check_post(post, tail)
        if not issues:
            issues = quality.check_facts(llm, models.fast, f'{post.hook}\n{post.tips}', body)
        if not issues:
            print(f'[검수 통과] 시도 {attempt}')
            return post.hook.strip(), post.tips.strip() + tail
        print(f'[검수 탈락] 시도 {attempt}: ' + ' / '.join(issues))
        feedback = tuple(issues)
    return None


def compose(
    llm: LLMClient,
    models: Models,
    history: Sequence[HistoryEntry],
    load_candidates: Callable[[], list[Candidate]],
    fetch_body: Callable[[Candidate], str | None],
    today: str,
) -> Draft:
    """점수 높은 기사부터 본문을 읽어 글을 쓰고, 검수를 통과한 첫 글을 반환합니다."""
    candidates = selector.filter_candidates(load_candidates(), history)
    print(f'[후보] {len(candidates)}건')
    ranked = selector.rank_candidates(llm, models.fast, candidates, history, today)
    print(f'[선별] 기준 통과 {len(ranked)}건')
    for article in ranked[:MAX_ARTICLE_ATTEMPTS]:
        print(f'[기사 시도] {article.publisher}: {article.title}')
        body = fetch_body(article)
        if not body:
            continue
        parts = write_checked(llm, models, article, body)
        if parts:
            return Draft(article.doc_id, article.title, parts, article.link)
    raise PipelineError('게시할 글을 만들지 못했습니다 (쓸 만한 기사가 없거나 검수 탈락).')
