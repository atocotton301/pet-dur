"""조회·판정 로직. API와 테스트가 함께 쓴다.

원칙
- 규칙이 없으면 '정보 없음(unknown)'. 절대 '안전'으로 바꾸지 않는다.
- 제품 종합 등급 = 연결된 성분 중 가장 위험한 등급. 알려진 성분이 전부 안전이어도
  미확인 성분이 하나라도 있으면 종합은 '정보 없음'.
- 병용: 입력 항목 쌍마다 (성분 + 성분이 속한 약물군) × (성분 + 약물군) 조합을 규칙에서 찾는다.
"""
from __future__ import annotations

import difflib
import math
import sqlite3
from itertools import combinations

from .normalize import norm, norm_ingredient

RISK_SEVERITY = {"unknown": 0, "safe": 1, "caution": 2, "danger": 3}
RISK_LABEL = {
    "danger": "위험",
    "caution": "주의",
    "safe": "일반적으로 독성 보고가 없습니다",
    "unknown": "확인된 정보 없음 — 수의사 상담을 권장합니다",
}
LEVEL_SEVERITY = {"unknown": 0, "caution": 2, "avoid": 3}
LEVEL_LABEL = {
    "avoid": "함께 쓰면 안 됩니다",
    "caution": "함께 쓸 때 주의가 필요합니다",
    "unknown": "확인된 상호작용 정보 없음 — 수의사 상담을 권장합니다",
}
DISCLAIMER = "이 정보는 수의사 진료를 대체하지 않습니다."
VET_PRODUCT_NOTE = ("동물용 의약품입니다. 수의사 처방과 제품 라벨에 적힌 대상 동물·용법대로만 사용하세요. "
                    "다른 종(예: 개·고양이용 제품을 토끼·새에게)에게 쓰지 마세요.")


class NotFound(Exception):
    pass


def species_id(con: sqlite3.Connection, code: str) -> int:
    row = con.execute("SELECT id FROM species WHERE code=?", (code,)).fetchone()
    if not row:
        raise NotFound(f"지원하지 않는 종: {code}")
    return row[0]


def list_species(con: sqlite3.Connection) -> list[dict]:
    q = ("SELECT s.code, s.name_ko, g.name FROM species s JOIN species_group g ON g.id=s.group_id "
         "ORDER BY s.sort_order")
    return [{"code": c, "name": n, "group": g} for c, n, g in con.execute(q)]


# ---------------- 독성 판정 ----------------
def _sources(con, table: str, rule_id: int) -> list[dict]:
    q = (f"SELECT s.name, s.url, s.tier, x.checked_on FROM {table} x JOIN source s ON s.id=x.source_id "
         f"WHERE x.rule_id=? ORDER BY s.tier, s.name")
    return [{"name": n, "url": u, "tier": t, "checked_on": d} for n, u, t, d in con.execute(q, (rule_id,))]


def substance_verdict(con: sqlite3.Connection, substance_id: int, species: str) -> dict:
    sp = species_id(con, species)
    sub = con.execute("SELECT id, name_ko, name_en, type_code FROM substance WHERE id=?", (substance_id,)).fetchone()
    if not sub:
        raise NotFound(f"물질 없음: {substance_id}")
    base = {"substance_id": sub[0], "name": sub[1], "name_en": sub[2], "type": sub[3], "species": species}
    rule = con.execute(
        "SELECT r.id, r.risk_code, m.text, r.review_status FROM toxicity_rule r "
        "LEFT JOIN mechanism m ON m.id=r.mechanism_id WHERE r.substance_id=? AND r.species_id=?",
        (substance_id, sp)).fetchone()
    if not rule:
        return {**base, "risk": "unknown", "risk_label": RISK_LABEL["unknown"], "mechanism": None,
                "symptoms": [], "first_aid": [], "sources": [], "review_status": None}
    rid, risk, mech, review = rule
    symptoms = [t for (t,) in con.execute(
        "SELECT s.text FROM rule_symptom x JOIN symptom s ON s.id=x.symptom_id WHERE x.rule_id=?", (rid,))]
    actions = [t for (t,) in con.execute(
        "SELECT a.text FROM rule_action x JOIN first_aid_action a ON a.id=x.action_id WHERE x.rule_id=? "
        "ORDER BY x.step_order", (rid,))]
    return {**base, "risk": risk, "risk_label": RISK_LABEL[risk], "mechanism": mech, "symptoms": symptoms,
            "first_aid": actions, "sources": _sources(con, "rule_source", rid), "review_status": review}


