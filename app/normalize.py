"""검색어·성분명 정규화."""
from __future__ import annotations

import re

# 성분 표기에 붙는 염·수화물·제형 접미사 (긴 것부터)
_SUFFIXES = sorted([
    "브롬화수소산염", "타르타르산염", "말레산염", "시트르산염", "염산염", "황산염", "질산염", "인산염",
    "이수화물", "수화물", "무수물", "수산화물", "아세테이트",
    "나트륨", "칼륨", "칼슘", "마그네슘", "알루미늄",
    "장용과립", "과립", "디씨", "dc",
], key=len, reverse=True)
_MIN_STEM = 3  # 접미사를 뗀 뒤 이보다 짧아지면 떼지 않는다 (예: 산화마그네슘)


def norm(s: str) -> str:
    """검색·비교용 키: 소문자, 괄호 내용·공백·기호 제거."""
    s = (s or "").lower()
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"[\s\-_/·,.'’]+", "", s)


def norm_ingredient(raw: str) -> str:
    """식약처 성분 표기를 표준 성분 키로. 예: '슈도에페드린염산염' → '슈도에페드린'."""
    s = norm(raw)
    s = re.sub(r"^(dl|d|l)(?=[가-힣])", "", s)
    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES:
            if s.endswith(suf) and len(s) - len(suf) >= _MIN_STEM:
                s = s[: -len(suf)]
                changed = True
                break
    return s


# 쪼갠 조각이 이것뿐이면 별칭으로 쓰지 않는다 (물질이 아니라 수식어)
_STOP_PARTS = {"경구", "보충제", "화재", "조리사고", "섭취", "과잉", "등"}


def substance_key(name_ko: str) -> str:
    """물질 동일성 키: 괄호 설명을 뺀 한국어 표준명. 예: '알코올(에탄올)' → '알코올'."""
    return norm(re.sub(r"\(.*?\)", "", name_ko)) or norm(name_ko)


def split_names(name: str) -> list[str]:
    """'포도·건포도', '백합(나리속)' 같은 이름을 별칭 후보로 쪼갠다."""
    parts = [name]
    inner = re.findall(r"\((.*?)\)", name)
    outer = re.sub(r"\(.*?\)", "", name)
    for chunk in [outer, *inner]:
        for p in re.split(r"[·,/]|\s및\s", chunk):
            p = re.sub(r"\s*등\s*.*$", "", p.strip())  # '커피 등' → '커피', '향초 등 실내 …' → '향초'
            if p and norm(p) not in _STOP_PARTS:
                parts.append(p)
    return list(dict.fromkeys(p for p in parts if len(norm(p)) >= 2))
