"""스레드 떡상글 패턴 (2026-09-27 사용자가 공유한 운영 노하우에서 뉴스 채널에 맞는 것만 골랐다).

한 글에 다 넣으면 어색하므로 글마다 2개를 골라 주고, "쉬운 질문 마무리"는 항상 넣는다.
지어낸 경험·인물이 필요한 패턴(권위형 빌려오기, 군중심리, 스친 추천, 우연한 발견)은 거짓 후기가 되므로 쓰지 않는다.
"""
from __future__ import annotations

import random

PATTERNS = (
    '감탄사 후킹: 첫 10자가 제목이다. 감탄사로 시작하고, 기사에 나온 브랜드·장소 키워드(다이소·쿠팡·편의점·올리브영 등)가 있으면 맨 앞에 둬',
    '답 숨기기: 첫 글에서는 핵심 대상을 "이거"로만 부르고 정체와 내용은 답글에서 공개해',
    '비유 한 줄: 숫자 나열 대신 누구나 바로 그려지는 감각적인 비유 한 줄을 넣어 (기사 사실을 넘는 과장은 금지)',
    '가성비 비교: 기사에 가격·용량 비교가 있으면 비싼 쪽과 대놓고 비교해 (기사에 없으면 이 패턴은 건너뛰어)',
    '전문가 인용: 기사에 실제로 나온 전문가·기관의 말을 "~가 말하길"처럼 빌려 와 (기사에 없는 인물은 절대 만들지 마)',
)
# 제휴 제품 추천 글 (혼자써봄 20:00). 제품명 밖의 스펙·효능은 쓰지 않는다.
PRODUCT_PATTERNS = (
    PATTERNS[0],
    '제품명 숨기기: 첫 글과 첫 번째 답글에는 제품명을 쓰지 말고 "이거", "얘"로만 불러. 정체는 마지막 답글에서 공개해',
    '비유 한 줄: 설명 대신 누구나 바로 그려지는 상황 비유 한 줄 (써 본 후기처럼 쓰지 말고, 과장 금지)',
)
ALWAYS = '쉬운 질문 마무리: 마지막 파트의 마지막 줄은 누구나 한 줄로 답할 수 있는 가벼운 질문으로 끝내 (물음표 필수)'
PICK = 2


def pick_patterns(seed: str, k: int = PICK, product: bool = False) -> tuple[str, ...]:
    """seed(글 키)마다 같은 조합이 나오도록 패턴 k개를 고르고, 질문 마무리를 붙입니다."""
    return (*random.Random(seed).sample(PRODUCT_PATTERNS if product else PATTERNS, k), ALWAYS)


def pattern_brief(seed: str, product: bool = False) -> str:
    picked = pick_patterns(seed, product=product)
    return '이번 글에 쓸 패턴 (이것만 자연스럽게 섞어):\n' + '\n'.join(f'- {p}' for p in picked)
