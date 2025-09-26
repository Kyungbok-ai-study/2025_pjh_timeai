# backend/app/main.py
import os
import re
import random
from pathlib import Path
from typing import Optional, List, Dict, Any

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from pydantic import BaseModel

# ── 내부 모듈 (상대 경로) ─────────────────────────────────────────────
try:
    from .core.gemini_client import summarize_text_ko, rank_courses_ko  # 선택 기능
except Exception:
    # 제미나이가 없어도 서버는 동작하도록 더미 함수
    def summarize_text_ko(text: str) -> str:
        return text[:200] + ("..." if len(text) > 200 else "")
    def rank_courses_ko(prefs: str, courses: list, topk: int = 5):
        return courses[:topk]

from .core.scheduler import (
    solve, Course, Room, Instructor, Grid, Hard, Soft, Request
)

# ───────────────────────── Env & DB ─────────────────────────
# .env를 프로젝트 루트에서 강제 로드
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_PATH)

DEFAULT_SQLITE = "sqlite:///./courses.db"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE)

# sqlite 상대경로 보정(루트/courses.db)
if DATABASE_URL.startswith("sqlite:///./"):
    db_file = Path(__file__).resolve().parents[2] / DATABASE_URL.replace("sqlite:///./", "")
    DATABASE_URL = f"sqlite:///{db_file.as_posix()}"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
DB_DIALECT = engine.dialect.name  # 'postgresql' / 'sqlite' 등

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
    days: List[str] = ["MON", "TUE", "WED", "THU", "FRI"]
    periodsPerDay: int = 9
    blockMinutes: int = 50
    preferMorning: bool = True
    priorityWeight: int = 1
    natural: str = ""
    noFridayEvening: bool = False  # 하드 제약(체크박스 연결용)

# ───────────────────────── 공통 유틸 ─────────────────────────
def _to_int(x, default=0):
    """문자/콤마/NaN 섞여 있어도 안전하게 int로."""
    if x is None:
        return default
    if isinstance(x, int):
        return x
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return default
    s = re.sub(r"[^0-9\-]", "", s)
    try:
        return int(s) if s not in ("", "-") else default
    except Exception:
        return default

def _pick_name_col(cols):
    """과목명 컬럼 자동 탐지."""
    for k in ["교과목명", "과목명", "name", "NAME"]:
        if k in cols:
            return k
    return cols[0] if cols else "교과목명"

# ───────────────────────── Endpoints ─────────────────────────
@app.get("/health")
def health():
    return {"ok": True, "db": DATABASE_URL, "dialect": DB_DIALECT}

@app.get("/courses")
def courses(limit: int = 20, offset: int = 0):
    with engine.connect() as c:
        # LIMIT/OFFSET은 정수 인라인(일부 드라이버 파라미터 바인딩 이슈 회피)
        df = pd.read_sql(text(f"SELECT * FROM courses LIMIT {int(limit)} OFFSET {int(offset)}"), c)
    return df.to_dict(orient="records")

