from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from ortools.sat.python import cp_model
import random

# ---------- 데이터 모델 ----------
@dataclass
class Course:
    id: str
    name: str
    size: int = 30
    sessions_per_week: int = 1
    duration_blocks: int = 1
    instructor_id: str = "inst-unknown"

@dataclass
class Room:
    id: str
    name: str
    capacity: int = 40
    tags: Optional[List[str]] = None

@dataclass
class Instructor:
    id: str
    name: str
    unavailable: Optional[List[Tuple[str, int]]] = None  # (DAY, BLOCK)

@dataclass
class Grid:
    days: List[str]
    blocks_per_day: int
    block_minutes: int = 50

    def slots(self):
        return [(d, b) for d in self.days for b in range(1, self.blocks_per_day + 1)]

    def is_evening(self, block: int) -> bool:
        # 마지막 2교시를 저녁으로 간주
        return block >= max(1, self.blocks_per_day - 2)

@dataclass
class Hard:
    no_friday_evening: bool = False

@dataclass
class Soft:
    # “같은 요일 압축 선호”는 완전 제거. 오전 선호만.
    prefer_morning: bool = False
    weight: int = 1

@dataclass
class Request:
    grid: Grid
    hard: Hard
    soft: Soft
    randomize: bool = True  # 매 실행 랜덤 탐색

# ---------- 솔버 ----------
def solve(courses: List[Course], rooms: List[Room], instructors: List[Instructor], req: Request):
    model = cp_model.CpModel()
    grid = req.grid

    # 슬롯/방 순서를 섞어서 매 실행 해가 달라지도록
    days = list(grid.days)
    blocks = list(range(1, grid.blocks_per_day + 1))
    slots = [(d, b) for d in days for b in blocks]
    rooms_order = rooms[:]
    if req.randomize:
        random.shuffle(days)
        random.shuffle(blocks)
        slots = [(d, b) for d in days for b in blocks]
        random.shuffle(slots)
        random.shuffle(rooms_order)

    inst_by_id = {i.id: i for i in instructors}

    # 결정변수 X[c, s, day, block, room] ∈ {0,1}
    X: Dict[tuple, cp_model.IntVar] = {}
    for c in courses:
        for s in range(c.sessions_per_week):
            for (d, b) in slots:
                if b + c.duration_blocks - 1 > grid.blocks_per_day:
                    continue
                for r in rooms_order:
                    if r.capacity < c.size:
                        continue
                    X[(c.id, s, d, b, r.id)] = model.NewBoolVar(f"x_{c.id}_{s}_{d}_{b}_{r.id}")

    # 1) 각 세션은 정확히 1자리
    for c in courses:
        for s in range(c.sessions_per_week):
            model.Add(sum(X.get((c.id, s, d, b, r.id), 0) for (d, b) in slots for r in rooms_order) == 1)

    # 2) 같은 방·같은 시간 시작 ≤ 1
    for r in rooms_order:
        for d, b in slots:
            starts = [X[(c.id, s, d, b, r.id)]
                      for c in courses
                      for s in range(c.sessions_per_week)
                      if (c.id, s, d, b, r.id) in X]
            if starts:
                model.Add(sum(starts) <= 1)

    # 3) 강사 중복 금지
    for inst in instructors:
        for d, b in slots:
            vars_same = []
            for c in courses:
                if c.instructor_id != inst.id:
                    continue
                for s in range(c.sessions_per_week):
                    for r in rooms_order:
                        v = X.get((c.id, s, d, b, r.id))
                        if v is not None:
                            vars_same.append(v)
            if vars_same:
                model.Add(sum(vars_same) <= 1)

    # 4) 강사 불가 시간
    for c in courses:
        unav = inst_by_id.get(c.instructor_id).unavailable if inst_by_id.get(c.instructor_id) else None
        if not unav:
            continue
        for (ud, ub) in unav:
            for s in range(c.sessions_per_week):
                for r in rooms_order:
                    v = X.get((c.id, s, ud, ub, r.id))
                    if v is not None:
                        model.Add(v == 0)

    # 5) 금요일 저녁 금지 (옵션)
    if req.hard.no_friday_evening:
        for c in courses:
            for s in range(c.sessions_per_week):
                for r in rooms_order:
                    for b in range(1, grid.blocks_per_day + 1):
                        if grid.is_evening(b):
                            v = X.get((c.id, s, "FRI", b, r.id))
                            if v is not None:
                                model.Add(v == 0)

    # 6) 소프트: 오전 선호만 (compact 없음)
    penalties = []
    if req.soft.prefer_morning:
        for key, var in X.items():
            _, _, _, b, _ = key
            if b <= 3:
                penalties.append(var * (-req.soft.weight))  # 보너스(음수 벌점)
    if penalties:
        model.Minimize(sum(penalties))

    # 풀이
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    if req.randomize:
        solver.parameters.random_seed = random.randint(1, 1_000_000)

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
