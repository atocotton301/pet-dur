"""사람 상비약 제품 → 주성분 샘플 수집 (개발·시연용 소량).

식약처 의약품안전나라 공개 검색 화면을 검색어당 1회, 1.5초 간격으로 조회한다.
※ 서비스용 전체 수집은 공공데이터포털 OpenAPI(인증키)로 교체할 것.

입력: data/product_queries.txt   출력: data/human_products_sample.csv
"""
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase1_product_lookup import search  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    queries = [q.strip() for q in (ROOT / "data" / "product_queries.txt").read_text(encoding="utf-8").splitlines()
               if q.strip() and not q.startswith("#")]
    seen, rows = set(), []
    for q in queries:
        try:
            found = search(q)
        except Exception as e:  # 한 검색어 실패가 전체를 멈추지 않게
            print(f"[실패] {q}: {e}")
            continue
        n = 0
        for r in found:
            if r["상태"] != "정상" or r["품목기준코드"] in seen or "수출용" in r["제품명"]:
                continue
            seen.add(r["품목기준코드"])
            rows.append({"item_seq": r["품목기준코드"], "name": r["제품명"], "company": r["업체명"],
                         "ingredients_raw": "/".join(r["주성분"]), "query": q})
            n += 1
        print(f"{q}: {n}개")
        time.sleep(1.5)
    out = ROOT / "data" / "human_products_sample.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["item_seq", "name", "company", "ingredients_raw", "query"])
        w.writeheader()
        w.writerows(rows)
    print(f"저장: {out.relative_to(ROOT)} ({len(rows)}개 제품)")


if __name__ == "__main__":
    main()
