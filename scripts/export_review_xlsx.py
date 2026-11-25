"""자문 수의사 검토용 엑셀을 만든다. 재실행 가능.

입력: data/rules_seed.csv, data/interactions_seed.csv, data/rule_sources_seed.csv
출력: out/수의사검토_규칙_YYYYMMDD.xlsx
  - 시트 '안내' : 검토 방법
  - 시트 '병용 규칙', '독성 규칙' : 규칙 + 출처 + [판정(맞음/틀림/모름) · 수정 등급 · 의견] 입력칸
사용: python scripts/export_review_xlsx.py
"""
from __future__ import annotations

import csv
import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "out"

SPECIES_KO = {"dog": "개", "cat": "고양이", "rabbit": "토끼", "hamster": "햄스터",
              "bird": "앵무새류", "hedgehog": "고슴도치"}
RISK_KO = {"danger": "🔴 위험", "caution": "🟠 주의", "safe": "🟢 일반적으로 독성 보고 없음"}
LEVEL_KO = {"avoid": "🔴 함께 쓰면 안 됨", "caution": "🟠 주의"}
TYPE_KO = {"drug_ingredient": "의약품 성분", "drug_class": "약물군", "food": "음식",
           "plant": "식물", "household": "생활용품"}
FILL = {"danger": "F8D7DA", "avoid": "F8D7DA", "caution": "FFE5CC", "safe": "D4EDDA"}
REVIEW_FILL = PatternFill("solid", fgColor="FFF9DB")
HEAD_FILL = PatternFill("solid", fgColor="343A40")
THIN = Side(style="thin", color="CCCCCC")


def read(name: str) -> list[dict]:
    p = DATA / name
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def sources_by_rule() -> dict[str, str]:
    m = defaultdict(list)
    for s in read("rule_sources_seed.csv"):
        m[s["rule_key"]].append(f"[{s['source_tier']}등급] {s['source_name']}\n{s['source_url']}")
    return {k: "\n\n".join(v) for k, v in m.items()}


def sheet(wb: Workbook, title: str, header: list[str], rows: list[list], grade_col: int,
          grade_choices: str, color_keys: list[str], widths: list[int]) -> None:
    ws = wb.create_sheet(title)
    review_cols = ["판정", "수정 등급", "의견", "검토자", "검토일"]
    full = header + review_cols
    ws.append(full)
    for c, _ in enumerate(full, 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD_FILL if c <= len(header) else PatternFill("solid", fgColor="B08900")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for r, (row, key) in enumerate(zip(rows, color_keys), start=2):
        ws.append(row + [""] * len(review_cols))
        for c in range(1, len(full) + 1):
            cell = ws.cell(row=r, column=c)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
            if c > len(header):
                cell.fill = REVIEW_FILL
        ws.cell(row=r, column=grade_col).fill = PatternFill("solid", fgColor=FILL.get(key, "FFFFFF"))
    n = len(rows) + 1
    if rows:
        v1 = DataValidation(type="list", formula1='"맞음,틀림,모름"', allow_blank=True)
        v2 = DataValidation(type="list", formula1=f'"{grade_choices}"', allow_blank=True)
        ws.add_data_validation(v1)
        ws.add_data_validation(v2)
        v1.add(f"{get_column_letter(len(header) + 1)}2:{get_column_letter(len(header) + 1)}{n}")
        v2.add(f"{get_column_letter(len(header) + 2)}2:{get_column_letter(len(header) + 2)}{n}")
    for i, wdt in enumerate(widths + [10, 16, 40, 10, 12], start=1):
        ws.column_dimensions[get_column_letter(i)].width = wdt
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(full))}{n}"


def main() -> None:
    src = sources_by_rule()
    wb = Workbook()
    guide = wb.active
    guide.title = "안내"
    lines = [
        "반려동물 약·음식 안전 조회 서비스 — 규칙 검토 요청",
        f"생성일: {dt.date.today().isoformat()}",
        "",
        "■ 부탁드리는 것",
        "각 규칙의 노란 칸에 '판정'(맞음/틀림/모름)을 골라 주세요. 틀림이면 '수정 등급'과 '의견'을 적어 주세요.",
        "",
        "■ 등급 뜻",
        "독성: 🔴 위험 / 🟠 주의 / 🟢 일반적으로 독성 보고 없음 (규칙이 없으면 서비스는 '확인된 정보 없음, 수의사 상담 권장'으로 표시)",
        "병용: 🔴 함께 쓰면 안 됨 / 🟠 주의",
        "",
        "■ 원칙",
        "· 모든 규칙은 공개 수의학 자료에서 확인한 내용만 넣었습니다(출처 칸 참고). 출처 등급: 1=논문·교과서·정부기관, 2=대학·학회·Merck·ASPCA, 3=임상 해설지.",
        "· 용량 정보는 넣지 않았습니다. 사람 대상 DUR 금기는 근거로 쓰지 않았습니다.",
        "· '출처 충돌=Y'는 자료끼리 등급이 달라 더 위험한 쪽으로 둔 규칙입니다. 특히 봐 주세요.",
        "· 병용 규칙은 서비스의 핵심 기능이라 우선 검토 부탁드립니다.",
    ]
    for ln in lines:
        guide.append([ln])
    guide["A1"].font = Font(bold=True, size=14)
    guide.column_dimensions["A"].width = 120

    inter = read("interactions_seed.csv")
    sheet(wb, "병용 규칙",
          ["규칙ID", "종", "성분/약 A", "성분/약 B", "현재 등급", "기전", "보호자 안내", "출처 충돌", "출처"],
          [[r["rule_key"], SPECIES_KO.get(r["species"], r["species"]),
            f"{r['a_ko']} ({r['a_en']})", f"{r['b_ko']} ({r['b_en']})",
            LEVEL_KO.get(r["level"], r["level"]), r["mechanism_ko"], r["advice_ko"],
            r["source_conflict"], src.get(r["rule_key"], "")] for r in inter],
          grade_col=5, grade_choices="함께 쓰면 안 됨,주의,상호작용 없음,근거 부족",
          color_keys=[r["level"] for r in inter], widths=[22, 8, 22, 22, 16, 40, 40, 8, 50])

    tox = read("rules_seed.csv")
    sheet(wb, "독성 규칙",
          ["규칙ID", "종", "물질", "유형", "현재 등급", "기전", "증상", "대처", "출처 충돌", "출처"],
          [[r["rule_key"], SPECIES_KO.get(r["species"], r["species"]),
            f"{r['substance_ko']} ({r['substance_en']})", TYPE_KO.get(r["substance_type"], r["substance_type"]),
            RISK_KO.get(r["risk"], r["risk"]), r["mechanism_ko"], r["symptoms_ko"], r["first_aid_ko"],
            r["source_conflict"], src.get(r["rule_key"], "")] for r in tox],
          grade_col=5, grade_choices="위험,주의,일반적으로 안전,근거 부족",
          color_keys=[r["risk"] for r in tox], widths=[22, 8, 22, 10, 16, 40, 30, 30, 8, 50])

    OUT.mkdir(exist_ok=True)
    path = OUT / f"수의사검토_규칙_{dt.date.today():%Y%m%d}.xlsx"
    wb.save(path)
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"저장: {path.relative_to(ROOT)}  (병용 {len(inter)}건, 독성 {len(tox)}건)")


if __name__ == "__main__":
    main()
