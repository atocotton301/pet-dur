"""Phase 1 확인용: 제품명 → 주성분 추적 예시.

API 키가 아직 없어서 식약처 의약품안전나라(nedrug) 공개 검색 화면을 소량 조회한다.
※ 서비스용 대량 수집은 공공데이터포털 OpenAPI(인증키)로 바꿀 것. 이 스크립트는 데모·검증용.

사용: python scripts/phase1_product_lookup.py 타이레놀 챔프시럽 판콜에이
"""
import html
import re
import sys
import time
import urllib.parse
import urllib.request

URL = "https://nedrug.mfds.go.kr/searchDrug?itemName={q}&page=1&limit=20"


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", s))).strip()


def search(name: str) -> list[dict]:
    req = urllib.request.Request(URL.format(q=urllib.parse.quote(name)),
                                 headers={"User-Agent": "Mozilla/5.0"})
    text = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S)[1:]:
        c = [_clean(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(c) < 12:
            continue
        rows.append({
            "제품명": c[1].removeprefix("제품명").strip(),
            "업체명": c[3].removeprefix("업체명").strip(),
            "품목기준코드": c[5].removeprefix("품목기준코드"),
            "상태": c[9].removeprefix("취소/취하구분"),
            "주성분": [x.strip() for x in c[11].removeprefix("주성분").split("/") if x.strip()],
        })
    return rows


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for q in sys.argv[1:] or ["타이레놀", "챔프시럽", "판콜에이"]:
        print(f"## {q}")
        for r in search(q):
            print(f"- {r['제품명']} ({r['업체명']}, {r['품목기준코드']}, {r['상태']})")
            for ing in r["주성분"]:
                print(f"    └ {ing}")
        time.sleep(1)  # 서버 부담 줄이기
