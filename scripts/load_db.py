"""시드 CSV + 공공데이터 원본 → SQLite DB. 매번 새로 만든다(재실행 가능).

사용: python scripts/load_db.py [--db data/app.db] [--no-raw]
  --no-raw : data/raw 공공데이터(동물약·동물병원) 없이 규칙·제품 샘플만 적재 (테스트용)
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.normalize import norm, norm_ingredient, split_names, substance_key  # noqa: E402

DATA = ROOT / "data"
CHECKED_ON = "2026-11-23"


def read_csv(p: Path, enc: str = "utf-8-sig") -> list[dict]:
    if not p.exists():
        return []
    with p.open(encoding=enc) as fh:
        return list(csv.DictReader(fh))


class Loader:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.sub_by_key: dict[str, int] = {}
        self.alias_index: dict[str, int] = {}   # 정규화 별칭 → substance_id
        self.text_ids: dict[tuple[str, str], int] = {}
        self.source_ids: dict[str, int] = {}
        self.company_ids: dict[str, int] = {}
        self.unmatched_ingredients: dict[str, int] = {}

    # ---------- 공통 ----------
    def text_id(self, table: str, text: str) -> int | None:
        text = (text or "").strip()
        if not text:
            return None
        k = (table, text)
        if k not in self.text_ids:
            self.con.execute(f"INSERT OR IGNORE INTO {table}(text) VALUES (?)", (text,))
            self.text_ids[k] = self.con.execute(f"SELECT id FROM {table} WHERE text=?", (text,)).fetchone()[0]
        return self.text_ids[k]

    def source_id(self, name: str, url: str, tier: int) -> int:
        if url not in self.source_ids:
            self.con.execute("INSERT INTO source(name,url,tier) VALUES (?,?,?)", (name, url, int(tier)))
            self.source_ids[url] = self.con.execute("SELECT id FROM source WHERE url=?", (url,)).fetchone()[0]
        return self.source_ids[url]

    def company_id(self, name: str) -> int | None:
        name = (name or "").strip()
        if not name:
            return None
        if name not in self.company_ids:
            self.con.execute("INSERT OR IGNORE INTO company(name) VALUES (?)", (name,))
            self.company_ids[name] = self.con.execute("SELECT id FROM company WHERE name=?", (name,)).fetchone()[0]
        return self.company_ids[name]

    def add_alias(self, sid: int, alias: str, alias_type: str) -> None:
        a = norm(alias)
        if len(a) < 2:
            return
        self.con.execute("INSERT OR IGNORE INTO substance_alias(substance_id,alias,alias_norm,alias_type) VALUES (?,?,?,?)",
                         (sid, alias.strip(), a, alias_type))
        self.alias_index.setdefault(a, sid)
        self.alias_index.setdefault(norm_ingredient(alias), sid)

    def substance(self, ko: str, en: str, type_code: str) -> int:
        key = substance_key(ko)
        if key not in self.sub_by_key:
            cur = self.con.execute("INSERT INTO substance(key,name_ko,name_en,type_code) VALUES (?,?,?,?)",
                                   (key, ko.strip(), (en or "").strip(), type_code))
            self.sub_by_key[key] = cur.lastrowid
            sid = cur.lastrowid
            self.add_alias(sid, ko, "표준명")
            if en:
                self.add_alias(sid, en, "영문")
            for part in split_names(ko)[1:]:
                self.add_alias(sid, part, "동의어")
        else:
            sid = self.sub_by_key[key]
            self.add_alias(sid, ko, "동의어")
            if en:
                self.add_alias(sid, en, "영문")
        return sid

    # ---------- 단계별 ----------
    def lookups(self) -> None:
        c = self.con
        c.executemany("INSERT INTO substance_type VALUES (?,?)", [
            ("drug_ingredient", "의약품 성분"), ("drug_class", "약물군"), ("food", "음식"),
            ("plant", "식물"), ("household", "생활용품")])
        c.executemany("INSERT INTO risk_level VALUES (?,?,?)", [
            ("danger", "위험", 3), ("caution", "주의", 2), ("safe", "일반적으로 독성 보고 없음", 1)])
        c.executemany("INSERT INTO interaction_level VALUES (?,?,?)", [
            ("avoid", "함께 쓰면 안 됨", 3), ("caution", "주의", 2)])
        groups = {}
        for r in read_csv(DATA / "species.csv"):
            if r["group"] not in groups:
                groups[r["group"]] = c.execute("INSERT INTO species_group(name) VALUES (?)", (r["group"],)).lastrowid
            c.execute("INSERT INTO species(code,name_ko,group_id,sort_order) VALUES (?,?,?,?)",
                      (r["code"], r["name_ko"], groups[r["group"]], int(r["sort_order"])))
        self.species_ids = dict(c.execute("SELECT code,id FROM species"))

    def rules(self) -> None:
        srcs: dict[str, list[dict]] = {}
        for s in read_csv(DATA / "rule_sources_seed.csv"):
            srcs.setdefault(s["rule_key"], []).append(s)
        for r in read_csv(DATA / "rules_seed.csv"):
            sid = self.substance(r["substance_ko"], r["substance_en"], r["substance_type"])
            cur = self.con.execute(
                "INSERT INTO toxicity_rule(substance_id,species_id,risk_code,mechanism_id,review_status) VALUES (?,?,?,?,?)",
                (sid, self.species_ids[r["species"]], r["risk"], self.text_id("mechanism", r["mechanism_ko"]), r["review_status"]))
            rid = cur.lastrowid
            for s in filter(None, (x.strip() for x in r["symptoms_ko"].split(";"))):
                self.con.execute("INSERT OR IGNORE INTO rule_symptom VALUES (?,?)", (rid, self.text_id("symptom", s)))
            for i, a in enumerate(filter(None, (x.strip() for x in r["first_aid_ko"].split(";")))):
                self.con.execute("INSERT OR IGNORE INTO rule_action VALUES (?,?,?)", (rid, self.text_id("first_aid_action", a), i))
            for s in srcs.get(r["rule_key"], []):
                self.con.execute("INSERT OR IGNORE INTO rule_source VALUES (?,?,?,?)",
                                 (rid, self.source_id(s["source_name"], s["source_url"], s["source_tier"]), s["checked_on"], s["evidence"]))
        for r in read_csv(DATA / "interactions_seed.csv"):
            a = self.substance(r["a_ko"], r["a_en"], r["a_type"] or "drug_ingredient")
            b = self.substance(r["b_ko"], r["b_en"], r["b_type"] or "drug_ingredient")
            a, b = min(a, b), max(a, b)
            cur = self.con.execute(
                "INSERT INTO interaction_rule(substance_a_id,substance_b_id,species_id,level_code,mechanism_id,advice_id,review_status) "
                "VALUES (?,?,?,?,?,?,?)",
                (a, b, self.species_ids[r["species"]], r["level"], self.text_id("mechanism", r["mechanism_ko"]),
                 self.text_id("first_aid_action", r["advice_ko"]), r["review_status"]))
            for s in srcs.get(r["rule_key"], []):
                self.con.execute("INSERT OR IGNORE INTO interaction_source VALUES (?,?,?,?)",
                                 (cur.lastrowid, self.source_id(s["source_name"], s["source_url"], s["source_tier"]),
                                  s["checked_on"], s["evidence"]))

    def class_members(self) -> None:
        p = DATA / "seed_parts" / "class_members.json"
        if not p.exists():
            print("※ class_members.json 없음 — 약물군 소속 없이 적재")
            return
        for m in json.loads(p.read_text(encoding="utf-8")).get("members", []):
            cls = self.alias_index.get(norm(m["class_en"]))
            if cls is None:  # 병용 규칙에 없는 약물군이면 굳이 만들지 않는다
                continue
            mem = self.substance(m["member_ko"], m["member_en"], "drug_ingredient")
            self.con.execute("INSERT OR IGNORE INTO substance_class_member VALUES (?,?,?,?)",
                             (cls, mem, self.source_id(m["source_name"], m["source_url"], m["source_tier"]), CHECKED_ON))

    def manual_aliases(self) -> None:
        for r in read_csv(DATA / "aliases_seed.csv"):
            sid = self.alias_index.get(norm(r["substance"]))
            if sid is None:
                print(f"※ 별칭 대상 없음: {r['alias']} → {r['substance']}")
                continue
            self.add_alias(sid, r["alias"], r["alias_type"])

    def human_products(self) -> None:
        for r in read_csv(DATA / "human_products_sample.csv"):
            self.con.execute("INSERT OR IGNORE INTO human_drug_product VALUES (?,?,?,?)",
                             (r["item_seq"], r["name"], norm(r["name"]), self.company_id(r["company"])))
            for raw in filter(None, (x.strip() for x in r["ingredients_raw"].split("/"))):
                sid = self.alias_index.get(norm_ingredient(raw)) or self.alias_index.get(norm(raw))
                if sid is None:
                    self.unmatched_ingredients[raw] = self.unmatched_ingredients.get(raw, 0) + 1
                self.con.execute("INSERT OR IGNORE INTO product_ingredient VALUES (?,?,?)", (r["item_seq"], raw, sid))

    def vet_products(self) -> int:
        rows = read_csv(DATA / "raw" / "vetdrug" / "vetdrug_permit_20250925.csv")
        for r in rows:
            self.con.execute(
                "INSERT INTO vet_drug_product(permit_no,name,name_norm,name_en,company_id,usage_type,permit_date,dosage_form) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (r["허가번호"], r["품목명"], norm(r["품목명"]), r.get("영문품목명") or None, self.company_id(r["업체명"]),
                 r["용도"], r["허가일"], r.get("제형") or None))
        return len(rows)

    def clinics(self) -> int:
        n = 0
        for r, lat, lng in localdata_rows(DATA / "raw" / "clinic" / "animal_hospitals.csv"):
            name = r["사업장명"].strip()
            self.con.execute("INSERT INTO vet_clinic VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                r["관리번호"], name, r["도로명주소"] or None, (r["지번주소"] or "").strip() or None,
                (r["전화번호"] or "").strip() or None, lat, lng, None, int("24" in name), None, r["최종수정시점"]))
            n += 1
        return n

    def places(self) -> dict:
        self.con.executemany("INSERT INTO place_category VALUES (?,?,?)",
                             [(c, label, i) for i, (c, label, _, _) in enumerate(PLACE_FILES)])
        counts = {}
        for code, label, fname, dataset in PLACE_FILES:
            n = 0
            for r, lat, lng in localdata_rows(DATA / "raw" / "place" / fname):
                self.con.execute(
                    "INSERT OR IGNORE INTO place(category_code,ext_id,name,address,tel,lat,lng,dataset,source_url,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (code, r["관리번호"], r["사업장명"].strip(), r.get("도로명주소") or (r.get("지번주소") or "").strip() or None,
                     (r.get("전화번호") or "").strip() or None, lat, lng, dataset,
                     f"https://file.localdata.go.kr/file/{fname.removesuffix('.csv')}/info", r.get("최종수정시점")))
                n += 1
            counts[f"place_{code}"] = n
        return counts


# (분류 코드, 화면 이름, data/raw/place 파일명, 데이터셋 이름) — LOCALDATA 동물 업종, 소관: 농림축산식품부
PLACE_FILES = [
    ("boarding", "유치원·호텔", "animal_boarding.csv", "동물_동물위탁관리업"),
    ("grooming", "미용", "pet_grooming.csv", "동물_동물미용업"),
]


def localdata_rows(p: Path):
    """LOCALDATA 표준 CSV에서 영업 중이고 좌표가 있는 행을 (행, 위도, 경도)로. 좌표 EPSG:5174 → WGS84."""
    if not p.exists():
        return
    from pyproj import Transformer
    tf = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
    for enc in ("cp949", "utf-8-sig"):
        try:
            rows = read_csv(p, enc=enc)
            break
        except UnicodeDecodeError:
            continue
    for r in rows:
        if r.get("영업상태명") != "영업/정상" or not (r.get("좌표정보(X)") or "").strip():
            continue
        lng, lat = tf.transform(float(r["좌표정보(X)"]), float(r["좌표정보(Y)"]))
        if 33 < lat < 39 and 124 < lng < 132:  # 좌표 이상치 제외
            yield r, lat, lng


def _empty_places(L: "Loader") -> dict:
    L.con.executemany("INSERT INTO place_category VALUES (?,?,?)",
                      [(c, label, i) for i, (c, label, _, _) in enumerate(PLACE_FILES)])
    return {}


def build(db_path: Path, with_raw: bool = True) -> dict:
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.executescript((ROOT / "app" / "schema.sql").read_text(encoding="utf-8"))
    L = Loader(con)
    L.lookups()
    L.rules()
    L.class_members()
    L.manual_aliases()
    L.human_products()
    stats = {"vet_products": L.vet_products() if with_raw else 0, "clinics": L.clinics() if with_raw else 0}
    place_counts = L.places() if with_raw else _empty_places(L)
    stats.update(place_counts)
    for t in ["substance", "substance_alias", "toxicity_rule", "interaction_rule", "substance_class_member",
              "source", "human_drug_product", "product_ingredient"]:
        stats[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    stats["product_ingredient_unmatched"] = con.execute(
        "SELECT COUNT(*) FROM product_ingredient WHERE substance_id IS NULL").fetchone()[0]
    con.executemany("INSERT INTO meta VALUES (?,?)", [(k, str(v)) for k, v in stats.items()])
    con.commit()
    con.close()
    stats["_unmatched"] = L.unmatched_ingredients
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DATA / "app.db"))
    ap.add_argument("--no-raw", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    st = build(Path(a.db), with_raw=not a.no_raw)
    um = st.pop("_unmatched")
    for k, v in st.items():
        print(f"{k}: {v}")
    print(f"규칙 DB에 없는 성분 표기 {len(um)}종 (예: {', '.join(list(um)[:8])})")
