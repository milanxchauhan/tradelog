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

def load_excel_full(file, conn):
    """Load products, contracts, aliases from an uploaded workbook.
    Only inserts what's missing — safe to run alongside existing data."""
    clean = lambda s: " ".join(str(s).split()).strip()

    mapping = pd.read_excel(file, sheet_name="Mapping", header=1).dropna(subset=["Contract "])
    mapping["Product"] = mapping["Product"].fillna(mapping["Sub-Category"])
    defaults = (mapping.dropna(subset=["Tick Size"])
                .groupby("Product")[["Tick Size", "Tick Value"]].first())
    for col in ["Tick Size", "Tick Value"]:
        mapping[col] = mapping[col].fillna(mapping["Product"].map(defaults[col]))
    mapping["RT "] = mapping["RT "].fillna(2.0)
    mapping = mapping.dropna(subset=["Product", "Tick Size"])

    ase = pd.read_excel(file, sheet_name="ASE Mapping").dropna(subset=["ASE", "Quoted"])

    # products
    prod_ids = {}
    prods = mapping.groupby("Product").agg(
        ts=("Tick Size", "max"), tv=("Tick Value", "max"), ex=("Exchange", "first")).reset_index()
    for _, r in prods.iterrows():
        pid = conn.execute(text("""
            insert into products (symbol, exchange, tick_size, tick_value, commission_per_rt, rebate_per_rt)
            values (:s,:e,:ts,:tv,0,0)
            on conflict (symbol) do update set symbol = excluded.symbol
            returning id"""),
            {"s": r["Product"], "e": r["ex"], "ts": float(r["ts"]), "tv": float(r["tv"])}).scalar()
        prod_ids[r["Product"]] = pid

    # contracts
    con_ids = {}
    for _, r in mapping.iterrows():
        name = clean(r["Contract "])
        cid = conn.execute(text("""
            insert into contracts (product_id, canonical_name, tt_code, category, sub_category,
                                   rt_count, tick_size, tick_value, exchange)
            values (:p,:c,:tt,:cat,:sub,:rt,:ts,:tv,:ex)
            on conflict (canonical_name) do update set canonical_name = excluded.canonical_name
            returning id"""),
            {"p": prod_ids[r["Product"]], "c": name,
             "tt": None if pd.isna(r["TT Code"]) else clean(r["TT Code"]),
             "cat": None if pd.isna(r["Category"]) else clean(r["Category"]),
             "sub": None if pd.isna(r["Sub-Category"]) else clean(r["Sub-Category"]),
             "rt": float(r["RT "]), "ts": float(r["Tick Size"]), "tv": float(r["Tick Value"]),
             "ex": None if pd.isna(r["Exchange"]) else clean(r["Exchange"])}).scalar()
        con_ids[name] = cid

    # aliases
    for _, r in ase.iterrows():
        cid = con_ids.get(clean(r["Quoted"]))
        if cid:
            conn.execute(text("""insert into contract_aliases (contract_id, source, alias_string)
                                 values (:c,'ASE',:a) on conflict do nothing"""),
                         {"c": cid, "a": clean(r["ASE"])})

    return len(prod_ids), len(con_ids)