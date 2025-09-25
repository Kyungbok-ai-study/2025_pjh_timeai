# test_db.py
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()
url = os.getenv("DATABASE_URL")
print("DATABASE_URL =", url)
engine = create_engine(url, pool_pre_ping=True)

with engine.connect() as conn:
    print("connected:", conn.execute(text("select version()")).scalar())