def product_verdict(con: sqlite3.Connection, item_seq: str, species: str) -> dict:
    p = con.execute("SELECT p.item_seq, p.name, c.name FROM human_drug_product p "
                    "LEFT JOIN company c ON c.id=p.company_id WHERE p.item_seq=?", (item_seq,)).fetchone()
    if not p:
        raise NotFound(f"제품 없음: {item_seq}")
    ingredients = []
    for raw, sid in con.execute("SELECT raw_name, substance_id FROM product_ingredient WHERE item_seq=? "
                                "ORDER BY rowid", (item_seq,)):
        if sid is None:
            ingredients.append({"raw_name": raw, "substance_id": None, "risk": "unknown",
                                "risk_label": RISK_LABEL["unknown"]})
        else:
            ingredients.append({"raw_name": raw, **substance_verdict(con, sid, species)})
    overall = combine_risks([i["risk"] for i in ingredients])
    return {"item_seq": p[0], "name": p[1], "company": p[2], "species": species, "kind": "human_drug",
            "overall_risk": overall, "overall_label": RISK_LABEL[overall],
            "has_unknown_ingredient": any(i["risk"] == "unknown" for i in ingredients),
            "ingredients": ingredients, "disclaimer": DISCLAIMER}


def combine_risks(risks: list[str]) -> str:
    """가장 위험한 등급. 단, 위험·주의가 없는데 미확인 성분이 있으면 '정보 없음'."""
    if not risks:
        return "unknown"
    worst = max(risks, key=lambda r: RISK_SEVERITY[r])
    if worst in ("safe", "unknown") and "unknown" in risks:
        return "unknown"
    return worst


# ---------------- 검색 ----------------
def search(con: sqlite3.Connection, q: str, species: str, limit: int = 10) -> dict:
    species_id(con, species)
    qn, qi = norm(q), norm_ingredient(q)
    if len(qn) < 1:
        return {"query": q, "substances": [], "products": [], "vet_products": [], "fuzzy": False}
    hits: dict[int, int] = {}  # substance_id → 점수(낮을수록 좋음)
    for sid, a in con.execute("SELECT substance_id, alias_norm FROM substance_alias "
                              "WHERE alias_norm LIKE ? OR alias_norm=?", (f"%{qn}%", qi)):
        score = 0 if a in (qn, qi) else 1 if a.startswith(qn) else 2
        hits[sid] = min(hits.get(sid, 9), score)
    fuzzy = False
    if not hits and len(qn) >= 2:  # 오타 허용: 별칭과 문자열 유사도
        aliases = con.execute("SELECT substance_id, alias_norm FROM substance_alias").fetchall()
        names = [a for _, a in aliases]
        for m in difflib.get_close_matches(qn, names, n=5, cutoff=0.7):
            for sid, a in aliases:
                if a == m:
                    hits.setdefault(sid, 3)
        fuzzy = bool(hits)
    ordered = sorted(hits, key=lambda s: (hits[s], s))[:limit]
    substances = [substance_verdict(con, sid, species) for sid in ordered]

    products = []
    for (seq,) in con.execute("SELECT item_seq FROM human_drug_product WHERE name_norm LIKE ? "
                              "ORDER BY length(name), name LIMIT ?", (f"%{qn}%", limit)):
        products.append(product_verdict(con, seq, species))
    vet = [{"id": i, "name": n, "company": c, "usage_type": u, "note": VET_PRODUCT_NOTE}
           for i, n, c, u in con.execute(
               "SELECT v.id, v.name, c.name, v.usage_type FROM vet_drug_product v LEFT JOIN company c "
               "ON c.id=v.company_id WHERE v.name_norm LIKE ? ORDER BY length(v.name) LIMIT 5", (f"%{qn}%",))]
    return {"query": q, "species": species, "substances": substances, "products": products,
            "vet_products": vet, "fuzzy": fuzzy, "disclaimer": DISCLAIMER}


