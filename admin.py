"""Settings-tab operations: destructive deletes and Excel bulk import."""

import hashlib
import pandas as pd
from sqlalchemy import text

from importer import content_key   # reuse the exact same key logic


def counts(conn):
    return {
        "fills": conn.execute(text("select count(*) from fills")).scalar(),
        "contracts": conn.execute(text("select count(*) from contracts")).scalar(),
        "aliases": conn.execute(text("select count(*) from contract_aliases")).scalar(),
        "products": conn.execute(text("select count(*) from products")).scalar(),
    }


def delete_fills_only(conn):
    n = conn.execute(text("select count(*) from fills")).scalar()
    conn.execute(text("truncate fills restart identity"))
    return n


def delete_everything(conn):
    n = conn.execute(text("select count(*) from fills")).scalar()
    conn.execute(text(
        "truncate fills, contract_aliases, contracts, products restart identity cascade"
    ))
    return n

def load_excel_fills(file):
    """Read the Fill Book sheet from an uploaded xlsx into the paste-box shape."""
    fills = pd.read_excel(file, sheet_name="Fill Book", header=1)
    fills = fills.dropna(subset=["Contract", "Buy/Sell", "Lots", "Price"])

    def build_ts(row):
        d = row["Date"]
        if pd.isna(d):
            return None
        t = row["Time"]
        if pd.isna(t):
            return pd.Timestamp(d).to_pydatetime()
        if isinstance(t, str):
            try:
                t = pd.to_datetime(t).time()
            except Exception:
                return pd.Timestamp(d).to_pydatetime()
        elif hasattr(t, "time"):
            t = t.time()
        try:
            return pd.Timestamp.combine(pd.Timestamp(d).date(), t).to_pydatetime()
        except Exception:
            return pd.Timestamp(d).to_pydatetime()

    clean = lambda s: " ".join(str(s).split()).strip()
    out = pd.DataFrame({
        "ts": [build_ts(r) for _, r in fills.iterrows()],
        "exchange": fills["Exchange"].map(clean),
        "raw_contract_string": fills["Contract"].map(clean),
        "side": fills["Buy/Sell"].map(lambda s: clean(s).upper()),
        "lots": pd.to_numeric(fills["Lots"], errors="coerce"),
        "price": pd.to_numeric(fills["Price"], errors="coerce"),
    })
    return out.dropna(subset=["ts", "lots", "price"])