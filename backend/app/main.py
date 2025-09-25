# backend/app/main.py
import os
from pathlib import Path
import pandas as pd
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from pydantic import BaseModel

# 내부 모듈 (패키지 경로 주의: app.)
from app.core.gemini_client import summarize_text_ko, rank_courses_ko
from app.core.scheduler import (
    solve, Course, Room, Instructor, Grid, Hard, Soft, Request
)

# ───────────────────────── Env & DB ─────────────────────────
load_dotenv()
DEFAULT_SQLITE = "sqlite:///./courses.db"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE)

# sqlite 상대경로 보정
if DATABASE_URL.startswith("sqlite:///./"):
    db_file = Path(__file__).resolve().parents[2] / DATABASE_URL.replace("sqlite:///./", "")
    DATABASE_URL = f"sqlite:///{db_file.as_posix()}"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# ───────────────────────── FastAPI ─────────────────────────
app = FastAPI(title="Courses API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONT_DIR = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/app", StaticFiles(directory=str(FRONT_DIR), html=True), name="static")

# ───────────────────────── Schemas ─────────────────────────
class SummaryIn(BaseModel):
    text: str

class RecommendIn(BaseModel):
    preferences: str
    limit: int = 5

class ScheduleIn(BaseModel):
    days: list[str] = ["MON", "TUE", "WED", "THU", "FRI"]
    periodsPerDay: int = 9
    blockMinutes: int = 50
    preferMorning: bool = True
    compactSameDay: bool = False
    priorityWeight: int = 1
    natural: str = ""
    noFridayEvening: bool = False   # ✅ 하드 제약(체크박스 연결용)

# ───────────────────────── Endpoints ─────────────────────────
@app.get("/health")
def health():
    return {"ok": True, "db": DATABASE_URL}

@app.get("/courses")
def courses(limit: int = 20, offset: int = 0):
    sql = text("SELECT * FROM courses LIMIT :l OFFSET :o")
    with engine.connect() as c:
        df = pd.read_sql(sql, c, params={"o": offset, "l": limit})
    return df.to_dict(orient="records")

@app.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = 100, offset: int = 0):
    sql = text("""
        SELECT * FROM courses
        WHERE CAST("교과목명" AS TEXT) ILIKE :kw
        LIMIT :l OFFSET :o
    """)
    with engine.connect() as c:
        df = pd.read_sql(sql, c, params={"kw": f"%{q}%", "o": offset, "l": limit})
        total = c.execute(
            text('SELECT COUNT(*) FROM courses WHERE CAST("교과목명" AS TEXT) ILIKE :kw'),
            {"kw": f"%{q}%"}
        ).scalar_one()
    return {"total": total, "results": df.to_dict(orient="records")}

@app.post("/gemini/summary")
def gemini_summary(body: SummaryIn):
    return {"summary": summarize_text_ko(body.text)}

@app.post("/gemini/recommend")
def gemini_recommend(body: RecommendIn):
    topk = max(1, min(body.limit, 10))
    with engine.connect() as c:
        df = pd.read_sql(text("SELECT * FROM courses"), c)
    courses = df.to_dict(orient="records")
    res = rank_courses_ko(body.preferences, courses, topk=topk)
    return {"result": res}

@app.post("/schedule")
def schedule(body: ScheduleIn):
    # 1) 과목 로드
    with engine.connect() as c:
        df = pd.read_sql(text("SELECT * FROM courses"), c)

    # 2) DB → 모델 변환
    courses_m: list[Course] = []
    inst_map: dict[str, Instructor] = {}

    for i, row in df.iterrows():
        cid  = str(row.get("교과목코드") or row.get("코드") or f"C{i+1}")
        name = str(row.get("교과목명") or row.get("과목") or cid)
        size = int(row.get("수강인원") or 30)
        sess = int(row.get("수업주수") or row.get("수업주수(회)") or 2)
        prof = str(row.get("강좌대표교수") or row.get("교수") or "교수미정")

        courses_m.append(Course(
            id=cid, name=name, size=size,
            sessions_per_week=max(1, sess),
            duration_blocks=1,
            instructor_id=prof
        ))
        if prof not in inst_map:
            inst_map[prof] = Instructor(id=prof, name=prof, unavailable=[])

    instructors = list(inst_map.values())

    # 3) 강의실 구성 (없으면 기본)
    room_ids = []
    if "강의실" in df.columns:
        room_ids = sorted(set(str(x).strip() for x in df["강의실"].dropna().tolist() if str(x).strip()))
    if not room_ids:
        room_ids = ["R101", "R102"]
    rooms = [Room(id=r, name=r, capacity=40, tags=[]) for r in room_ids]

    # 4) 그리드/제약
    grid = Grid(days=[d.upper()[:3] for d in body.days],
                blocks_per_day=body.periodsPerDay,
                block_minutes=body.blockMinutes)
    hard = Hard(no_friday_evening=bool(body.noFridayEvening))
    soft = Soft(prefer_morning=bool(body.preferMorning),
                prefer_compact_days=bool(body.compactSameDay),
                weight=int(body.priorityWeight))
    req = Request(grid=grid, hard=hard, soft=soft)

    # 5) OR-Tools 풀이
    assigns = []
    try:
        sol = solve(courses_m, rooms, instructors, req)
        assigns = sol.get("assignments", [])
    except Exception as e:
        print("[/schedule] OR-Tools error:", e)

    # 6) 결과 없으면 라운드로빈 폴백
    if not assigns:
        def start_min(t: str):
            try:
                hh, mm = str(t).split("~")[0].split(":")
                return int(hh) * 60 + int(mm)
            except Exception:
                return 8 * 60 if body.preferMorning else 18 * 60

        items = df.to_dict(orient="records")
        items.sort(key=lambda x: start_min(x.get("시간", "")))
        ptr = {d: 0 for d in grid.days}
        for idx, r in enumerate(items):
            d = str(r.get("요일", "")).upper()[:3]
            if d not in ptr:
                d = grid.days[idx % len(grid.days)]
            if ptr[d] >= grid.blocks_per_day:
                continue
            ptr[d] += 1
            assigns.append({
                "course_id": str(r.get("교과목코드") or r.get("코드") or f"C{idx+1}"),
                "session_index": 0,
                "day": d,
                "block": ptr[d],
                "room_id": rooms[ptr[d] % len(rooms)].id
            })

    # 7) 프론트가 바로 그릴 수 있는 schedule 생성
    by_cid = {str(r.get("교과목코드") or r.get("코드") or f"C{i+1}"): dict(r)
              for i, r in df.iterrows()}
    schedule_rows = []
    for a in assigns:
        base = by_cid.get(str(a["course_id"]), {})
        schedule_rows.append({
            **base,
            "요일": a["day"],
            "slot": f"P{a['block']}",
            "강의실": a["room_id"],
        })

    return {
        "message": "배정 완료",
        "summary": {
            "courses": len(courses_m),
            "rooms": len(rooms),
            "instructors": len(instructors),
            "days": grid.days,
            "blocks_per_day": grid.blocks_per_day,
        },
        "solution": {"assignments": assigns},  # 필요 시 사용
        "schedule": schedule_rows,             # ✅ 프론트 테이블에서 사용
    }

# ───────────────────────── Entry ─────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