# ---------------- 병용 점검 ----------------
def _expand_item(con, item: str) -> dict:
    """'s:12'(물질) 또는 'p:202106954'(제품) → 이름 + 성분 목록."""
    kind, _, ref = item.partition(":")
    if kind == "s":
        row = con.execute("SELECT id, name_ko FROM substance WHERE id=?", (ref,)).fetchone()
        if not row:
            raise NotFound(f"물질 없음: {ref}")
        return {"item": item, "name": row[1], "parts": [{"name": row[1], "substance_id": row[0]}]}
    if kind == "p":
        row = con.execute("SELECT name FROM human_drug_product WHERE item_seq=?", (ref,)).fetchone()
        if not row:
            raise NotFound(f"제품 없음: {ref}")
        parts = [{"name": raw, "substance_id": sid} for raw, sid in con.execute(
            "SELECT raw_name, substance_id FROM product_ingredient WHERE item_seq=? ORDER BY rowid", (ref,))]
        return {"item": item, "name": row[0], "parts": parts}
    raise NotFound(f"항목 형식 오류: {item} (s:물질ID 또는 p:품목기준코드)")


def _with_classes(con, sid: int) -> set[int]:
    ids = {sid}
    ids |= {c for (c,) in con.execute("SELECT class_id FROM substance_class_member WHERE member_id=?", (sid,))}
    return ids


def check_interactions(con: sqlite3.Connection, items: list[str], species: str) -> dict:
    sp = species_id(con, species)
    if len(items) < 2:
        raise NotFound("병용 점검은 2개 이상 필요합니다")
    expanded = [_expand_item(con, it) for it in items]
    pairs = []
    for x, y in combinations(expanded, 2):
        matches, seen, duplicates = [], set(), []
        unknown_parts = sorted({p["name"] for p in x["parts"] + y["parts"] if p["substance_id"] is None})
        for px in x["parts"]:
            for py in y["parts"]:
                if px["substance_id"] is None or py["substance_id"] is None:
                    continue
                if px["substance_id"] == py["substance_id"]:
                    duplicates.append(px["name"])
                for a in _with_classes(con, px["substance_id"]):
                    for b in _with_classes(con, py["substance_id"]):
                        lo, hi = min(a, b), max(a, b)
                        row = con.execute(
                            "SELECT r.id, r.level_code, m.text, f.text, r.review_status, sa.name_ko, sb.name_ko "
                            "FROM interaction_rule r LEFT JOIN mechanism m ON m.id=r.mechanism_id "
                            "LEFT JOIN first_aid_action f ON f.id=r.advice_id "
                            "JOIN substance sa ON sa.id=r.substance_a_id JOIN substance sb ON sb.id=r.substance_b_id "
                            "WHERE r.substance_a_id=? AND r.substance_b_id=? AND r.species_id=?",
                            (lo, hi, sp)).fetchone()
                        if row and row[0] not in seen:
                            seen.add(row[0])
                            matches.append({
                                "rule_id": row[0], "level": row[1], "level_label": LEVEL_LABEL[row[1]],
                                "rule_between": [row[5], row[6]], "via": [px["name"], py["name"]],
                                "mechanism": row[2], "advice": row[3], "review_status": row[4],
                                "sources": _sources(con, "interaction_source", row[0])})
        matches.sort(key=lambda m: -LEVEL_SEVERITY[m["level"]])
        level = matches[0]["level"] if matches else "unknown"
        pairs.append({"a": x["name"], "b": y["name"], "level": level, "level_label": LEVEL_LABEL[level],
                      "matches": matches, "duplicate_ingredients": sorted(set(duplicates)),
                      "unchecked_ingredients": unknown_parts})
    worst = max((p["level"] for p in pairs), key=lambda l: LEVEL_SEVERITY[l])
    return {"species": species, "items": [{"item": e["item"], "name": e["name"]} for e in expanded],
            "overall_level": worst, "overall_label": LEVEL_LABEL[worst], "pairs": pairs, "disclaimer": DISCLAIMER}


