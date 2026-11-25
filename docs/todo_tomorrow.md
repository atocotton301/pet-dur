# 내일 할 일 — API 키·데이터 (2026-11-25 작성)

## 1. 공공데이터포털 인증키 (무료, 하나면 됨)
[data.go.kr](https://www.data.go.kr)에 로그인한 뒤 아래 2개를 각각 **활용신청**한다. 개발계정은 자동승인이다.

| API | 쓰는 곳 |
|---|---|
| 식품의약품안전처_의약품 제품 허가정보 (검색창에 "의약품 제품 허가정보") | 사람 약 샘플 122개 → 전체 품목 |
| [한국관광공사_반려동물_동반여행_서비스](https://www.data.go.kr/data/15135102/openapi.do) | 내 주변 탭: 반려동물 동반 카페·음식점·숙소 |

- 마이페이지 → 인증키에서 **일반 인증키(Decoding)**를 복사한다. 신청한 API 모두에 같은 키 하나를 쓴다.
- 프로젝트의 `.env.example`을 `.env`로 복사하고 `DATA_GO_KR_KEY=` 뒤에 붙여 넣는다. `.env`는 git에 올라가지 않는다.
- **키를 채팅에 붙여 넣지 말 것.** `.env`에 넣었다고만 알려 주면 된다.

## 2. LOCALDATA 파일 2개 (키 필요 없음)
오늘 file.localdata.go.kr 접속이 안 돼서 받지 못했다. 내일 내가 다시 시도한다. 그래도 안 되면 직접 받아서 넣으면 된다.
- [file.localdata.go.kr](https://file.localdata.go.kr) → 동물 → **동물_동물위탁관리업**, **동물_동물미용업** → 전체 다운로드(CSV)
- 저장 위치: `data/raw/place/animal_boarding.csv`, `data/raw/place/pet_grooming.csv`
- 그다음 `python scripts/load_db.py`를 실행하면 내 주변 탭에 바로 나온다.
