from datetime import datetime

import pytest

from scripts import due_check
from src import patterns, channel, collector, commands, compose, history, notifier, post, quality, schedule, selector, state, threads, token_refresh
from src.models import ClaimCheck, FactCheck, ThreadPost
from src.threads import ThreadsClient, ThreadsConfig, ThreadsError
from tests.helpers import AT_20, ARTICLES, BODY, GOOD_BODY, HOOK, TIPS, Resp, fake_llm, selection

POST = ThreadPost(hook=HOOK, tips=TIPS)
OK_FACTS = FactCheck(claims=[])
MODELS = compose.Models('w', 'f')
NOW = datetime(2026, 9, 27, 9, 0, tzinfo=schedule.KST)

RSS = '''<?xml version="1.0"?><rss><channel>
<item><title>구독 해지 위약금 분쟁 늘어</title><link>https://news.example/1</link>
<pubDate>Sat, 26 Sep 2026 08:00:00 +0900</pubDate><description>&lt;p&gt;분쟁이 늘었다&lt;/p&gt;</description></item>
<item><title>[포토] 행사 현장</title><link>https://news.example/2</link><pubDate>2026-09-26 09:00:00</pubDate></item>
<item><title>오래된 기사</title><link>https://news.example/3</link><pubDate>2026-09-01 09:00:00</pubDate></item>
</channel></rss>'''


# --- 수집 ---

def test_parse_feed_keeps_recent_and_drops_excluded_titles():
    items = collector.parse_feed(RSS, channel.Feed('매체', 'u'), NOW)
    assert [c.title for c in items] == ['구독 해지 위약금 분쟁 늘어']
    assert items[0].summary == '분쟁이 늘었다' and items[0].date == '2026.09.26' and items[0].publisher == '매체'
    assert items[0].doc_id == collector.doc_id_for('https://news.example/1')


def test_fetch_candidates_survives_one_broken_feed():
    import requests

    def get(url):
        if url == 'bad':
            raise requests.ConnectionError()
        return RSS
    feeds = (channel.Feed('나쁨', 'bad'), channel.Feed('좋음', 'good'))
    assert len(collector.fetch_candidates(get, NOW, feeds, sleep=lambda s: None)) == 1


def test_channel_config_is_complete():
    assert channel.NAME and channel.HANDLE and channel.CMD_PREFIX and channel.FEEDS
    assert all(f.url.startswith('https://') for f in channel.FEEDS)
    assert notifier.PREFIX == f'[Threads {channel.NAME}] '


# --- 선별 ---

def test_filter_candidates_drops_used_and_similar():
    past = (history.HistoryEntry('s1', history.PUBLISHED, title='세제 가격 올라요', doc_id='x'),)
    used = (history.HistoryEntry('s0', history.PUBLISHED, doc_id='a1'),)
    assert selector.filter_candidates(ARTICLES, used + past) == []
    assert [c.doc_id for c in selector.filter_candidates(ARTICLES, ())] == ['a1', 'a2']


def test_rank_candidates_orders_by_score_and_applies_threshold():
    llm, _ = fake_llm({'SelectionResult': [selection((0, 6), (1, 9))]})
    ranked = selector.rank_candidates(llm, 'f', ARTICLES, (), '2026-09-27')
    assert [c.doc_id for c in ranked] == ['a2', 'a1'] and ranked[0].angle == '포인트'
    llm, _ = fake_llm({'SelectionResult': [selection((0, 3))]})
    assert selector.rank_candidates(llm, 'f', ARTICLES, (), '2026-09-27') == []
    llm, _ = fake_llm({'SelectionResult': [selection((0, 3), (1, 5))]})  # 6점 넘는 기사가 없으면 4점 이상으로
    assert [c.doc_id for c in selector.rank_candidates(llm, 'f', ARTICLES, (), '2026-09-27')] == ['a2']


# --- 검수 규칙 ---

def test_rule_issues_blocks_first_person_hype_links_and_length():
    assert quality.rule_issues(GOOD_BODY) == []
    assert any('1인칭' in i for i in quality.rule_issues('어제 써봤는데 괜찮았어'))
    assert any('과장' in i for i in quality.rule_issues('무조건 확인해'))
    assert any('링크' in i for i in quality.rule_issues('여기 https://x.com'))
    assert any('200자' in i for i in quality.part_issues('hook', '가' * 201))
    assert any('500자' in i for i in quality.part_issues('tips', '가' * 400, '나' * 150))
    assert quality.ending_issues(TIPS) == [] and quality.ending_issues('1. 정리\n저장해 둬')


