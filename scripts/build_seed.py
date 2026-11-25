"""규칙 후보(data/seed_parts/*.json)를 검증해서 시드 CSV로 합친다. 재실행 가능.

출력
  data/rules_seed.csv          독성 규칙 (물질 × 종) 1행 1규칙
  data/interactions_seed.csv   병용 규칙 (성분A × 성분B × 종) 1행 1규칙
  data/rule_sources_seed.csv   규칙별 출처 (규칙 1 : 출처 N)
  data/seed_rejects.csv        검증에서 떨어진 후보와 이유

사용: python scripts/build_seed.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
PARTS = ROOT / "data" / "seed_parts"
OUT = ROOT / "data"
CHECKED_ON = "2026-11-23"  # 원문 확인일(에이전트가 원문을 읽은 날)

SPECIES = {"dog", "cat", "rabbit", "hamster", "bird", "hedgehog"}
SUB_TYPES = {"drug_ingredient", "drug_class", "food", "plant", "household"}
RISK = {"danger": 3, "caution": 2, "safe": 1}
LEVEL = {"avoid": 3, "caution": 2}
ALLOWED_DOMAINS = {
    "merckvetmanual.com", "msdvetmanual.com", "aspca.org", "aspcapro.org",
    "petpoisonhelpline.com", "fda.gov", "anses.fr", "ncbi.nlm.nih.gov",
    "frontiersin.org", "vetmed.illinois.edu", "wsu.edu", "aaha.org",
    "cliniciansbrief.com", "plumbs.com", "bluepearlvet.com", "dvm360.com",
    "vin.com", "isvma.org", "vcahospitals.com", "catvets.com",
    "koreascience.kr", "dailyvet.co.kr",
}
# 용량 정보는 MVP에서 제공하지 않는다 (지시문 7장)
DOSE_PATTERN = re.compile(r"\d+(\.\d+)?\s*(mg|g|ml|mL|㎎|밀리그램|kg|정|알)\b|mg/kg", re.I)


def domain_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


def norm_key(s: str) -> str:
    return re.sub(r"[\s\-_/()·,]+", "", (s or "").lower())


def ko_key(name_ko: str) -> str:
    """물질 동일성 키: 괄호 설명을 뺀 한국어 표준명 (app.normalize.substance_key와 같은 규칙)."""
    return norm_key(re.sub(r"\(.*?\)", "", name_ko)) or norm_key(name_ko)


def check_common(row: dict, rejects: list, kind: str) -> bool:
    problems = []
    if row.get("species") not in SPECIES:
        problems.append(f"종 코드 오류: {row.get('species')}")
    url = row.get("source_url", "")
    if not url.startswith("http") or not domain_ok(url):
        problems.append(f"허용되지 않은 출처: {url}")
    if row.get("source_tier") not in (1, 2, 3):
        problems.append("source_tier 누락")
    if not row.get("evidence"):
        problems.append("evidence 누락")
    text = " ".join([row.get("mechanism_ko", ""), row.get("advice_ko", ""),
                     *row.get("first_aid_ko", []), *row.get("symptoms_ko", [])])
    if DOSE_PATTERN.search(text):
        problems.append("용량 숫자 포함(MVP 금지)")
    if re.search(r"구토\s*(를)?\s*(유도|시키)", " ".join(row.get("first_aid_ko", []))) and \
            not re.search(r"(하지|말|금지|않)", " ".join(row.get("first_aid_ko", []))):
        problems.append("집에서 구토 유도 지시")
    # 반려조류가 아닌 새(야생조류·가금·맹금류) 연구만 근거인 규칙은 제외
    if row.get("species") == "bird":
        ev = (row.get("evidence", "") + " " + row.get("mechanism_ko", "")).lower()
        ev = re.sub(r"not (in )?pet \w+", "", ev)  # "not pet psittacines" 같은 부정 표현은 근거로 치지 않음
        if "aflatox" in ev or "mycotox" in ev:
            problems.append("반려조류 근거 아님(주로 가금 연구) — 수의사 판단 후 추가")
        elif re.search(r"vulture|poultry|broiler|chicken|birds of prey|raptor|wild (bird|finch)|sparrow|ostrich|pigeon", ev) \
                and not re.search(r"pet bird|psittac|parrot|companion|budgerigar|cockatiel|conure", ev):
            problems.append("반려조류 근거 아님(야생·가금 연구)")
    if problems:
        rejects.append({"kind": kind, "file": row.get("_file"),
                        "item": row.get("substance_ko") or f"{row.get('a_ko')}+{row.get('b_ko')}",
                        "species": row.get("species"), "reason": "; ".join(problems)})
        return False
    return True


def main() -> None:
    tox, inter, rejects = {}, {}, []
    sources = []
    for f in sorted(PARTS.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for r in data.get("toxicity", []):
            r["_file"] = f.name
            if r.get("type") not in SUB_TYPES or r.get("risk") not in RISK:
                rejects.append({"kind": "toxicity", "file": f.name, "item": r.get("substance_ko"),
                                "species": r.get("species"), "reason": f"type/risk 오류: {r.get('type')}/{r.get('risk')}"})
                continue
            if not check_common(r, rejects, "toxicity"):
                continue
            key = f"T:{ko_key(r['substance_ko'])}:{r['species']}"
            cur = tox.get(key)
            if cur is None:
                tox[key] = {**r, "_risks": {r["risk"]}}
            else:
                cur["_risks"].add(r["risk"])
                if RISK[r["risk"]] > RISK[cur["risk"]]:  # 출처끼리 다르면 더 위험한 쪽으로
                    for k in ("risk", "mechanism_ko", "symptoms_ko", "first_aid_ko"):
                        cur[k] = r[k]
                else:
                    cur["symptoms_ko"] = list(dict.fromkeys(cur["symptoms_ko"] + r.get("symptoms_ko", [])))
            sources.append((key, r))
        for r in data.get("interaction", []):
            r["_file"] = f.name
            if r.get("level") not in LEVEL:
                rejects.append({"kind": "interaction", "file": f.name, "item": f"{r.get('a_ko')}+{r.get('b_ko')}",
                                "species": r.get("species"), "reason": f"level 오류: {r.get('level')}"})
                continue
            if r["level"] == "avoid" and r.get("source_tier") == 3:
                r["level"] = "caution"  # 보조 출처만으로는 '함께 쓰면 안 됨'을 매기지 않는다
                r["_downgraded"] = True
            if not check_common(r, rejects, "interaction"):
                continue
            a, b = sorted([ko_key(r["a_ko"]), ko_key(r["b_ko"])])
            key = f"I:{a}+{b}:{r['species']}"
            cur = inter.get(key)
            if cur is None:
                inter[key] = {**r, "_levels": {r["level"]}}
            else:
                cur["_levels"].add(r["level"])
                if LEVEL[r["level"]] > LEVEL[cur["level"]]:
                    for k in ("level", "mechanism_ko", "advice_ko"):
                        cur[k] = r[k]
            sources.append((key, r))

    def w(path: Path, rows: list[dict], cols: list[str]) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            wr = csv.DictWriter(fh, fieldnames=cols)
            wr.writeheader()
            wr.writerows(rows)

    tox_rows = [{
        "rule_key": k, "substance_ko": r["substance_ko"], "substance_en": r["substance_en"],
        "substance_type": r["type"], "species": r["species"], "risk": r["risk"],
        "mechanism_ko": r["mechanism_ko"], "symptoms_ko": "; ".join(r.get("symptoms_ko", [])),
        "first_aid_ko": "; ".join(r.get("first_aid_ko", [])),
        "source_conflict": "Y" if len(r["_risks"]) > 1 else "", "review_status": "미감수",
    } for k, r in sorted(tox.items(), key=lambda kv: (kv[1]["species"], -RISK[kv[1]["risk"]], kv[1]["substance_ko"]))]
    int_rows = [{
        "rule_key": k, "a_ko": r["a_ko"], "a_en": r["a_en"], "a_type": r.get("a_type", ""),
        "b_ko": r["b_ko"], "b_en": r["b_en"], "b_type": r.get("b_type", ""),
        "species": r["species"], "level": r["level"], "mechanism_ko": r["mechanism_ko"],
        "advice_ko": r.get("advice_ko", ""),
        "source_conflict": "Y" if len(r["_levels"]) > 1 else "",
        "downgraded_tier3": "Y" if r.get("_downgraded") else "", "review_status": "미감수",
    } for k, r in sorted(inter.items(), key=lambda kv: (kv[1]["species"], -LEVEL[kv[1]["level"]], kv[1]["a_ko"]))]
    seen, src_rows = set(), []
    for key, r in sources:
        if (key, r["source_url"]) in seen:
            continue
        seen.add((key, r["source_url"]))
        src_rows.append({"rule_key": key, "source_name": r["source_name"], "source_url": r["source_url"],
                         "source_tier": r["source_tier"], "checked_on": CHECKED_ON, "evidence": r["evidence"]})

    w(OUT / "rules_seed.csv", tox_rows, list(tox_rows[0]) if tox_rows else ["rule_key"])
    w(OUT / "interactions_seed.csv", int_rows, list(int_rows[0]) if int_rows else ["rule_key"])
    w(OUT / "rule_sources_seed.csv", src_rows, ["rule_key", "source_name", "source_url", "source_tier", "checked_on", "evidence"])
    w(OUT / "seed_rejects.csv", rejects, ["kind", "file", "item", "species", "reason"])

    sys.stdout.reconfigure(encoding="utf-8")
    print(f"독성 규칙 {len(tox_rows)} / 병용 규칙 {len(int_rows)} / 출처 연결 {len(src_rows)} / 탈락 {len(rejects)}")
    from collections import Counter
    print("종별 독성:", dict(Counter(r["species"] for r in tox_rows)))
    print("종별 병용:", dict(Counter(r["species"] for r in int_rows)))
    print("등급별 독성:", dict(Counter(r["risk"] for r in tox_rows)))
    print("등급별 병용:", dict(Counter(r["level"] for r in int_rows)))


if __name__ == "__main__":
    main()
