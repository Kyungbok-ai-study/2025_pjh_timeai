import os, json, re
import google.generativeai as genai
from dotenv import load_dotenv
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
MODEL=os.getenv("GEMINI_MODEL","gemini-1.5-flash")

def _model(): return genai.GenerativeModel(MODEL)
def _gen(prompt): return (_model().generate_content(prompt).text or "").strip()

def summarize_text_ko(text:str)->str:
    return _gen(f"아래 텍스트를 한국어로 핵심 5줄 이내로 요약:\n{text}")

def rank_courses_ko(prefs:str, courses:list, topk:int=5):
    import json as _j
    p = f"""선호: {prefs}
아래 JSON 과목 리스트에서 상위 {topk}개를 고르고 이유를 써.
반드시 JSON 배열로만 출력: [{{"교과목코드":str,"교과목명":str,"개설학과":str,"강좌담당교수":str,"이유":str}}]
데이터:
{_j.dumps(courses, ensure_ascii=False)}"""
    txt=_gen(p)
    m=re.search(r'(\[.*\])', txt, re.S)
    if not m: return {"raw": txt}
    try: return _j.loads(m.group(1))
    except: return {"raw": txt}
