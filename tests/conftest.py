"""모든 테스트 공통: 실제 기록 파일(data/*)을 절대 건드리지 않도록 임시 경로로 바꾼다.

GitHub Actions에서 테스트가 돌 때 GITHUB_ACTIONS=true라서, 막지 않으면
테스트용 가짜 기록이 data/에 써지고 커밋된다.
"""
import pytest

from src import channel, history, replies, runlog, state


@pytest.fixture(autouse=True)
def isolate_data_files(monkeypatch, tmp_path):
    monkeypatch.setattr(history, 'DEFAULT_HISTORY_PATH', tmp_path / 'history.json')
    monkeypatch.setattr(runlog, 'DEFAULT_RUNS_PATH', tmp_path / 'runs.jsonl')
    monkeypatch.setattr(state, 'DEFAULT_STATE_PATH', tmp_path / 'state.json')
    monkeypatch.setattr(replies, 'REPLIED_PATH', tmp_path / 'replied.json')
    monkeypatch.setattr(channel, 'BLOG_HOUR', None)  # 20:00 블로그 슬롯은 해당 테스트에서만 켠다
    for name in ('GITHUB_ACTIONS', 'GITHUB_RUN_ID', 'GITHUB_EVENT_NAME', 'GITHUB_REPOSITORY', 'GITHUB_SERVER_URL'):
        monkeypatch.delenv(name, raising=False)