def test_patterns_pick_two_plus_question_and_no_fake_personas():
    picked = patterns.pick_patterns('a1')
    assert len(picked) == 3 and picked[-1] == patterns.ALWAYS and picked == patterns.pick_patterns('a1')
    assert not any(w in p for p in patterns.PATTERNS for w in ('따라 샀', '스친', '얼떨결'))


# --- 글 만들기 ---

def run_compose(responses, bodies=None, history_=()):
    llm, client = fake_llm(responses)
    bodies = bodies or {}
    draft = compose.compose(llm, MODELS, history_, lambda: list(ARTICLES), lambda a: bodies.get(a.doc_id, BODY),
                            '2026-09-27')
    return draft, client


def test_compose_writes_top_article_with_source_tail():
    draft, client = run_compose({'SelectionResult': [selection((0, 8), (1, 7))], 'ThreadPost': [POST],
                                 'FactCheck': [OK_FACTS]})
    assert draft.key == 'a1' and draft.parts[0] == HOOK and len(draft.parts) == 2
    assert draft.parts[1].endswith('📰 출처: 컨슈머치\nhttps://news.example/a1')
    assert 'https://' not in draft.parts[0]
    assert len(client.requests) == 3


def test_compose_rewrites_after_fact_fail():
    bad = FactCheck(claims=[ClaimCheck(sentence='50% 늘었대', kind='unsupported_fact', reason='숫자 다름')])
    draft, client = run_compose({'SelectionResult': [selection((0, 8))], 'ThreadPost': [POST, POST],
                                 'FactCheck': [bad, OK_FACTS]})
    assert draft.key == 'a1' and '자동 검수에서 탈락' in client.requests[3]['input']


def test_compose_skips_article_without_body():
    draft, _ = run_compose({'SelectionResult': [selection((0, 9), (1, 8))], 'ThreadPost': [POST],
                            'FactCheck': [OK_FACTS]}, bodies={'a1': None})
    assert draft.key == 'a2'


def test_compose_raises_without_good_article():
    with pytest.raises(compose.PipelineError):
        run_compose({'SelectionResult': [selection((0, 2), (1, 1))]})


# --- 텔레그램 명령 ---

def test_commands_use_channel_prefix():
    p = channel.CMD_PREFIX
    new, notes = commands.apply_commands(state.State(), [commands.Command(1, f'/{p}_stop')], 's')
    assert new.paused and notes
    new, _ = commands.apply_commands(new, [commands.Command(1, f'/{p}_stop'), commands.Command(2, f'/{p}_resume')], 's')
    assert not new.paused and new.handled_updates == (1, 2)
    assert '/th_stop' not in commands.COMMANDS


# --- Threads API ---

class Graph:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, params):
        self.calls.append((method, url, dict(params)))
        for key, resp in self.routes.items():
            if key in url:
                return resp
        raise AssertionError(url)


def client(routes):
    graph = Graph(routes)
    return ThreadsClient(ThreadsConfig('u1', 'secret'), request=graph, sleep=lambda s: None), graph


def test_threads_client_create_publish_permalink():
    c, graph = client({'threads_publish': Resp(200, {'id': 'm1'}), '/threads': Resp(200, {'id': 'box'}),
                       'm1': Resp(200, {'permalink': 'https://threads/p/1'})})
    assert c.create_text('hi') == 'box' and c.publish('box') == 'm1' and c.permalink('m1') == 'https://threads/p/1'
    assert graph.calls[0][2]['media_type'] == 'TEXT' and graph.calls[0][2]['access_token'] == 'secret'


def test_threads_client_errors():
    c, _ = client({'/threads': Resp(400, {'error': {'message': 'bad token', 'code': 190}})})
    with pytest.raises(ThreadsError) as info:
        c.create_text('hi')
    assert info.value.fatal and 'secret' not in str(info.value)
    with pytest.raises(ThreadsError, match='500자'):
        c.create_text('가' * 501)


# --- 게시 작업 ---

OK_ROUTES = {'threads_publish': Resp(200, {'id': 'm1'}), '/threads': Resp(200, {'id': 'box'}),
             'm1': Resp(200, {'permalink': 'https://threads/p/1'})}
