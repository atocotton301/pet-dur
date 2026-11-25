"""Phase 3 단위 테스트: 제품→성분→종합 등급, '정보 없음' 처리, 동의어·오타 검색, 병용 점검, API."""
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import load_db  # noqa: E402
from app import logic, main  # noqa: E402
from app.normalize import norm_ingredient  # noqa: E402


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("db") / "test.db"
    load_db.build(p, with_raw=False)  # 공공데이터 원본 없이 규칙·제품 샘플만
    con = sqlite3.connect(p)
    con.execute("INSERT INTO vet_clinic(mgmt_no,name,road_addr,lat,lng,name_suggests_24h) VALUES "
                "('T1','테스트24시동물병원','서울 성북구',37.5826,127.0106,1),"
                "('T2','먼동물병원','부산',35.1796,129.0756,0)")
    con.execute("INSERT INTO place(category_code,ext_id,name,address,lat,lng,dataset,source_url) VALUES "
                "('boarding','B1','멍멍유치원','서울 성북구',37.5830,127.0110,'동물_동물위탁관리업','https://example'),"
                "('grooming','G1','뽀송미용실','서울 성북구',37.5900,127.0200,'동물_동물미용업','https://example')")
    con.commit()
    con.close()
    return p


@pytest.fixture()
def con(db_path):
    c = sqlite3.connect(db_path)
    yield c
    c.close()


