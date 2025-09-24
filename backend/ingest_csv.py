import os
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
CSV_PATH = os.getenv("CSV_PATH", "courses_data.csv")
engine = create_engine(DATABASE_URL)

def read_csv_smart(path):
    try:
        return pd.read_csv(path, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp949")

def main():
    df = read_csv_smart(CSV_PATH)
    df.columns = [c.strip() for c in df.columns]
    df.to_sql("courses", engine, if_exists="replace", index=False)
    print(f"Loaded {len(df)} rows into table 'courses'.")

if __name__ == "__main__":
    main()