ENV = {'PUBLISH_TIMES': '08:00,20:00'}
GOOD_RUN = {'SelectionResult': [selection((0, 8))], 'ThreadPost': [POST], 'FactCheck': [OK_FACTS]}


def deps(graph_routes, responses, request=None):
    c, graph = client(graph_routes)
    if request is not None:
        c = ThreadsClient(ThreadsConfig('u1', 'secret'), request=request, sleep=lambda s: None)
    backend = fake_llm(responses)[0]._backend
    return post.PostDeps(backend, MODELS, c, lambda: list(ARTICLES), lambda a: BODY), graph


def test_run_post_publishes_once_with_reply():
    d, graph = deps(OK_ROUTES, GOOD_RUN)
    assert post.run_post(ENV, d, None, AT_20).outcome == 'success'
    entry = history.find(history.load_history(), '2026-09-26T20:00')
    assert entry.status == history.PUBLISHED and entry.doc_id == 'a1' and entry.permalink == 'https://threads/p/1'
    creates = [p for m, u, p in graph.calls if u.endswith('/threads')]
    assert len(creates) == 2 and 'reply_to_id' not in creates[0] and creates[1]['reply_to_id'] == 'm1'
    assert post.run_post(ENV, d, None, AT_20).outcome == 'skipped'  # 같은 슬롯 두 번 게시 안 함


def test_run_post_keeps_publishing_state_on_publish_error():
    routes = {**OK_ROUTES, 'threads_publish': Resp(500, {'error': {'message': 'timeout', 'code': 2}})}
    d, _ = deps(routes, GOOD_RUN)
    post.run_post(ENV, d, None, AT_20)
    assert history.find(history.load_history(), '2026-09-26T20:00').status == post.PUBLISHING


def test_run_post_respects_pause_and_skip():
    d, graph = deps(OK_ROUTES, {})
    assert post.run_post({**ENV, 'PAUSED': 'true'}, d, None, AT_20).outcome == 'skipped'
    state.save_state(state.skip(state.State(), '2026-09-26T20:00'))
    post.run_post(ENV, d, None, AT_20)
    assert history.find(history.load_history(), '2026-09-26T20:00').status == history.SKIPPED and graph.calls == []


def test_run_post_records_failure_when_no_article():
    d, graph = deps(OK_ROUTES, {'SelectionResult': [selection((0, 1))]})
    assert post.run_post(ENV, d, None, AT_20).outcome == 'failed'
    assert history.find(history.load_history(), '2026-09-26T20:00').status == history.FAILED and graph.calls == []


def test_reply_failure_keeps_main_post_published_with_note():
    class Flaky(Graph):
        def __call__(self, method, url, params):
            if url.endswith('/threads') and params.get('reply_to_id'):
                return Resp(400, {'error': {'message': 'reply blocked', 'code': 100}})
            return super().__call__(method, url, params)
    d, _ = deps(OK_ROUTES, GOOD_RUN, request=Flaky(OK_ROUTES))
    post.run_post(ENV, d, None, AT_20)
    entry = history.find(history.load_history(), '2026-09-26T20:00')
    assert entry.status == history.PUBLISHED and '답글 1/1 게시 실패' in entry.note


def test_due_check():
    assert due_check.is_due(AT_20, ((8, 0), (20, 0)), ())
    done = (history.HistoryEntry('2026-09-26T20:00', history.PUBLISHED),)
    assert not due_check.is_due(AT_20, ((8, 0), (20, 0)), done)


def test_token_refresh_saves_without_printing(capsys):
    saved = {}
    r = token_refresh.run_refresh({'THREADS_ACCESS_TOKEN': 'old'}, None, refresh=lambda t: ('new-secret', 60 * 86400),
                                  set_secret=lambda n, v: saved.update({n: v}))
    assert r.outcome == 'success' and saved == {'THREADS_ACCESS_TOKEN': 'new-secret'}
    assert 'new-secret' not in capsys.readouterr().out


def test_refresh_token_api():
    graph = Graph({'refresh_access_token': Resp(200, {'access_token': 'n', 'expires_in': 100})})
    assert threads.refresh_token('o', request=graph) == ('n', 100)
    assert graph.calls[0][2]['grant_type'] == 'th_refresh_token'


# --- 제휴 제품 추천·교차 추천 (channel 설정으로 켜고 끔) ---

from src import products as products_mod  # noqa: E402

PRODUCTS = [products_mod.Product('오징어 짬뽕', 'https://link.coupang.com/a/1'),
            products_mod.Product('백색소음기', 'https://link.inpock.co.kr/x')]