# ---------------- 동물병원 ----------------
def nearby_clinics(con: sqlite3.Connection, lat: float, lng: float, limit: int = 10, radius_km: float = 10) -> list[dict]:
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.1))
    rows = con.execute(
        "SELECT mgmt_no, name, road_addr, jibun_addr, tel, lat, lng, is_24h, name_suggests_24h, treats_exotic "
        "FROM vet_clinic WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
        (lat - dlat, lat + dlat, lng - dlng, lng + dlng)).fetchall()
    out = []
    for r in rows:
        d = _haversine(lat, lng, r[5], r[6])
        if d <= radius_km:
            out.append({"id": r[0], "name": r[1], "address": r[2] or r[3], "tel": r[4], "lat": r[5], "lng": r[6],
                        "distance_km": round(d, 2), "is_24h": None if r[7] is None else bool(r[7]),
                        "name_suggests_24h": bool(r[8]), "treats_exotic": None if r[9] is None else bool(r[9]),
                        "links": map_links(r[1], r[2] or r[3], r[5], r[6])})
    return sorted(out, key=lambda c: c["distance_km"])[:limit]


def _haversine(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------- 장소 탭 ----------------
def map_links(name: str, address: str | None, lat: float, lng: float) -> dict:
    """네이버 지도·카카오맵 바로가기. 휴대폰에서는 앱이 설치돼 있으면 앱으로 열린다."""
    from urllib.parse import quote
    label = quote(name.replace(",", " "))
    return {
        "kakao": f"https://map.kakao.com/link/map/{label},{lat:.6f},{lng:.6f}",
        "kakao_route": f"https://map.kakao.com/link/to/{label},{lat:.6f},{lng:.6f}",
        "naver": f"https://map.naver.com/p/search/{quote((name + ' ' + (address or '')).strip())}",
    }


HOSPITAL = ("hospital", "동물병원")


def place_categories(con: sqlite3.Connection) -> list[dict]:
    out = [{"code": HOSPITAL[0], "label": HOSPITAL[1], "count": con.execute("SELECT COUNT(*) FROM vet_clinic").fetchone()[0]}]
    for code, label in con.execute("SELECT code, label_ko FROM place_category ORDER BY sort_order"):
        n = con.execute("SELECT COUNT(*) FROM place WHERE category_code=?", (code,)).fetchone()[0]
        out.append({"code": code, "label": label, "count": n})
    return out


def nearby_places(con: sqlite3.Connection, lat: float, lng: float, categories: list[str] | None = None,
                  limit: int = 30, radius_km: float = 3) -> list[dict]:
    cats = {c["code"]: c["label"] for c in place_categories(con)}
    wanted = [c for c in (categories or list(cats)) if c in cats]
    out = []
    if HOSPITAL[0] in wanted:
        for c in nearby_clinics(con, lat, lng, limit=limit, radius_km=radius_km):
            out.append({"category": HOSPITAL[0], "category_label": HOSPITAL[1], "id": f"h:{c['id']}",
                        "name": c["name"], "address": c["address"], "tel": c["tel"], "lat": c["lat"], "lng": c["lng"],
                        "distance_km": c["distance_km"], "name_suggests_24h": c["name_suggests_24h"],
                        "dataset": "동물_동물병원", "links": map_links(c["name"], c["address"], c["lat"], c["lng"])})
    others = [c for c in wanted if c != HOSPITAL[0]]
    if others:
        dlat = radius_km / 111.0
        dlng = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.1))
        q = (f"SELECT id, category_code, name, address, tel, lat, lng, dataset FROM place "
             f"WHERE category_code IN ({','.join('?' * len(others))}) AND lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?")
        for pid, cat, name, addr, tel, plat, plng, ds in con.execute(q, (*others, lat - dlat, lat + dlat, lng - dlng, lng + dlng)):
            d = _haversine(lat, lng, plat, plng)
            if d <= radius_km:
                out.append({"category": cat, "category_label": cats[cat], "id": f"p:{pid}", "name": name, "address": addr,
                            "tel": tel, "lat": plat, "lng": plng, "distance_km": round(d, 2),
                            "name_suggests_24h": "24" in name, "dataset": ds, "links": map_links(name, addr, plat, plng)})
    return sorted(out, key=lambda p: p["distance_km"])[:limit]
