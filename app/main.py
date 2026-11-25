"""FastAPI 앱. 실행: uvicorn app.main:app --reload"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import logic

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).resolve().parent.parent / "data" / "app.db"))

app = FastAPI(title="이거 먹어도 돼? API", version="0.1.0",
              description="반려동물 약·음식·식물 안전 및 병용 조회. " + logic.DISCLAIMER)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
                   allow_methods=["GET"], allow_headers=["*"])
api = APIRouter(prefix="/api")


@contextmanager
def db():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        yield con
    finally:
        con.close()


def _run(fn, *args, **kw):
    with db() as con:
        try:
            return fn(con, *args, **kw)
        except logic.NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))


@api.get("/species")
def get_species():
    return _run(logic.list_species)


@api.get("/search")
def get_search(q: str = Query(..., min_length=1, max_length=50), species: str = Query(...)):
    return _run(logic.search, q, species)


@api.get("/substance/{substance_id}")
def get_substance(substance_id: int, species: str = Query(...)):
    return {**_run(logic.substance_verdict, substance_id, species), "disclaimer": logic.DISCLAIMER}


@api.get("/product/{item_seq}")
def get_product(item_seq: str, species: str = Query(...)):
    return _run(logic.product_verdict, item_seq, species)


@api.get("/interactions/check")
def get_interactions(items: str = Query(..., description="쉼표 구분. s:물질ID 또는 p:품목기준코드. 예: p:202106954,s:12"),
                     species: str = Query(...)):
    parts = [x.strip() for x in items.split(",") if x.strip()]
    if len(parts) > 10:
        raise HTTPException(400, "한 번에 10개까지 점검할 수 있습니다")
    return _run(logic.check_interactions, parts, species)


@api.get("/clinics")
def get_clinics(lat: float = Query(..., ge=33, le=39), lng: float = Query(..., ge=124, le=132),
                limit: int = Query(10, ge=1, le=30), radius_km: float = Query(10, gt=0, le=50)):
    return {"clinics": _run(logic.nearby_clinics, lat, lng, limit, radius_km),
            "note": "'24시(추정)'은 병원 이름에 '24'가 들어간 경우의 추정입니다. 공공데이터에는 진료 시간·특수동물 진료 정보가 없으니 방문 전 꼭 전화로 확인하세요.",
            "disclaimer": logic.DISCLAIMER}


@api.get("/places/categories")
def get_place_categories():
    return _run(logic.place_categories)


@api.get("/places")
def get_places(lat: float = Query(..., ge=33, le=39), lng: float = Query(..., ge=124, le=132),
               categories: str = Query("", description="쉼표 구분. 비우면 전체. 예: hospital,boarding"),
               limit: int = Query(30, ge=1, le=100), radius_km: float = Query(3, gt=0, le=20)):
    cats = [c.strip() for c in categories.split(",") if c.strip()] or None
    return {"places": _run(logic.nearby_places, lat, lng, cats, limit, radius_km),
            "note": "공공데이터(인허가 정보) 기준입니다. 영업시간·진료 과목·반려동물 동반 조건은 방문 전 확인하세요."}


app.include_router(api)
# 화면(정적 파일). API 라우트보다 뒤에 붙여야 /api가 가려지지 않는다.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent / "static", html=True), name="static")
