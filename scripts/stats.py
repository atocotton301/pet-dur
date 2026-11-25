"""기획서·발표용 수치를 DB에서 뽑아 docs/contest_metrics.md로 저장한다. 재실행 가능.

사용: python scripts/stats.py
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "app.db"

PUBLIC_DATA = [
    # (이름, 제공기관, 소관, 출처, 테이블, 조건)
    ("동물용의약품 품목허가 현황", "농림축산검역본부", "농림축산식품부",
     "공공데이터포털 파일데이터 15150757", "vet_drug_product", ""),
    ("동물_동물병원 인허가 정보", "행정안전부(LOCALDATA)", "농림축산식품부(동물보호법)",
     "공공데이터포털 15045050 / file.localdata.go.kr", "vet_clinic", ""),
    ("의약품 제품 허가정보 (상비약 샘플)", "식품의약품안전처", "식품의약품안전처",
     "의약품안전나라 공개 검색 (OpenAPI 전환 예정)", "human_drug_product", ""),
]


def q(con, sql):
    return con.execute(sql).fetchone()[0]


def main() -> None:
    con = sqlite3.connect(DB)
    has_place = con.execute("SELECT 1 FROM sqlite_master WHERE name='place'").fetchone()
    rows = []
    for name, org, owner, src, table, _ in PUBLIC_DATA:
        rows.append((name, org, owner, src, q(con, f"SELECT COUNT(*) FROM {table}")))
    if has_place:
        for cat, name, src in con.execute("SELECT category, MIN(dataset), MIN(source) FROM place GROUP BY category"):
            n = q(con, f"SELECT COUNT(*) FROM place WHERE category='{cat}'")
            rows.append((name, "행정안전부(LOCALDATA)" if "localdata" in src else src, "농림축산식품부(동물보호법)"
                         if "localdata" in src else "-", src, n))

    tox = dict(con.execute("SELECT risk_code, COUNT(*) FROM toxicity_rule GROUP BY risk_code"))
    inter = dict(con.execute("SELECT level_code, COUNT(*) FROM interaction_rule GROUP BY level_code"))
    by_species = con.execute(
        "SELECT s.name_ko, (SELECT COUNT(*) FROM toxicity_rule t WHERE t.species_id=s.id), "
        "(SELECT COUNT(*) FROM interaction_rule i WHERE i.species_id=s.id) FROM species s ORDER BY s.sort_order").fetchall()
    tiers = dict(con.execute("SELECT tier, COUNT(*) FROM source GROUP BY tier"))
    types = dict(con.execute("SELECT t.label_ko, COUNT(*) FROM toxicity_rule r JOIN substance s ON s.id=r.substance_id "
                             "JOIN substance_type t ON t.code=s.type_code GROUP BY t.label_ko"))
    mapped = q(con, "SELECT COUNT(*) FROM human_drug_product p WHERE EXISTS (SELECT 1 FROM product_ingredient i "
                    "WHERE i.item_seq=p.item_seq AND i.substance_id IS NOT NULL)")

    L = [f"# 기획서용 수치 (자동 생성: {dt.date.today().isoformat()}, `python scripts/stats.py`)", "",
         "## 사용 공공데이터", "", "| 데이터 | 제공 | 소관 부처 | 출처 | 적재 건수 |", "|---|---|---|---|---|"]
    L += [f"| {a} | {b} | {c} | {d} | {e:,} |" for a, b, c, d, e in rows]
    L += ["", f"- 공공데이터 **{len(rows)}종**, 적재 합계 **{sum(r[4] for r in rows):,}건**",
          f"- 동물병원은 영업 중이고 좌표가 있는 곳만 적재(원본 10,676행 중)", "",
          "## 규칙 DB (서비스 핵심 자산)", "",
          f"- 지원 종: **{q(con, 'SELECT COUNT(*) FROM species')}종** (개, 고양이, 토끼, 햄스터, 고슴도치, 앵무새류)",
          f"- 병용 규칙: **{sum(inter.values())}건** (함께 쓰면 안 됨 {inter.get('avoid', 0)} · 주의 {inter.get('caution', 0)})",
          f"- 독성 규칙: **{sum(tox.values())}건** (위험 {tox.get('danger', 0)} · 주의 {tox.get('caution', 0)} · 독성 보고 없음 {tox.get('safe', 0)})",
          f"- 유형별 독성 규칙: " + ", ".join(f"{k} {v}" for k, v in types.items()),
          f"- 약물군 소속: {q(con, 'SELECT COUNT(*) FROM substance_class_member')}건 (약물군 {q(con, 'SELECT COUNT(DISTINCT class_id) FROM substance_class_member')}개)",
          f"- 출처 문헌·페이지: **{sum(tiers.values())}개** (1등급 논문·정부기관 {tiers.get(1, 0)} · 2등급 수의 매뉴얼·대학·ASPCA {tiers.get(2, 0)} · 3등급 {tiers.get(3, 0)})",
          f"- 감수 상태: 전 규칙 미감수 (자문 수의사 검토 예정)", "",
          "| 종 | 독성 규칙 | 병용 규칙 |", "|---|---|---|"]
    L += [f"| {n} | {t} | {i} |" for n, t, i in by_species]
    L += ["", "## 검색 대상", "",
          f"- 사람 약 제품(샘플): {q(con, 'SELECT COUNT(*) FROM human_drug_product')}개, 이 중 규칙이 있는 성분을 포함한 제품 {mapped}개",
          f"- 동물용 의약품 제품명: {q(con, 'SELECT COUNT(*) FROM vet_drug_product'):,}개",
          f"- 검색 별칭(동의어·영문·오타·성분 표기): {q(con, 'SELECT COUNT(*) FROM substance_alias')}개"]
    out = ROOT / "docs" / "contest_metrics.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
