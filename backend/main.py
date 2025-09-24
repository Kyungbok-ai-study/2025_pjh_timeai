# main.py (정상 동작 버전: /health, /courses, /search + /app 정적서빙)
import os
import pandas as pd
import json
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from pathlib import Path
from pydantic import BaseModel                         # 🔴 추가
from gemini_client import summarize_text_ko, rank_courses_ko   # 🔴 추가

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

app = FastAPI(title="Courses API")

FRONT_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/app", StaticFiles(directory=str(FRONT_DIR), html=True), name="static")
class SummaryIn(BaseModel):        # 🔴 추가
    text: str

class RecommendIn(BaseModel):      # 🔴 추가
    preferences: str
    limit: int = 5

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 엔드포인트들 ---
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/courses")
def courses(limit: int = 20, offset: int = 0):
    with engine.connect() as c:
        df = pd.read_sql(
            text("SELECT * FROM courses OFFSET :o LIMIT :l"),
            c, params={"o": offset, "l": limit}
        )
    return df.to_dict(orient="records")

@app.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = 100, offset: int = 0):
    sql = text("""
        SELECT * FROM courses
        WHERE CAST("교과목명" AS TEXT) ILIKE :kw
        OFFSET :o LIMIT :l
    """)
    with engine.connect() as c:
        df = pd.read_sql(sql, c, params={"kw": f"%{q}%", "o": offset, "l": limit})
        total = c.execute(
            text('SELECT COUNT(*) FROM courses WHERE CAST("교과목명" AS TEXT) ILIKE :kw'),
            {"kw": f"%{q}%"}
        ).scalar()
    return {"total": total, "results": df.to_dict(orient="records")}
@app.post("/gemini/summary")       # 🔴 추가
def gemini_summary(body: SummaryIn):
    return {"summary": summarize_text_ko(body.text)}

@app.post("/gemini/recommend")     # 🔴 추가
def gemini_recommend(body: RecommendIn):
    topk = max(1, min(body.limit, 10))
    with engine.connect() as c:
        df = pd.read_sql(text("SELECT * FROM courses"), c)
    courses = df.to_dict(orient="records")
    res = rank_courses_ko(body.preferences, courses, topk=topk)
    return {"result": res}

# --- 정적파일 서빙: 루트("/")가 아닌 "/app" 으로! ---
FRONT_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/app", StaticFiles(directory=str(FRONT_DIR), html=True), name="static")