PRODUCT_POST = ThreadPost(hook=HOOK, tips=TIPS, pitch='잠귀 밝은 사람한테 백색소음기 딱이야\n너는 잠귀 밝은 편이야?')


@pytest.fixture
def product_channel(monkeypatch):
    from src.llm import PROMPTS_DIR
    if not (PROMPTS_DIR / 'product.md').exists():
        pytest.skip('이 채널은 제품 추천 프롬프트가 없음 (제품 추천을 쓰지 않는 채널)')
    monkeypatch.setattr(channel, 'PRODUCT_HOUR', 20)
    monkeypatch.setattr(channel, 'PRODUCT_FROM_END', True)


def test_product_slot_picks_from_end_with_disclosure(product_channel):
    llm, client = fake_llm({'ThreadPost': [PRODUCT_POST]})
    draft = compose.compose(llm, MODELS, (), lambda: list(ARTICLES), lambda a: BODY, '2026-09-27', 20,
                            lambda: list(PRODUCTS))
    assert draft.kind == compose.PRODUCT and draft.key == PRODUCTS[1].url and len(draft.parts) == 3
    assert draft.parts[2].endswith(compose.AFFILIATE_DISCLOSURE) and '👉 백색소음기' in draft.parts[2]
    assert 'https://' not in draft.parts[0] + draft.parts[1] and len(client.requests) == 1


def test_product_slot_falls_back_to_news_when_all_used(product_channel):
    used = tuple(history.HistoryEntry(f's{i}', history.PUBLISHED, doc_id=p.url, seed='product')
                 for i, p in enumerate(PRODUCTS))
    llm, _ = fake_llm({'SelectionResult': [selection((0, 8))], 'ThreadPost': [POST], 'FactCheck': [OK_FACTS]})
    draft = compose.compose(llm, MODELS, used, lambda: list(ARTICLES), lambda a: BODY, '2026-09-27', 20,
                            lambda: list(PRODUCTS))
    assert draft.kind == compose.NEWS


def test_no_product_when_channel_disables_it(monkeypatch):
    monkeypatch.setattr(channel, 'PRODUCT_HOUR', None)
    llm, _ = fake_llm({'SelectionResult': [selection((0, 8))], 'ThreadPost': [POST], 'FactCheck': [OK_FACTS]})
    draft = compose.compose(llm, MODELS, (), lambda: list(ARTICLES), lambda a: BODY, '2026-09-27', 20,
                            lambda: list(PRODUCTS))
    assert draft.kind == compose.NEWS


def test_cross_promo_every_third_news_post(monkeypatch):
    monkeypatch.setattr(channel, 'CROSS_PROMO', '📸 인스타 @x')
    monkeypatch.setattr(channel, 'CROSS_PROMO_EVERY', 3)
    news = lambda n: tuple(history.HistoryEntry(f's{i}', history.PUBLISHED, seed='news') for i in range(n))
    assert [compose.wants_cross_promo(news(n)) for n in range(6)] == [False, False, True, False, False, True]
    draft, _ = run_compose({'SelectionResult': [selection((0, 8))], 'ThreadPost': [POST], 'FactCheck': [OK_FACTS]},
                           history_=news(2))
    assert draft.parts[1].endswith('📸 인스타 @x')


def test_post_pending_publishes_saved_draft_once(tmp_path):
    path = tmp_path / 'pending.json'
    draft = compose.Draft('a1', '제목', (HOOK, TIPS), 'https://news.example/a1')
    post.save_pending(draft, '2026-09-27T13:40', path)
    c, graph = client(OK_ROUTES)
    r = post.run_pending(c, None, AT_20, path)
    assert r.outcome == 'success' and not path.exists()
    entry = history.find(history.load_history(), '2026-09-27T13:40')
    assert entry.status == history.PUBLISHED and entry.doc_id == 'a1' and entry.permalink == 'https://threads/p/1'
    creates = [p for m, u, p in graph.calls if u.endswith('/threads')]
    assert [p['text'] for p in creates] == [HOOK, TIPS] and creates[1]['reply_to_id'] == 'm1'
    post.save_pending(draft, '2026-09-27T13:40', path)
    assert post.run_pending(c, None, AT_20, path).outcome == 'skipped'  # 같은 슬롯 두 번 안 올림
    assert post.run_pending(c, None, AT_20, path).outcome == 'skipped'  # 파일 없음


