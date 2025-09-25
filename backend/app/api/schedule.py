# backend/app/api/schedule.py
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
import pandas as pd
from pathlib import Path
from app.core.scheduler import greedy_schedule  # 네가 만든 그리디 로직

router = APIRouter()

CSV = Path(__file__).resolve().parents[1] / "db" / "courses_data.csv"

def load_courses():
    if not CSV.exists():
        return [{"code":"AI101","name":"인공지능 기초","professor":"홍길동","day":"MON","time":"09:00~10:50","room":"A101"}]
    df = pd.read_csv(CSV, encoding="utf-8")
    ren = {"코드":"code","과목코드":"code","과목명":"name","담당교수":"professor","교수":"professor","요일":"day","시간":"time","강의실":"room"}
    for k,v in ren.items():
        if k in df.columns and v not in df.columns: df[v]=df[k]
    need=["code","name","professor","day","time","room"]
    for c in need:
        if c not in df.columns: df[c]=""
    df["day"]=df["day"].astype(str).str.upper().str[:3]
    return df[need].fillna("").to_dict(orient="records")

class ScheduleIn(BaseModel):
    days: List[str] = ["MON","TUE","WED","THU","FRI"]
    periodsPerDay: int = 9
    blockMinutes: int = 50
    preferMorning: bool = True
    compactSameDay: bool = False
    priorityWeight: int = 1
    natural: str = ""

@router.post("/schedule")
def schedule(req: ScheduleIn):
    items = load_courses()
    sched = greedy_schedule(items, req.days, req.periodsPerDay, req.preferMorning)
    return {"message":"배정 완료(그리디)","options":req.model_dump(),"schedule":sched}