@app.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = 100, offset: int = 0):
    try:
        q = (q or "").strip()
        if not q:
            return {"total": 0, "results": []}

        with engine.connect() as c:
            cols = pd.read_sql(text("SELECT * FROM courses LIMIT 1"), c).columns.tolist()
            name_col = _pick_name_col(cols)

            if DB_DIALECT == "postgresql":
                sql = text(f'''
                    SELECT * FROM courses
                    WHERE CAST("{name_col}" AS TEXT) ILIKE :kw
                    ORDER BY 1
                    LIMIT {int(limit)} OFFSET {int(offset)}
                ''')
                cnt_sql = text(f'''
                    SELECT COUNT(*) FROM courses
                    WHERE CAST("{name_col}" AS TEXT) ILIKE :kw
                ''')
                params = {"kw": f"%{q}%"}
            else:
                # SQLite 등
                sql = text(f'''
                    SELECT * FROM courses
                    WHERE LOWER(CAST("{name_col}" AS TEXT)) LIKE :kw
                    ORDER BY 1
                    LIMIT {int(limit)} OFFSET {int(offset)}
                ''')
                cnt_sql = text(f'''
                    SELECT COUNT(*) FROM courses
                    WHERE LOWER(CAST("{name_col}" AS TEXT)) LIKE :kw
                ''')
                params = {"kw": f"%{q.lower()}%"}

            df = pd.read_sql(sql, c, params=params)
            total = c.execute(cnt_sql, params).scalar() or 0

        return {"total": int(total), "results": df.to_dict(orient="records")}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"/search 실패: {e.__class__.__name__}: {e}"})

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
    try:
        # 1) 과목 로드
        with engine.connect() as c:
            df = pd.read_sql(text("SELECT * FROM courses"), c)

        # 2) DB → 모델 변환
        courses_m: List[Course] = []
        inst_map: Dict[str, Instructor] = {}

        for i, row in df.iterrows():
            cid  = str(row.get("교과목코드") or row.get("코드") or f"C{i+1}")
            name = str(row.get("교과목명") or row.get("과목") or cid)
            size = _to_int(row.get("수강인원"), 30)
            sess = _to_int(row.get("수업주수") or row.get("수업주수(회)"), 1)
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
        rooms = [Room(id=r, name=r, capacity=120 if i == 0 else 80, tags=[]) for i, r in enumerate(room_ids)]

        # 4) 그리드/제약 (오전 선호만 사용)
        grid = Grid(days=[d.upper()[:3] for d in body.days],
                    blocks_per_day=body.periodsPerDay,
                    block_minutes=body.blockMinutes)
        hard = Hard(no_friday_evening=bool(body.noFridayEvening))
        soft = Soft(prefer_morning=bool(body.preferMorning), weight=int(body.priorityWeight))
        req = Request(grid=grid, hard=hard, soft=soft, randomize=True)

        # 5) OR-Tools 풀이
        sol = solve(courses_m, rooms, instructors, req)
        assigns = sol.get("assignments", [])

        # ── 폴백: 해가 없으면 랜덤 그리디로 항상 배정 ──────────────────
        if not assigns:
            # 모든 (day, block, room) 슬롯 생성 후 셔플
            all_slots = []
            for d in grid.days:
                for b in range(1, grid.blocks_per_day + 1):
                    for r in rooms:
                        all_slots.append((d, b, r.id))
            random.shuffle(all_slots)

            used_room = set()            # {(day, block, room_id)}
            used_inst = set()            # {(instructor_id, day, block)}
            assigns = []

            # 코스 순서도 매번 랜덤 → “항상 랜덤” 요구 반영
            random_courses = courses_m[:]
            random.shuffle(random_courses)

            for c in random_courses:
                for s_idx in range(max(1, c.sessions_per_week)):
                    placed = False
                    random.shuffle(all_slots)
                    for (d, b, r_id) in all_slots:
                        # 방 / 강사 충돌 방지
                        if (d, b, r_id) in used_room:
                            continue
                        if (c.instructor_id, d, b) in used_inst:
                            continue
                        # 배정
                        assigns.append({
                            "course_id": c.id,
                            "session_index": s_idx,
                            "day": d,
                            "block": b,
                            "room_id": r_id
                        })
                        used_room.add((d, b, r_id))
                        used_inst.add((c.instructor_id, d, b))
                        placed = True
                        break
                    if not placed:
                        continue  # 남은 슬롯 부족하면 해당 세션은 건너뜀

        # 6) 프론트용 schedule 생성
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
                "block_minutes": grid.block_minutes
            },
            "solution": {"assignments": assigns},
            "schedule": schedule_rows,
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"/schedule 실패: {e.__class__.__name__}: {e}"}
        )

# ───────────────────────── Entry (로컬 실행용) ─────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
