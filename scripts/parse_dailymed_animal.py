"""미국 DailyMed 동물약 라벨(FDA 허가 라벨, 공공 저작물) → 반려동물 관련 라벨의 상호작용·금기·주의 섹션 추출.

입력: data/raw/dailymed/dm_spl_release_animal.zip  (DailyMed 'ANIMAL LABELS' 전체 릴리스, 약 1.3GB)
      https://dailymed.nlm.nih.gov/dailymed/spl-resources-all-drug-labels.cfm
출력: data/labels/dailymed_companion.jsonl  — 라벨 1개 = 1줄
      data/labels/dailymed_stats.json
사용: python scripts/parse_dailymed_animal.py

라벨 XML(SPL)은 신뢰하지 않는 입력으로 다룬다: 외부 엔티티를 풀지 않는 defusedxml이 있으면 쓰고,
없으면 표준 ElementTree(외부 엔티티 미해석)로 파싱한다. 실행 코드는 없다.
"""
from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

try:
    from defusedxml import ElementTree as ET  # type: ignore
except ImportError:  # 표준 라이브러리도 외부 엔티티는 해석하지 않는다
    import xml.etree.ElementTree as ET  # noqa: N817

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "dailymed" / "dm_spl_release_animal.zip"
OUT = ROOT / "data" / "labels"
NS = {"v3": "urn:hl7-org:v3"}

# LOINC 섹션 코드
CODES = {
    "34073-7": "interactions",
    "34070-3": "contraindications",
    "34071-1": "warnings",
    "42232-9": "precautions",
    "43685-7": "warnings",        # warnings and precautions
    "34067-9": "indications",
    "34084-4": "adverse_reactions",
}
# 코드 없는(미분류) 섹션은 제목으로 분류
TITLE_RULES = [
    (re.compile(r"interact", re.I), "interactions"),
    (re.compile(r"contraindicat", re.I), "contraindications"),
    (re.compile(r"precaution", re.I), "precautions"),
    (re.compile(r"warning", re.I), "warnings"),
    (re.compile(r"indication", re.I), "indications"),
    (re.compile(r"adverse", re.I), "adverse_reactions"),
]
SPECIES = {
    "dog": re.compile(r"\b(dogs?|canines?|puppies|puppy)\b", re.I),
    "cat": re.compile(r"\b(cats?|felines?|kittens?)\b", re.I),
    "rabbit": re.compile(r"\brabbits?\b", re.I),
    "bird": re.compile(r"\b(birds?|parrots?|psittacines?|budgerigars?|cockatiels?)\b", re.I),
    "ferret": re.compile(r"\bferrets?\b", re.I),
    "rodent": re.compile(r"\b(hamsters?|guinea pigs?|rodents?)\b", re.I),
}
MAX_SECTION_CHARS = 6000


def text_of(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def parse_spl(xml_bytes: bytes) -> dict | None:
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return None
    setid = root.find("v3:setId", NS)
    title_el = root.find("v3:title", NS)
    eff = root.find("v3:effectiveTime", NS)
    names, ingredients = set(), set()
    for mp in root.iter("{urn:hl7-org:v3}manufacturedProduct"):
        n = mp.find("v3:name", NS)
        if n is not None and text_of(n):
            names.add(text_of(n))
        for ai in mp.iter("{urn:hl7-org:v3}activeIngredientSubstance"):
            nm = ai.find("v3:name", NS)
            if nm is not None and text_of(nm):
                ingredients.add(text_of(nm).lower())
        for ing in mp.iter("{urn:hl7-org:v3}ingredient"):
            if ing.get("classCode", "").startswith("ACTI"):
                sub = ing.find("v3:ingredientSubstance/v3:name", NS)
                if sub is not None and text_of(sub):
                    ingredients.add(text_of(sub).lower())
    sections: dict[str, list[str]] = {}
    for sec in root.iter("{urn:hl7-org:v3}section"):
        code = sec.find("v3:code", NS)
        title = sec.find("v3:title", NS)
        kind = CODES.get(code.get("code") if code is not None else "")
        if kind is None and title is not None:
            t = text_of(title)
            kind = next((k for rx, k in TITLE_RULES if rx.search(t)), None)
        if kind is None:
            continue
        body = text_of(sec)[:MAX_SECTION_CHARS]
        if body and body not in sections.get(kind, []):
            sections.setdefault(kind, []).append(body)
    full_title = text_of(title_el) if title_el is not None else ""
    species_text = " ".join([full_title, *sections.get("indications", [])])
    species = sorted(k for k, rx in SPECIES.items() if rx.search(species_text))
    return {
        "setid": setid.get("root") if setid is not None else None,
        "effective": eff.get("value") if eff is not None else None,
        "title": full_title[:300],
        "products": sorted(names)[:5],
        "active_ingredients": sorted(ingredients),
        "species": species,
        "sections": sections,
        "url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid.get('root')}" if setid is not None else None,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    with zipfile.ZipFile(SRC) as outer, (OUT / "dailymed_companion.jsonl").open("w", encoding="utf-8") as out:
        for info in outer.infolist():
            if not info.filename.lower().endswith(".zip"):
                continue
            stats["labels_total"] += 1
            try:
                with zipfile.ZipFile(io.BytesIO(outer.read(info))) as inner:
                    xmls = [n for n in inner.namelist() if n.lower().endswith(".xml")]
                    if not xmls:
                        continue
                    rec = parse_spl(inner.read(xmls[0]))
            except (zipfile.BadZipFile, KeyError):
                stats["bad_zip"] += 1
                continue
            if rec is None:
                stats["parse_error"] += 1
                continue
            companion = [s for s in rec["species"] if s in ("dog", "cat", "rabbit", "bird", "rodent", "ferret")]
            if not companion:
                continue
            stats["labels_companion"] += 1
            for s in companion:
                stats[f"species_{s}"] += 1
            if rec["sections"].get("interactions"):
                stats["with_interactions_section"] += 1
            if rec["sections"].get("contraindications"):
                stats["with_contraindications"] += 1
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (OUT / "dailymed_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
