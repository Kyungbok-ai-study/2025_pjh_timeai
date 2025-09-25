# backend/scheduler.py
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from ortools.sat.python import cp_model

# --------- 데이터 모델 ---------
@dataclass
class Course:
    id: str
    name: str
    size: int = 30
    sessions_per_week: int = 2
    duration_blocks: int = 1
    instructor_id: str = "inst-unknown"

@dataclass
class Room:
    id: str
    name: str
    capacity: int = 40
    tags: List[str] = None

@dataclass
class Instructor:
    id: str
    name: str
    unavailable: List[Tuple[str, int]] = None  # (DAY, BLOCK)

@dataclass
class Grid:
    days: List[str]
    blocks_per_day: int
    block_minutes: int = 50

    def slots(self):
        return [(d, b) for d in self.days for b in range(1, self.blocks_per_day + 1)]

    def is_evening(self, block: int) -> bool:
        return block >= max(1, self.blocks_per_day - 2)  # 마지막 2~3교시를 evening으로

@dataclass
class Hard:
    no_friday_evening: bool = False

@dataclass
class Soft:
    prefer_morning: bool = False
    prefer_compact_days: bool = False
    weight: int = 1

@dataclass
class Request:
    grid: Grid
    hard: Hard
    soft: Soft

# --------- 솔버 ---------
def solve(courses: List[Course], rooms: List[Room], instructors: List[Instructor], req: Request):
    model = cp_model.CpModel()
    grid = req.grid
    slots = grid.slots()
    rooms_by_id = {r.id: r for r in rooms}
    inst_by_id = {i.id: i for i in instructors}

    # 의사결정변수: X[c, s_idx, day, block, room] ∈ {0,1}
    X = {}
    for c in courses:
        for s in range(c.sessions_per_week):
            for (d, b) in slots:
                if b + c.duration_blocks - 1 > grid.blocks_per_day:
                    continue
                for r in rooms:
                    if r.capacity < c.size:
                        continue
                    X[(c.id, s, d, b, r.id)] = model.NewBoolVar(f"x_{c.id}_{s}_{d}_{b}_{r.id}")

    # 1) 각 세션은 정확히 1개 위치에 배정
    for c in courses:
        for s in range(c.sessions_per_week):
            model.Add(
                sum(X.get((c.id, s, d, b, r.id), 0) for (d, b) in slots for r in rooms) == 1
            )

    # 2) 같은 방·같은 시간 시작 중복 금지
    for r in rooms:
        for d, b in slots:
            starts = []
            for c in courses:
                for s in range(c.sessions_per_week):
                    v = X.get((c.id, s, d, b, r.id))
                    if v is not None:
                        starts.append(v)
            if starts:
                model.Add(sum(starts) <= 1)

    # 3) 강사 중복 금지
    for inst in instructors:
        for d, b in slots:
            vars_same_time = []
            for c in courses:
                if c.instructor_id != inst.id:
                    continue
                for s in range(c.sessions_per_week):
                    vlist = [X.get((c.id, s, d, b, r.id)) for r in rooms]
                    vars_same_time.extend([v for v in vlist if v is not None])
            if vars_same_time:
                model.Add(sum(vars_same_time) <= 1)

    # 4) 강사 불가 시간
    for c in courses:
        bad = inst_by_id.get(c.instructor_id).unavailable if inst_by_id.get(c.instructor_id) else None
        if not bad:
            continue
        for (ud, ub) in bad:
            for s in range(c.sessions_per_week):
                for r in rooms:
                    v = X.get((c.id, s, ud, ub, r.id))
                    if v is not None:
                        model.Add(v == 0)

    # 5) 하드 제약: 금요일 저녁 금지
    if req.hard.no_friday_evening:
        for c in courses:
            for s in range(c.sessions_per_week):
                for r in rooms:
                    for b in range(1, grid.blocks_per_day + 1):
                        if grid.is_evening(b):
                            v = X.get((c.id, s, "FRI", b, r.id))
                            if v is not None:
                                model.Add(v == 0)

    # 6) 소프트 제약 → 목적함수 (벌점 최소)
    penalties = []
    if req.soft.prefer_morning:
        for key, var in X.items():
            _, _, _, b, _ = key
            if b <= 3:
                # 아침이면 보너스(음수 벌점)
                penalties.append(var * (-req.soft.weight))
    if req.soft.prefer_compact_days:
        for c in courses:
            # 요일 사용수를 최소화
            used = {}
            for d in grid.days:
                used[d] = model.NewBoolVar(f"use_{c.id}_{d}")
                day_vars = []
                for s in range(c.sessions_per_week):
                    for b in range(1, grid.blocks_per_day + 1):
                        for r in rooms:
                            v = X.get((c.id, s, d, b, r.id))
                            if v is not None:
                                day_vars.append(v)
                if day_vars:
                    model.Add(sum(day_vars) >= used[d])
                    model.Add(sum(day_vars) <= 1000 * used[d])
            penalties.append(sum(used.values()) * req.soft.weight)

    if penalties:
        model.Minimize(sum(penalties))

    # 풀이
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)

    result = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (c_id, s, d, b, r_id), var in X.items():
            if solver.Value(var) == 1:
                result.append({
                    "course_id": c_id,
                    "session_index": s,
                    "day": d,
                    "block": b,
                    "room_id": r_id
                })
    return {"status": int(status), "assignments": result}
