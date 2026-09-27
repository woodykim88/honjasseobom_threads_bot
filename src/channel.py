"""채널별 설정. 두 Threads 뉴스 채널(혼자써봄·건강노트)은 이 파일과 prompts/만 다르고 나머지 코드는 같다."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Feed:
    publisher: str
    url: str


NAME = '혼자써봄'
HANDLE = 'honjasseobom'
TOPIC = '생활필수품 뉴스'
CMD_PREFIX = 'hj'  # 텔레그램 명령: /hj_stop /hj_skip /hj_resume (다른 Threads 채널과 겹치지 않게)

# 언론사가 직접 배포하는 공식 RSS만 쓴다 (모두 robots.txt가 /rss/ 수집을 허용, 2026-09-27 확인).
# 소비자가만드는신문은 robots.txt가 /rss/를 막아서 뺐다.
FEEDS = (
    Feed('컨슈머치', 'https://www.consumuch.com/rss/allArticle.xml'),
    Feed('소비자경제', 'https://www.dailycnc.com/rss/allArticle.xml'),
    Feed('컨슈머타임스', 'https://www.cstimes.com/rss/S1N3.xml'),
    Feed('식품음료신문', 'https://www.foodnews.co.kr/rss/S1N1.xml'),
)

# 생활필수품과 거리가 먼 기사 (선별 LLM 전에 걸러 비용 절약). 제목에서 찾는다.
EXCLUDED_TITLE_WORDS = (
    '[포토]', '[인사]', '[부고]', '[칼럼]', '[사설]', 'MOU', '업무협약', '협약 체결', '임명', '취임', '선임',
    '대학교', '대학', '게임', '주가', '투자', '실적', '영업이익', '공모', '봉사', '기부', '후원', '수상', '시상',
    '선물거래', '코인', '가상자산', '정치', '국회의원', '선거',
)
# 자동 게시에서 빼는 주제: 의료 분쟁·사건사고처럼 정보보다 사고 소식인 기사
SENSITIVE_PATTERNS = (
    r'사망', r'숨져', r'숨진', r'성폭', r'마약', r'자살', r'시술', r'수술', r'임플란트', r'분만', r'치료받',
)

# 과장·단정 표현 (본문 전체 검사)
BANNED_WORDS = (
    '무조건', '100%', '최저가', '역대급', '미쳤다', '효과 보장', '완치', '해독', '디톡스', '충격', '경악',
)

# 수익화 (2026-09-27 사용자 결정): 20:00은 인포크 제휴 제품 추천, 나머지는 뉴스. 모든 제품을 한 번씩 올리면 뉴스로.
# @damz0324도 같은 인포크 목록을 앞에서부터 쓰므로, 같은 날 같은 제품이 겹치지 않게 여기선 뒤에서부터 고른다.
PRODUCT_HOUR: int | None = 20
PRODUCT_FROM_END = True
# 교차 추천: 뉴스 글 3개에 1번, 답글 출처 아래에 붙인다 (첫 글에 링크를 달면 노출이 줄어드는 경향이 있어 답글에만)
CROSS_PROMO = '📸 생활경제 소식은 카드로도 정리 중: 인스타 @newsmanwoody\nhttps://www.instagram.com/newsmanwoody/'
CROSS_PROMO_EVERY = 3

# 일상글 (2026-09-27 사용자 결정): 매일 12:30, 링크·광고 없는 짧은 대화형 글. 지어낸 경험은 쓰지 않는다 (src/casual.py).
CASUAL_HOUR: int | None = 12
CASUAL_FALLBACKS = (  # AI 글이 검수에 두 번 떨어졌을 때 쓰는 준비된 질문 (회차를 건너뛰지 않기 위해)
    '자취템 중에 이건 진짜 잘 샀다 싶은 거 하나만 말해 줘?',
    '장 볼 때 매번 꼭 사게 되는 거 하나씩 말해 보자 🛒 뭐 있어?',
    '혼자 밥 먹을 때 제일 자주 먹는 메뉴 뭐야?',
    '세제 vs 휴지, 떨어지면 더 곤란한 건?',
    '퇴근하고 집 오면 제일 먼저 하는 거 뭐야?',
)
