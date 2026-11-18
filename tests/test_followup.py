"""반응 좋은 글에 혼자써봄이 직접 덧붙이는 댓글 (2026-11-18 사용자: "반응 좋았던 실험에는 댓글 다는 것도 하자")."""
from datetime import datetime, timezone

from src import followup
from src.followup import FollowupDraft
from tests.helpers import fake_llm

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


class Client:
    user_id = 'u1'

    def __init__(self, views=None, counts=None):
        self.views = views or {'hot': 128, 'cold': 16}
        self.counts = counts or {'hot': 6}
        self.created, self.published = [], []

    def get(self, path, params=None):
        if path == 'u1/threads':
            return {'data': [
                {'id': 'hot', 'text': '남은 연차가 눈에 밟혀 ㅋㅋ', 'timestamp': '2026-11-17T03:31:00+0000', 'is_reply': False},
                {'id': 'cold', 'text': '카드 내역 출석 체크', 'timestamp': '2026-11-16T03:31:00+0000', 'is_reply': False},
                {'id': 'old', 'text': '옛 글', 'timestamp': '2026-11-10T03:31:00+0000', 'is_reply': False},
                {'id': 'r1', 'text': '내 답글', 'timestamp': '2026-11-17T03:40:00+0000', 'is_reply': True},
            ]}
        if path.endswith('/insights'):
            pid = path.split('/')[0]
            return {'data': [{'name': 'views', 'values': [{'value': self.views.get(pid, 0)}]},
                             {'name': 'replies', 'values': [{'value': self.counts.get(pid, 1)}]}]}
        if path.endswith('/replies'):
            return {'data': [{'id': 'c1', 'text': '12월에 몰아 쓰려다 반납한 적 많아요', 'username': 'a'},
                             {'id': 'c2', 'text': '연차는 왜 이럴 때 몰리죠', 'username': 'b'}]}
        raise AssertionError(path)

    def create_text(self, text, reply_to=''):
        self.created.append((text, reply_to))
        return 'box'

    def wait_before_publish(self):
        pass

    def publish(self, box):
        self.published.append(box)
        return 'm'


GOOD = FollowupDraft(text='댓글 보니까 12월 몰아 쓰기파가 제일 많네 ㅋㅋ 너는 연차 반납해 본 적 있어?')


def test_hot_post_gets_one_followup_comment(tmp_path):
    client = Client()
    llm, req = fake_llm({'FollowupDraft': [GOOD]})
    result = followup.run_followups(client, llm, 'f', None, NOW, tmp_path / 'f.json')
    assert result.outcome == 'success'
    assert client.created == [(GOOD.text, 'hot')]
    assert '반납한 적' in req.requests[0]['input']  # 댓글 내용을 보고 쓴다
    again = followup.run_followups(client, fake_llm({})[0], 'f', None, NOW, tmp_path / 'f.json')
    assert again.outcome == 'skipped' and len(client.created) == 1  # 같은 글엔 한 번만


def test_cold_or_old_posts_get_nothing(tmp_path):
    client = Client(views={'hot': 30, 'cold': 16, 'old': 999}, counts={'hot': 2, 'old': 50})
    result = followup.run_followups(client, fake_llm({})[0], 'f', None, NOW, tmp_path / 'f.json')
    assert result.outcome == 'skipped' and client.created == []


def test_daily_cap(tmp_path):
    path = tmp_path / 'f.json'
    followup.save_state({'ids': [], 'days': {'2026-11-17': followup.MAX_PER_DAY}}, path)
    client = Client()
    assert followup.run_followups(client, fake_llm({})[0], 'f', None, NOW, path).outcome == 'skipped'
    assert client.created == []


def test_followup_with_link_or_fake_story_is_dropped(tmp_path):
    bad = FollowupDraft(text='나도 작년에 반납했는데 여기 봐 https://x.com')
    client = Client()
    llm, _ = fake_llm({'FollowupDraft': [bad, bad]})
    followup.run_followups(client, llm, 'f', None, NOW, tmp_path / 'f.json')
    assert client.created == []
