"""글 한 편 만들기.

- 뉴스 글: RSS 기사 후보 → 선별 → 본문 → 스레드(첫 글 + 답글) → 규칙·원문 대조 검수.
- 제품 글 (channel.PRODUCT_HOUR 슬롯만): 아직 안 올린 인포크 제휴 제품 → 스레드(첫 글 + 답글 2개). 다 올렸거나 실패하면 뉴스 글.

출처 줄·제휴 링크·광고 고지·교차 추천은 LLM이 아니라 코드가 붙인다 (빠뜨리거나 지어낼 수 없게).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from src import channel, patterns, quality, rescue, selector
from src.history import HistoryEntry
from src.llm import LLMClient, load_prompt
from src.models import Candidate, ThreadPost
from src.products import Product

MAX_WRITE_ATTEMPTS = 2
MAX_ARTICLE_ATTEMPTS = 3  # 본문을 못 가져오거나 검수에 떨어지면 다음 순위 기사로
COUPANG_DISCLOSURE = '이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.'
AFFILIATE_DISCLOSURE = '이 글은 제휴 링크를 포함하며, 구매 시 수수료를 받을 수 있어요.'
PRODUCT = 'product'
NEWS = 'news'


class PipelineError(Exception):
    """게시할 글을 만들지 못했을 때."""


@dataclass(frozen=True)
class Models:
    writer: str
    fast: str


@dataclass(frozen=True)
class Draft:
    key: str                  # 중복 방지 키 (기사 주소 해시 또는 제품 URL)
    title: str                # 기록용 이름 (기사 제목 또는 제품명)
    parts: tuple[str, ...]    # 첫 글, 답글(들) — 최종 게시 문구
    source_url: str
    kind: str = NEWS
    rescued: bool = False     # 검수를 통과하지 못해 문제 줄을 빼고 낸 글 (구제 발행)

    @property
    def text(self) -> str:
        """기록·미리보기용: 파트를 구분선으로 이어 붙인 전체 글."""
        return '\n\n— — —\n\n'.join(self.parts)


def wants_cross_promo(history: Sequence[HistoryEntry]) -> bool:
    """게시한 뉴스 글 CROSS_PROMO_EVERY개마다 한 번 교차 추천을 붙입니다."""
    if not channel.CROSS_PROMO or channel.CROSS_PROMO_EVERY <= 0:
        return False
    published = sum(1 for e in history if e.status == 'PUBLISHED' and e.seed != PRODUCT)
    return published % channel.CROSS_PROMO_EVERY == channel.CROSS_PROMO_EVERY - 1


def source_tail(article: Candidate, promo: bool = False) -> str:
    extra = f'\n\n{channel.CROSS_PROMO}' if promo else ''
    return f'\n\n📰 출처: {article.publisher}\n{article.link}{extra}'


def product_tail(product: Product) -> str:
    disclosure = COUPANG_DISCLOSURE if product.is_coupang else AFFILIATE_DISCLOSURE
    return f'\n\n👉 {product.name}\n{product.url}\n\n{disclosure}'


def check_post(post: ThreadPost, tail: str, kind: str = NEWS) -> list[str]:
    parts = [('hook', post.hook, ''), ('tips', post.tips, tail if kind == NEWS else '')]
    if kind == PRODUCT:
        parts.append(('pitch', post.pitch, tail))
    issues = [i for name, body, t in parts for i in quality.part_issues(name, body, t)]
    issues += quality.ending_issues(parts[-1][1])
    return issues + quality.rule_issues('\n'.join(body for _, body, _ in parts))


def assemble(post: ThreadPost, tail: str, kind: str) -> tuple[str, ...]:
    if kind == PRODUCT:
        return post.hook.strip(), post.tips.strip(), post.pitch.strip() + tail
    return post.hook.strip(), post.tips.strip() + tail


@dataclass(frozen=True)
class Attempt:
    """검수에 떨어진 뉴스 원고 (구제 발행 후보)."""
    article: Candidate
    post: ThreadPost
    tail: str
    issues: tuple[str, ...]
    bad_sentences: tuple[str, ...]


def write_checked(llm: LLMClient, models: Models, prompt: str, user_input: str, tail: str, kind: str,
                  source: str | None, article: Candidate | None = None) -> tuple[tuple[str, ...] | None, Attempt | None]:
    """(통과한 글, None) 또는 (None, 가장 나은 탈락 원고)를 반환합니다.

    source가 있으면(뉴스) 원문 대조 사실 검증까지 합니다. 제품 글은 제품명 밖의 사실을 규칙으로 막는다.
    """
    feedback: tuple[str, ...] = ()
    best: Attempt | None = None
    for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
        extra = ('\n\n이전 글이 자동 검수에서 탈락했어. 아래를 고쳐서 다시 써:\n' + '\n'.join(f'- {f}' for f in feedback)) if feedback else ''
        post = llm.parse(models.writer, load_prompt(prompt), user_input + extra, ThreadPost)
        issues = check_post(post, tail, kind)
        bad: list[str] = []
        if source is not None:
            fact_issues, bad = quality.fact_problems(llm, models.fast, f'{post.hook}\n{post.tips}', source)
            issues += fact_issues
        if not issues:
            print(f'[검수 통과] 시도 {attempt}')
            return assemble(post, tail, kind), None
        print(f'[검수 탈락] 시도 {attempt}: ' + ' / '.join(issues))
        feedback = tuple(issues)
        if article is not None and (best is None or len(issues) <= len(best.issues)):
            best = Attempt(article, post, tail, tuple(issues), tuple(bad))
    return None, best


def rescue_best(attempts: Sequence[Attempt]) -> Draft | None:
    """문제가 적은 원고부터 문제 줄을 빼 보고, 내용이 충분히 남는 첫 원고를 반환합니다."""
    for a in sorted(attempts, key=lambda a: len(a.issues)):
        parts = rescue.rescue(a.post.hook, a.post.tips, a.bad_sentences, a.tail)
        if parts:
            print(f'[구제 발행] {a.article.title} (문제 {len(a.issues)}건의 줄을 빼고 게시)')
            return Draft(a.article.doc_id, a.article.title, parts, a.article.link, rescued=True)
    return None


def next_product(products: Sequence[Product], history: Sequence[HistoryEntry]) -> Product | None:
    used = {e.doc_id for e in history if e.doc_id and e.status in ('PUBLISHED', 'PUBLISHING', 'SKIPPED')}
    ordered = list(reversed(products)) if channel.PRODUCT_FROM_END else list(products)
    return next((p for p in ordered if p.url not in used), None)


def compose_product(llm: LLMClient, models: Models, product: Product) -> Draft | None:
    user_input = f'제품명: {product.name}\n{patterns.pattern_brief(product.url, product=True)}'
    parts, _ = write_checked(llm, models, 'product', user_input, product_tail(product), PRODUCT, source=None)
    return Draft(product.url, product.name, parts, product.url, PRODUCT) if parts else None


def compose_news(
    llm: LLMClient, models: Models, history: Sequence[HistoryEntry],
    load_candidates: Callable[[], list[Candidate]], fetch_body: Callable[[Candidate], str | None], today: str,
) -> Draft:
    """점수 높은 기사부터 본문을 읽어 글을 쓰고, 검수를 통과한 첫 글을 반환합니다."""
    candidates = selector.filter_candidates(load_candidates(), history)
    print(f'[후보] {len(candidates)}건')
    ranked = selector.rank_candidates(llm, models.fast, candidates, history, today)
    print(f'[선별] 기준 통과 {len(ranked)}건')
    promo = wants_cross_promo(history)
    attempts: list[Attempt] = []
    for article in ranked[:MAX_ARTICLE_ATTEMPTS]:
        print(f'[기사 시도] {article.publisher}: {article.title}')
        body = fetch_body(article)
        if not body:
            continue
        user_input = (f'매체: {article.publisher}\n기사 제목: {article.title}\n독자 포인트: {article.angle}\n'
                      f'{patterns.pattern_brief(article.doc_id)}\n--- 기사 본문 ---\n{body}')
        parts, failed = write_checked(llm, models, 'writer', user_input, source_tail(article, promo), NEWS,
                                      source=body, article=article)
        if parts:
            return Draft(article.doc_id, article.title, parts, article.link)
        if failed:
            attempts.append(failed)
    draft = rescue_best(attempts)
    if draft:
        return draft
    raise PipelineError('게시할 글을 만들지 못했습니다 (읽을 수 있는 기사가 없음: RSS·기사 사이트 장애 가능성).')


def compose(
    llm: LLMClient,
    models: Models,
    history: Sequence[HistoryEntry],
    load_candidates: Callable[[], list[Candidate]],
    fetch_body: Callable[[Candidate], str | None],
    today: str,
    slot_hour: int | None = None,
    load_products: Callable[[], list[Product]] = lambda: [],
) -> Draft:
    """제품 슬롯이면 제품 추천을 먼저 시도하고, 올릴 제품이 없거나 실패하면 뉴스 글로 대신합니다."""
    if channel.PRODUCT_HOUR is not None and slot_hour == channel.PRODUCT_HOUR:
        product = next_product(load_products(), history)
        if product is None:
            print('[제품] 올릴 제품이 없어 뉴스 글로 대신합니다.')
        else:
            print(f'[제품] {product.name}')
            draft = compose_product(llm, models, product)
            if draft:
                return draft
    return compose_news(llm, models, history, load_candidates, fetch_body, today)
