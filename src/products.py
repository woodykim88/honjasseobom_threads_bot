"""인포크 페이지(link.inpock.co.kr/shoperwoody)에서 제휴 제품 목록을 읽는다.

- robots.txt가 허용하는 공개 페이지를 한 번 읽는다 (Next.js __NEXT_DATA__의 링크 블록).
- 건강기능식품·영양제·화장품 효능·의료기기 성격의 제품은 자동 추천에서 뺀다 (광고 규제가 까다로움).
- 쿠팡 상세페이지는 수집하지 않는다. 글에는 제품명 밖의 스펙·효능을 쓰지 않는다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from src.http_client import HttpGet

INPOCK_URL = 'https://link.inpock.co.kr/shoperwoody'
EXCLUDED_WORDS = (
    '관절', '패치', '프로틴', '단백질', '올레샷', '영양제', '비타민', '유산균', '홍삼', '콜라겐', '다이어트',
    '마스크팩', '메디힐', '크림', '세럼', '앰플', '화장품', '건강기능', '효능',
)
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_NUMBER_PREFIX_RE = re.compile(r'^\s*\d+\s*[.번,]\s*')


@dataclass(frozen=True)
class Product:
    name: str
    url: str
    image: str = ''

    @property
    def is_coupang(self) -> bool:
        return 'coupang.com' in self.url


def clean_name(title: str) -> str:
    """'47번, 오징어 짬뽕' → '오징어 짬뽕', '4. 메디힐 마스크팩 바로가기 👇' → '메디힐 마스크팩'."""
    name = _NUMBER_PREFIX_RE.sub('', title).replace('바로가기', '')
    return re.sub(r'[👇👉]', '', name).strip(' ,')


def is_excluded(name: str) -> bool:
    return any(word in name for word in EXCLUDED_WORDS)


def parse_products(page_html: str) -> list[Product]:
    match = _NEXT_DATA_RE.search(page_html)
    if not match:
        return []
    blocks = json.loads(match.group(1)).get('props', {}).get('pageProps', {}).get('blocks', [])
    products, seen = [], set()
    for block in blocks:
        url, title = (block.get('url') or '').strip(), (block.get('title') or '').strip()
        name = clean_name(title)
        if block.get('block_type') != 'link' or not url.startswith('https://') or not name or url in seen:
            continue
        seen.add(url)
        if is_excluded(name):
            continue
        image = block.get('image') or ''
        products.append(Product(name=name, url=url, image=image if isinstance(image, str) else ''))
    return products


def fetch_products(get: HttpGet) -> list[Product]:
    return parse_products(get(INPOCK_URL))