@pytest.fixture()
def client(db_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", db_path)
    return TestClient(main.app)


def sid(con, name_ko):
    return con.execute("SELECT id FROM substance WHERE name_ko=?", (name_ko,)).fetchone()[0]


def product(con, like):
    return con.execute("SELECT item_seq FROM human_drug_product WHERE name LIKE ? ORDER BY length(name)",
                       (f"%{like}%",)).fetchone()[0]


# ---------- 종합 등급 ----------
@pytest.mark.parametrize("risks,expected", [
    ([], "unknown"),
    (["unknown"], "unknown"),
    (["safe", "unknown"], "unknown"),          # 미확인 성분이 있으면 '안전'이 될 수 없다
    (["safe", "safe"], "safe"),
    (["caution", "unknown"], "caution"),
    (["safe", "caution", "danger", "unknown"], "danger"),
])
def test_combine_risks(risks, expected):
    assert logic.combine_risks(risks) == expected


def test_product_to_ingredients_to_overall(con):
    seq = product(con, "타이레놀콜드-에스")
    v = logic.product_verdict(con, seq, "cat")
    names = [i["raw_name"] for i in v["ingredients"]]
    assert len(names) == 4 and "아세트아미노펜" in names
    assert v["overall_risk"] == "danger"                     # 고양이 아세트아미노펜
    assert v["has_unknown_ingredient"] is True                # 클로르페니라민 등은 규칙 없음
    acet = next(i for i in v["ingredients"] if i["raw_name"] == "아세트아미노펜")
    assert acet["risk"] == "danger" and acet["sources"]       # 출처가 반드시 붙는다


def test_salt_form_ingredient_maps_to_substance(con):
    assert norm_ingredient("슈도에페드린염산염") == "슈도에페드린"
    seq = product(con, "타이레놀콜드-에스")
    row = con.execute("SELECT substance_id FROM product_ingredient WHERE item_seq=? AND raw_name='슈도에페드린염산염'",
                      (seq,)).fetchone()
    assert row[0] == sid(con, "슈도에페드린")


# ---------- 정보 없음 ----------
def test_no_rule_is_unknown_not_safe(con):
    v = logic.substance_verdict(con, sid(con, "포도·건포도"), "bird")
    assert v["risk"] == "unknown"
    assert "확인된 정보 없음" in v["risk_label"] and "수의사" in v["risk_label"]
    assert v["sources"] == []


def test_labels_never_say_definitely_safe():
    for label in [*logic.RISK_LABEL.values(), *logic.LEVEL_LABEL.values()]:
        assert "먹어도 됩니다" not in label and "안전합니다" not in label


# ---------- 검색: 동의어·오타 ----------
def test_search_synonym(con):
    r = logic.search(con, "파라세타몰", "dog")
    assert r["substances"][0]["name"] == "아세트아미노펜"


def test_search_typo_alias(con):
    r = logic.search(con, "초코렛", "dog")
    assert r["substances"][0]["name"] == "초콜릿" and r["substances"][0]["risk"] == "danger"


def test_search_fuzzy_typo(con):
    r = logic.search(con, "아세트아미노핀", "cat")
    assert r["fuzzy"] is True
    assert any(s["name"] == "아세트아미노펜" for s in r["substances"])


def test_search_product_name(con):
    r = logic.search(con, "챔프시럽", "dog")
    assert r["products"] and r["products"][0]["overall_risk"] == "danger"


def test_search_split_alias(con):
    r = logic.search(con, "건포도", "dog")
    assert r["substances"][0]["name"] == "포도·건포도"


# ---------- 병용 ----------
def test_interaction_via_drug_class(con):
    seq = product(con, "덱시부프로펜")  # 사람 NSAID 제품
    r = logic.check_interactions(con, [f"p:{seq}", f"s:{sid(con, '카프로펜')}"], "dog")
    assert r["overall_level"] == "avoid"
    m = r["pairs"][0]["matches"][0]
    assert m["sources"] and m["via"][1] == "카프로펜"


def test_interaction_direct_pair(con):
    r = logic.check_interactions(con, [f"s:{sid(con, '트라마돌')}", f"s:{sid(con, '플루옥세틴')}"], "cat")
    assert r["overall_level"] == "avoid"


def test_interaction_unknown_when_no_rule(con):
    r = logic.check_interactions(con, [f"s:{sid(con, '트라마돌')}", f"s:{sid(con, '플루옥세틴')}"], "rabbit")
    assert r["overall_level"] == "unknown" and "수의사" in r["overall_label"]


def test_interaction_duplicate_ingredient(con):
    a, b = product(con, "타이레놀정500"), product(con, "챔프시럽")
    r = logic.check_interactions(con, [f"p:{a}", f"p:{b}"], "dog")
    assert r["pairs"][0]["duplicate_ingredients"] == ["아세트아미노펜"]


def test_interaction_lists_unchecked_ingredients(con):
    a, b = product(con, "타이레놀콜드-에스"), product(con, "챔프시럽")
    r = logic.check_interactions(con, [f"p:{a}", f"p:{b}"], "dog")
    assert "클로르페니라민말레산염" in r["pairs"][0]["unchecked_ingredients"]


# ---------- API ----------
def test_api_species(client):
    r = client.get("/api/species")
    assert r.status_code == 200 and {s["code"] for s in r.json()} >= {"dog", "cat", "rabbit", "hamster", "bird", "hedgehog"}


def test_api_search_and_disclaimer(client):
    r = client.get("/api/search", params={"q": "타이레놀", "species": "cat"})
    assert r.status_code == 200
    body = r.json()
    assert body["products"] and body["disclaimer"] == logic.DISCLAIMER


def test_api_unknown_species_404(client):
    assert client.get("/api/search", params={"q": "포도", "species": "dragon"}).status_code == 404


def test_api_interactions(client, con):
    items = f"s:{sid(con, '트라마돌')},s:{sid(con, '트라조돈')}"
    r = client.get("/api/interactions/check", params={"items": items, "species": "dog"})
    assert r.status_code == 200 and r.json()["overall_level"] == "avoid"


def test_api_clinics_nearby_only(client):
    r = client.get("/api/clinics", params={"lat": 37.583, "lng": 127.011})
    names = [c["name"] for c in r.json()["clinics"]]
    assert names == ["테스트24시동물병원"]
    assert r.json()["clinics"][0]["is_24h"] is None   # 데이터에 없으면 '모름'


# ---------- 장소 탭 ----------
def test_places_sorted_and_linked(client):
    r = client.get("/api/places", params={"lat": 37.5826, "lng": 127.0106, "radius_km": 3})
    ps = r.json()["places"]
    assert [p["name"] for p in ps] == ["테스트24시동물병원", "멍멍유치원", "뽀송미용실"]
    assert all(p["distance_km"] <= 3 for p in ps)
    links = ps[1]["links"]
    assert links["kakao"].startswith("https://map.kakao.com/link/map/") and "37.583000,127.011000" in links["kakao"]
    assert links["naver"].startswith("https://map.naver.com/p/search/")


def test_places_category_filter(client):
    r = client.get("/api/places", params={"lat": 37.5826, "lng": 127.0106, "categories": "boarding"})
    assert [p["category"] for p in r.json()["places"]] == ["boarding"]


def test_place_categories_include_hospital(client):
    codes = [c["code"] for c in client.get("/api/places/categories").json()]
    assert codes[0] == "hospital" and {"boarding", "grooming"} <= set(codes)


def test_clinic_has_map_links(client):
    c = client.get("/api/clinics", params={"lat": 37.583, "lng": 127.011}).json()["clinics"][0]
    assert "kakao_route" in c["links"]
