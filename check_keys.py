import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from importer import content_key

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])

with engine.connect() as conn:
    df = pd.read_sql(text("""
        select ts, raw_contract_string, side, lots, price, content_key
        from fills where ts >= '2026-07-20'
    """), conn)

df["py_key"] = [
    content_key(r.ts, r.raw_contract_string, r.side, r.lots, r.price)
    for r in df.itertuples()
]
bad = df[df.py_key != df.content_key]
print(f"{len(df)} rows checked, {len(bad)} mismatches")
if len(bad):
    print(bad[["content_key", "py_key"]].head(10).to_string())