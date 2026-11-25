# 이거 먹어도 돼? 🐾

> 반려동물 보호자가 집에 있는 **사람 약·음식·식물**을 검색하면, **동물 종별로** 위험한지와 그 이유를 알려줍니다. **같이 먹여도 되는지(병용)**도 확인하고, 위험하면 가까운 동물병원을 안내하는 한국어 서비스입니다.

**이 정보는 수의사 진료를 대체하지 않습니다.**

## 무엇이 다른가
- **국내 제품명으로 검색**: "타이레놀콜드-에스정" → 식약처 품목정보로 성분 4개를 풀고 → 성분별·종별로 판정합니다. 해외 앱(ASPCA, Pet Poison Helpline 등)은 국내 제품명을 모릅니다.
- **병용 점검(핵심)**: 사람 약 성분이 "NSAID계" 같은 약물군 규칙에 연결됩니다. 예: 개가 카프로펜을 먹는 중일 때 애드빌(이부프로펜) → 함께 쓰면 안 됨.
- **약 + 음식 + 식물**을 한 번에, **6종**(개, 고양이, 토끼, 햄스터, 고슴도치, 앵무새류)별로 다룹니다. 특수동물도 포함합니다.
- **근거가 없으면 '안전'이라고 하지 않습니다.** "확인된 정보 없음, 수의사 상담 권장"으로 표시하고, 모든 규칙에 출처와 확인일을 붙입니다. 자문 수의사 감수 상태도 표시합니다.
- **응급 연결**: 위험 결과가 나오면 가까운 영업 중 동물병원(전화 버튼, 24시 추정 표시, 네이버·카카오 지도 바로가기)을 보여줍니다.
- **내 주변 탭(부가 서비스)**: 동물병원·강아지 유치원/호텔·미용실을 지도와 목록으로 보여줍니다(농식품부 소관 동물 업종 인허가 데이터).

## 사용 공공데이터
| 데이터 | 제공 | 용도 |
|---|---|---|
| 동물용의약품 품목허가 현황 ([공공데이터포털 15150757](https://www.data.go.kr/data/15150757/fileData.do)) | 농림축산검역본부 | 동물약 제품명 인식 → "처방·라벨대로, 다른 종에 쓰지 마세요" 안내 |
| 동물_동물병원 인허가 정보 ([공공데이터포털 15045050](https://www.data.go.kr/data/15045050/fileData.do), LOCALDATA) | 행정안전부 (소관: 농림축산식품부) | 위치 기반 응급 병원 안내 |
| 동물_동물위탁관리업·동물미용업 인허가 정보 (LOCALDATA) | 행정안전부 (소관: 농림축산식품부) | 내 주변 탭: 유치원·호텔, 미용실 |
| 의약품 제품 허가정보 | 식품의약품안전처 | 사람 약 제품명 → 주성분. 현재는 상비약 샘플, OpenAPI로 전환 예정 |

건수와 규칙 수는 [docs/contest_metrics.md](docs/contest_metrics.md)에 있습니다(`python scripts/stats.py`로 다시 만들 수 있음).

## 규칙 DB
- 독성 규칙(물질 × 종)과 병용 규칙(성분 A × 성분 B × 종). 근거는 Merck Veterinary Manual, ASPCA, FDA, 수의학 리뷰 논문 등 공개 자료이고, 목록은 [docs/sources.md](docs/sources.md)에 있습니다.
- 출처 등급: 1 = 논문·정부기관, 2 = 수의 매뉴얼·대학·ASPCA, 3 = 임상 해설지. 3등급 출처만으로는 "함께 쓰면 안 됨"을 매기지 않습니다.
- 용량 정보는 제공하지 않습니다. 사람 대상 DUR 금기를 동물 금기로 옮기지 않습니다.
- 수의사 검토용 엑셀은 `python scripts/export_review_xlsx.py`로 만듭니다.

## 실행
```bash
pip install -r requirements.txt
python scripts/load_db.py            # data/app.db 생성 (data/raw 원본이 없으면 --no-raw)
python -m uvicorn app.main:app --port 8000
# 화면: http://localhost:8000   API 문서: http://localhost:8000/docs
pytest tests
```

### 데이터 다시 만들기
| 순서 | 명령 | 내용 |
|---|---|---|
| 1 | `python scripts/fetch_products_nedrug.py` | 상비약 샘플 수집 (`data/product_queries.txt`) |
| 2 | `python scripts/build_seed.py` | `data/seed_parts/*.json`(출처를 읽고 뽑은 규칙 후보) → 검증 → 시드 CSV |
| 3 | `python scripts/load_db.py` | 시드 + 공공데이터 → SQLite |
| 4 | `python scripts/export_review_xlsx.py` | 수의사 검토용 엑셀 |
| 5 | `python scripts/stats.py` | 기획서 수치 |

공공데이터 원본(`data/raw/`)은 용량 때문에 저장소에 넣지 않습니다. 받는 방법은 [docs/phase1_report.md](docs/phase1_report.md)에 있습니다.

## API (`/api`)
| 엔드포인트 | 설명 |
|---|---|
| `GET /api/species` | 지원 종 |
| `GET /api/search?q=&species=` | 물질·사람 약 제품·동물약 검색 (동의어·오타 허용) |
| `GET /api/substance/{id}?species=` | 물질 판정 카드 |
| `GET /api/product/{item_seq}?species=` | 제품 → 성분별 판정 → 종합 등급 |
| `GET /api/interactions/check?items=p:…,s:…&species=` | 병용 점검 |
| `GET /api/clinics?lat=&lng=` | 가까운 동물병원 (네이버·카카오 지도 바로가기 포함) |
| `GET /api/places/categories` | 내 주변 탭 장소 종류와 건수 |
| `GET /api/places?lat=&lng=&categories=` | 내 주변: 동물병원·유치원/호텔·미용 (반경 3km, 지도 바로가기 포함) |

## 구조
```
app/        FastAPI(main.py), 판정 로직(logic.py), 정규화(normalize.py), 스키마(schema.sql), 화면(static/)
scripts/    수집·검증·적재·내보내기 스크립트 (모두 재실행 가능)
data/       시드 CSV, 규칙 후보 JSON, 상비약 샘플 (raw/는 git 제외)
docs/       단계별 보고, 출처 목록, 시연 시나리오, 기획서 수치, 확장 계획
tests/      pytest
```

## 문서
[Phase 1 데이터 확인·ERD](docs/phase1_report.md) · [Phase 2 규칙 시드](docs/phase2_report.md) · [Phase 3 API](docs/phase3_report.md) · [Phase 4 화면](docs/phase4_report.md) · [시연 시나리오](docs/demo_scenarios.md) · [확장 계획](docs/expansion_plan.md)

*2027 농림축산식품부 「농업·농촌 공공데이터+AI 활용 창업경진대회」 제품·서비스 부문 출품 예정 — 한성대학교 응용인공지능학과*
