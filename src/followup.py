"""반응 좋은 글에 혼자써봄이 직접 덧붙이는 댓글 한 개 (2026-11-18 사용자: "반응 좋았던 실험에는 댓글 다는 것도 하자").

11/17 계산기 글(연차)이 조회 128·댓글 6으로 최근 1등이었다. 대화가 붙은 글에 작성자가 댓글을 하나 더 달면
스레드가 다시 살아나 피드에 더 오래 머문다. reply 작업(매시 :55) 뒤에 이어서 돈다.
- 대상: 최근 HOT_WINDOW_HOURS 안의 내 원글 중 조회 HOT_VIEWS 이상이거나 댓글 HOT_REPLIES 이상.
- 글마다 한 번만, 한 번 실행에 1개, 하루 MAX_PER_DAY개.
- 댓글들을 읽고 "댓글 보니 ~파가 많네" 같은 한 줄 + 새 질문. 링크·지어낸 경험·제품 권유 금지 (replies.reply_issues).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src import notifier, replies
from src.guard import RunResult
from src.llm import LLMClient, LLMError, load_prompt
from src.threads import ThreadsClient, ThreadsError

STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'followups.json'
HOT_VIEWS = 80
HOT_REPLIES = 4
HOT_WINDOW_HOURS = 48
MAX_PER_DAY = 2
MAX_ATTEMPTS = 2
KST = timezone(timedelta(hours=9))


class FollowupDraft(BaseModel):
    text: str = Field(description='작성자가 덧붙이는 댓글 20~100자, 댓글 반응 한 줄 + 쉬운 새 질문, 링크 없음')


def load_state(path: Path | None = None) -> dict[str, Any]:
    try:
        data = json.loads((path or STATE_PATH).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'ids': [], 'days': {}}
    return {'ids': list(data.get('ids', [])), 'days': dict(data.get('days', {}))}


def save_state(data: dict[str, Any], path: Path | None = None) -> None:
    target = path or STATE_PATH
    trimmed = {'ids': data['ids'][-300:], 'days': dict(sorted(data['days'].items())[-14:])}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _metric(insights: dict[str, Any], name: str) -> int:
    for item in insights.get('data', []):
        if item.get('name') == name:
            values = item.get('values') or [{}]
            return int(values[0].get('value') or (item.get('total_value') or {}).get('value') or 0)
    return 0


def hot_posts(client: ThreadsClient, done: set[str], now: datetime) -> list[dict[str, Any]]:
    """덧붙일 만한 내 원글 (조회 많은 순)."""
    cutoff = now - timedelta(hours=HOT_WINDOW_HOURS)
    posts = client.get(f'{client.user_id}/threads', {'fields': 'id,text,timestamp,is_reply', 'limit': '10'})
    found = []
    for post in posts.get('data', []):
        if post.get('is_reply') or post['id'] in done or not replies._posted_after(post.get('timestamp', ''), cutoff):
            continue
        insights = client.get(f"{post['id']}/insights", {'metric': 'views,replies'})
        views, count = _metric(insights, 'views'), _metric(insights, 'replies')
        if views >= HOT_VIEWS or count >= HOT_REPLIES:
            found.append({**post, 'views': views})
    return sorted(found, key=lambda p: -p['views'])


def fix_spelling(text: str) -> str:
    """모델이 자주 틀리는 맞춤법 (11/18 첫 덧글 '몇 일이야?')."""
    return text.replace('몇 일', '며칠').replace('몇일', '며칠')


def write_followup(llm: LLMClient, model: str, client: ThreadsClient, post: dict[str, Any]) -> str:
    comments = client.get(f"{post['id']}/replies", {'fields': 'id,text,username,is_reply_owned_by_me'})
    others = [c.get('text', '')[:120] for c in comments.get('data', [])
              if not c.get('is_reply_owned_by_me') and c.get('username') != replies.HANDLE][:8]
    user_input = (f'내 원글: {post.get("text", "")[:300]}\n\n달린 댓글:\n'
                  + ('\n'.join(f'- {t}' for t in others) or '(아직 없음)'))
    feedback: list[str] = []
    for _ in range(MAX_ATTEMPTS):
        extra = ('\n\n이전 댓글이 검수에서 떨어졌어:\n' + '\n'.join(f'- {f}' for f in feedback)) if feedback else ''
        text = fix_spelling(llm.parse(model, load_prompt('followup'), user_input + extra, FollowupDraft).text.strip())
        feedback = replies.reply_issues(text) + ([] if '?' in text else ['쉬운 질문(물음표)을 하나 넣으세요.'])
        if not feedback:
            return text
        print(f'[덧글 탈락] {text[:30]}: ' + ' / '.join(feedback))
    return ''


def run_followups(client: ThreadsClient, llm: LLMClient, model: str, telegram: notifier.TelegramConfig | None,
                  now: datetime | None = None, path: Path | None = None) -> RunResult:
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(KST).strftime('%Y-%m-%d')
    data = load_state(path)
    if int(data['days'].get(day, 0)) >= MAX_PER_DAY:
        return RunResult('skipped', f'오늘 덧글 한도({MAX_PER_DAY}개)를 채웠습니다.')
    candidates = hot_posts(client, set(data['ids']), now)
    if not candidates:
        return RunResult('skipped', '덧붙일 만큼 반응 좋은 글이 없습니다.')
    post = candidates[0]
    try:
        text = write_followup(llm, model, client, post)
        if not text:
            data = {**data, 'ids': [*data['ids'], post['id']]}  # 두 번 떨어진 글은 다시 시도하지 않는다
            save_state(data, path)
            return RunResult('skipped', '덧글이 검수에 두 번 떨어져 건너뜁니다.', llm_calls=llm.calls)
        box = client.create_text(text, reply_to=post['id'])
        client.wait_before_publish()
        client.publish(box)
    except (LLMError, ThreadsError) as e:
        print(f'[덧글 실패] {e}')
        return RunResult('failed', f'덧글 실패: {e}', llm_calls=llm.calls)
    data = {'ids': [*data['ids'], post['id']], 'days': {**data['days'], day: int(data['days'].get(day, 0)) + 1}}
    save_state(data, path)
    notifier.notify(telegram, f'💬 반응 좋은 글(조회 {post["views"]})에 덧글: {text}')
    return RunResult('success', f'덧글 1개: {text[:40]}', llm_calls=llm.calls)
