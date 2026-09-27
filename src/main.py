"""Threads 뉴스 채널 자동 게시 진입점 (채널 설정은 src/channel.py).

작업(--job):
    post           슬롯 시각이 되면 기사로 글을 만들어 바로 게시
    preview        게시하지 않고 글만 만들어 output/preview.txt에 저장
    refresh-token  Threads 장기 토큰 갱신 (주 1회)
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src import channel, collector, compose, history, notifier, post, products, providers, runlog, schedule, token_refresh
from src.guard import RunResult
from src.http_client import http_get
from src.llm import LLMClient, LLMError
from src.threads import ThreadsClient, ThreadsConfigError, ThreadsError, load_threads_config

ROOT = Path(__file__).resolve().parent.parent
JOBS = ('post', 'preview', 'refresh-token')
PREVIEW_PATH = ROOT / 'output' / 'preview.txt'
KNOWN_ERRORS = (providers.ProviderConfigError, ThreadsConfigError, ThreadsError, schedule.ScheduleError,
                compose.PipelineError, LLMError)


def load_candidates():
    return collector.fetch_candidates(http_get, datetime.now(schedule.KST))


def fetch_body(article):
    return collector.fetch_body(http_get, article)


def load_products():
    return products.fetch_products(http_get)


def run_preview(env: Mapping[str, str], ai: providers.AISettings, hour: int | None) -> RunResult:
    llm = LLMClient(providers.build_text_backend(ai.text_provider, env))
    today = datetime.now(schedule.KST).strftime('%Y-%m-%d')
    draft = compose.compose(llm, compose.Models(ai.writer_model, ai.fast_model), history.load_history(),
                            load_candidates, fetch_body, today, hour, load_products)
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_PATH.write_text(draft.text, encoding='utf-8')
    print(f'[미리보기] ({draft.kind}) ' + ' + '.join(f'{len(p)}자' for p in draft.parts) + f'\n{draft.text}')
    return RunResult('success', f'미리보기 생성: {draft.title}', llm_calls=llm.calls)


def run_job(job: str, env: Mapping[str, str], ai: providers.AISettings | None,
            telegram: notifier.TelegramConfig | None, hour: int | None = None) -> RunResult:
    if job == 'preview':
        return run_preview(env, ai, hour)
    if job == 'refresh-token':
        return token_refresh.run_refresh(env, telegram)
    deps = post.PostDeps(
        backend=providers.build_text_backend(ai.text_provider, env),
        models=compose.Models(ai.writer_model, ai.fast_model),
        client=ThreadsClient(load_threads_config(env)),
        load_candidates=load_candidates, fetch_body=fetch_body, load_products=load_products,
    )
    return post.run_post(env, deps, telegram, datetime.now(timezone.utc))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f'Threads @{channel.HANDLE} 자동 게시')
    parser.add_argument('--job', choices=JOBS, default='preview')
    parser.add_argument('--hour', type=int, default=None, help='preview: 제품 슬롯 시각(예: 20)이면 제품 추천 글')
    args = parser.parse_args(argv)

    load_dotenv(ROOT / '.env')
    env = os.environ
    telegram = notifier.load_telegram_config(env)
    started = datetime.now(schedule.KST)
    ai: providers.AISettings | None = None
    try:
        if args.job in ('post', 'preview'):
            ai = providers.load_ai_settings(env)
        result = run_job(args.job, env, ai, telegram, args.hour)
    except KNOWN_ERRORS as e:
        result = RunResult('failed', str(e))
    except Exception as e:  # noqa: BLE001 - 무인 실행이므로 예상 못한 오류도 로그를 남기고 반드시 알린다
        traceback.print_exc()
        result = RunResult('failed', f'예상하지 못한 오류 {e.__class__.__name__}: {e}')

    print(f'[결과] {result.outcome}: {result.message}')
    if result.outcome == 'failed' and args.job != 'preview':
        notifier.notify(telegram, f'❌ {args.job} 작업 실패\n원인: {result.message}')
    if env.get('GITHUB_ACTIONS') == 'true':
        runlog.append_run(runlog.RunRecord(
            started_at=started.isoformat(timespec='seconds'),
            finished_at=datetime.now(schedule.KST).isoformat(timespec='seconds'),
            mode=args.job, outcome=result.outcome, message=result.message,
            text_provider=ai.text_provider if ai else '', writer_model=ai.writer_model if ai else '',
            llm_calls=result.llm_calls, posts=result.posts, **runlog.github_context(env),
        ))
    return 1 if result.outcome == 'failed' else 0


if __name__ == '__main__':
    sys.exit(main())
