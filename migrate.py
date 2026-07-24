"""
Phase 1 migration: Excel -> Postgres.

Loads products, contracts, contract_aliases, and fills.
Safe to re-run: truncates and reloads everything from scratch.
"""

import glob
import hashlib
import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])

matches = glob.glob("*.xlsx")
if not matches:
    raise SystemExit("No .xlsx found in this folder.")
XL = matches[0]
print(f"Reading: {XL}\n")


def clean(s):
    """Normalise a string for use as a lookup key."""
    return " ".join(str(s).split()).strip()


# ---------------------------------------------------------------- load sheets

mapping = pd.read_excel(XL, sheet_name="Mapping", header=1)
mapping = mapping.dropna(subset=["Contract "])
mapping["canonical"] = mapping["Contract "].map(clean)

# Three Mapping rows have a contract name but blank Product/tick/RT cells.
# Recover Product from Sub-Category, then fill tick values from the product's
# other rows. These are all butterflies (RT 2.0) with no fills against them.
mapping["Product"] = mapping["Product"].fillna(mapping["Sub-Category"])

prod_defaults = (
    mapping.dropna(subset=["Tick Size"])
    .groupby("Product")[["Tick Size", "Tick Value"]]
    .first()
)
for col in ["Tick Size", "Tick Value"]:
    mapping[col] = mapping[col].fillna(mapping["Product"].map(prod_defaults[col]))

mapping["RT "] = mapping["RT "].fillna(2.0)

still_bad = mapping[mapping["Product"].isna() | mapping["Tick Size"].isna()]
if len(still_bad):
    print("WARNING: unrecoverable mapping rows:")
    print(still_bad[["Contract ", "Product", "Tick Size"]].to_string())
    mapping = mapping.drop(still_bad.index)

ase = pd.read_excel(XL, sheet_name="ASE Mapping")
ase = ase.dropna(subset=["ASE", "Quoted"])
ase["alias"] = ase["ASE"].map(clean)
ase["quoted"] = ase["Quoted"].map(clean)

fills = pd.read_excel(XL, sheet_name="Fill Book", header=1)
fills = fills.dropna(subset=["Contract", "Buy/Sell", "Lots", "Price"])

print(f"mapping rows : {len(mapping)}")
print(f"alias rows   : {len(ase)}")
print(f"fill rows    : {len(fills)}\n")


# ------------------------------------------------------------------- products

products = (
    mapping.groupby("Product")
    .agg(
        tick_size=("Tick Size", "max"),
        tick_value=("Tick Value", "max"),
        exchange=("Exchange", "first"),
    )
    .reset_index()
    .rename(columns={"Product": "symbol"})
)


# ------------------------------------------------------------------ timestamps

def build_ts(row):
    """Combine the Date and Time columns into one timestamp."""
    d = row["Date"]
    if pd.isna(d):
        return None
    t = row["Time"]
    if pd.isna(t):
        return pd.Timestamp(d)
    if isinstance(t, str):
        try:
            t = pd.to_datetime(t).time()
        except Exception:
            return pd.Timestamp(d)
    elif hasattr(t, "time"):
        t = t.time()
    try:
        return pd.Timestamp.combine(pd.Timestamp(d).date(), t)
    except Exception:
        return pd.Timestamp(d)


fills["ts"] = fills.apply(build_ts, axis=1)
fills["raw"] = fills["Contract"].map(clean)


# ------------------------------------------------------------------------ load

with engine.begin() as conn:
    conn.execute(text("truncate fills, contract_aliases, contracts, products restart identity cascade"))

    # products
    prod_ids = {}
    for _, r in products.iterrows():
        pid = conn.execute(
            text("""insert into products (symbol, exchange, tick_size, tick_value)
                    values (:s, :e, :ts, :tv) returning id"""),
            {"s": r["symbol"], "e": r["exchange"],
             "ts": float(r["tick_size"]), "tv": float(r["tick_value"])},
        ).scalar()
        prod_ids[r["symbol"]] = pid
    print(f"products inserted      : {len(prod_ids)}")

    # contracts
    con_ids = {}
    for _, r in mapping.iterrows():
        cid = conn.execute(
            text("""insert into contracts
                    (product_id, canonical_name, tt_code, category, sub_category,
                     rt_count, tick_size, tick_value, exchange)
                    values (:p, :c, :tt, :cat, :sub, :rt, :ts, :tv, :ex)
                    returning id"""),
            {
                "p": prod_ids[r["Product"]],
                "c": r["canonical"],
                "tt": None if pd.isna(r["TT Code"]) else clean(r["TT Code"]),
                "cat": None if pd.isna(r["Category"]) else clean(r["Category"]),
                "sub": None if pd.isna(r["Sub-Category"]) else clean(r["Sub-Category"]),
                "rt": float(r["RT "]) if not pd.isna(r["RT "]) else 1.0,
                "ts": float(r["Tick Size"]),
                "tv": float(r["Tick Value"]),
                "ex": None if pd.isna(r["Exchange"]) else clean(r["Exchange"]),
            },
        ).scalar()
        con_ids[r["canonical"]] = cid
    print(f"contracts inserted     : {len(con_ids)}")

    # aliases
    n_alias, n_broken = 0, 0
    for _, r in ase.iterrows():
        cid = con_ids.get(r["quoted"])
        if cid is None:
            n_broken += 1
            continue
        conn.execute(
            text("""insert into contract_aliases (contract_id, source, alias_string)
                    values (:c, 'ASE', :a) on conflict do nothing"""),
            {"c": cid, "a": r["alias"]},
        )
        n_alias += 1
    print(f"aliases inserted       : {n_alias}  (skipped {n_broken} pointing to unknown contracts)")

    # fills
    alias_map = dict(zip(ase["alias"], ase["quoted"]))
    n_ins, n_unmapped, n_dup = 0, 0, 0

    for pos, (_, r) in enumerate(fills.iterrows()):
        raw = r["raw"]
        quoted = alias_map.get(raw, raw)
        cid = con_ids.get(quoted)
        if cid is None:
            n_unmapped += 1

        ts = r["ts"]
        # Row position is included so that identical untimed fills stay distinct.
        h = hashlib.sha256(
            f"XLIMPORT|{pos}|{ts}|{raw}|{r['Buy/Sell']}|{r['Lots']}|{r['Price']}".encode()
        ).hexdigest()

        res = conn.execute(
            text("""insert into fills
                    (ts, exchange, raw_contract_string, contract_id, side, lots,
                     price, source, import_batch_id, dedup_hash)
                    values (:ts, :ex, :raw, :cid, :side, :lots, :price,
                            'excel_import', 'initial', :h)
                    on conflict (dedup_hash) do nothing
                    returning id"""),
            {
                "ts": None if ts is None or pd.isna(ts) else ts.to_pydatetime(),
                "ex": None if pd.isna(r["Exchange"]) else clean(r["Exchange"]),
                "raw": raw,
                "cid": cid,
                "side": clean(r["Buy/Sell"]),
                "lots": float(r["Lots"]),
                "price": float(r["Price"]),
                "h": h,
            },
        ).scalar()
        if res is None:
            n_dup += 1
        else:
            n_ins += 1

    print(f"fills inserted         : {n_ins}")
    print(f"  of which unmapped    : {n_unmapped}")
    print(f"  duplicates skipped   : {n_dup}")

print("\nDone.")