# --- 구제 발행: 검수에 다 떨어져도 문제 줄만 빼고 게시 ---

from src import rescue  # noqa: E402

BAD_TIPS = TIPS.replace('3. 분쟁 생기면 소비자상담센터부터', '3. 분쟁이 50% 늘었대 무조건 확인')


def test_rescue_drops_bad_lines_and_keeps_question():
    hook, tips = rescue.rescue(HOOK, BAD_TIPS, ['분쟁이 50% 늘었대'], '\n\n📰 출처')
    assert '50%' not in tips and '무조건' not in tips and tips.endswith('📰 출처')
    assert '?' in tips.splitlines()[-3] and hook == HOOK
    assert rescue.rescue('짧음', TIPS, [], '') is None


def test_compose_rescues_when_every_rewrite_fails():
    bad = FactCheck(claims=[ClaimCheck(sentence='분쟁이 50% 늘었대', kind='unsupported_fact', reason='숫자 다름')])
    bad_post = ThreadPost(hook=HOOK, tips=BAD_TIPS)
    draft, _ = run_compose({'SelectionResult': [selection((0, 8))], 'ThreadPost': [bad_post, bad_post],
                            'FactCheck': [bad, bad]})
    assert draft.rescued and draft.key == 'a1' and '50%' not in draft.parts[1]


def test_rescued_post_is_marked_in_history():
    bad = FactCheck(claims=[ClaimCheck(sentence='분쟁이 50% 늘었대', kind='unsupported_fact', reason='숫자 다름')])
    bad_post = ThreadPost(hook=HOOK, tips=BAD_TIPS)
    d, _ = deps(OK_ROUTES, {'SelectionResult': [selection((0, 8))], 'ThreadPost': [bad_post, bad_post],
                            'FactCheck': [bad, bad]})
    assert post.run_post(ENV, d, None, AT_20).outcome == 'success'
    entry = history.find(history.load_history(), '2026-09-26T20:00')
    assert entry.status == history.PUBLISHED and post.RESCUED_NOTE in entry.note


# --- 일상글 (channel.CASUAL_HOUR 슬롯) ---

from src import casual  # noqa: E402
from src.casual import CasualPost  # noqa: E402


def test_casual_slot_writes_short_post_without_links(monkeypatch):
    monkeypatch.setattr(channel, 'CASUAL_HOUR', 12)
    llm, client = fake_llm({'CasualPost': [CasualPost(text='라면에 계란 vs 치즈, 너는 뭐 넣어? 🍜')]})
    draft = compose.compose(llm, MODELS, (), lambda: [], lambda a: None, '2026-09-27', 12, lambda: [],
                            '2026-09-27T12:30')
    assert draft.kind == casual.KIND and draft.parts == ('라면에 계란 vs 치즈, 너는 뭐 넣어? 🍜',)
    assert draft.key == 'casual:2026-09-27T12:30' and not draft.rescued and len(client.requests) == 1


def test_casual_falls_back_to_prepared_question(monkeypatch):
    monkeypatch.setattr(channel, 'CASUAL_HOUR', 12)
    bad = CasualPost(text='어제 내가 써봤는데 무조건 좋아 https://x.com')
    llm, _ = fake_llm({'CasualPost': [bad, bad]})
    draft = compose.compose(llm, MODELS, (), lambda: [], lambda a: None, '2026-09-27', 12, lambda: [],
                            '2026-09-27T12:30')
    assert draft.rescued and draft.parts[0] in channel.CASUAL_FALLBACKS
    assert all('?' in q and not quality.rule_issues(q) for q in channel.CASUAL_FALLBACKS)


def test_flagged_line_is_dropped_without_rewriting():
    """걸린 줄(근거 없는 사실·금지 표현)은 다시 쓰지 않고 빼고 게시한다 (2026-09-28)."""
    bad = FactCheck(claims=[ClaimCheck(sentence='분쟁이 50% 늘었대', kind='unsupported_fact', reason='숫자 다름')])
    draft, client = run_compose({'SelectionResult': [selection((0, 8))], 'ThreadPost': [ThreadPost(hook=HOOK, tips=BAD_TIPS)],
                                 'FactCheck': [bad]})
    writes = [r for r in client.requests if r['text_format'].__name__ == 'ThreadPost']
    assert len(writes) == 1 and draft.rescued and '50%' not in draft.parts[1] and '무조건' not in draft.parts[1]
