"""Parse pasted fills, resolve contracts, prepare rows for insert."""

import hashlib
import io
from datetime import datetime

import pandas as pd
from sqlalchemy import text

COLUMNS = ["date", "time", "exchange", "contract", "side", "lots", "price"]


def clean(s):
    return " ".join(str(s).split()).strip()


def parse_ts(date_str, time_str):
    """'24Jul26' + '16:53:46.192' -> datetime. Returns None if unparseable."""
    d, t = clean(date_str), clean(time_str)
    if not d:
        return None
    for fmt in ("%d%b%y", "%d-%b-%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            day = datetime.strptime(d, fmt).date()
            break
        except ValueError:
            continue
    else:
        return None

    if not t:
        return datetime.combine(day, datetime.min.time())
    for fmt in ("%H:%M:%S.%f", "%H:%M:%S", "%H:%M"):
        try:
            return datetime.combine(day, datetime.strptime(t, fmt).time())
        except ValueError:
            continue
    return datetime.combine(day, datetime.min.time())


def parse_paste(raw_text):
    """Tab- or comma-separated text -> dataframe. Raises ValueError on bad shape."""
    txt = raw_text.strip()
    if not txt:
        raise ValueError("Nothing pasted.")

    sep = "\t" if "\t" in txt.split("\n")[0] else ","
    df = pd.read_csv(
        io.StringIO(txt),
        sep=sep,
        header=None,
        names=COLUMNS,
        dtype=str,
        skipinitialspace=True,
    )

    if df.shape[1] != 7:
        raise ValueError(f"Expected 7 columns, found {df.shape[1]}.")

    # A header row would fail side validation; drop it if present.
    if clean(df.iloc[0]["side"]).upper() not in ("B", "S"):
        df = df.iloc[1:].reset_index(drop=True)

    df = df.dropna(subset=["contract", "side", "lots", "price"])
    df["ts"] = [parse_ts(d, t) for d, t in zip(df["date"], df["time"])]
    df["exchange"] = df["exchange"].map(clean)
    df["raw_contract_string"] = df["contract"].map(clean)
    df["side"] = df["side"].map(lambda s: clean(s).upper())
    df["lots"] = pd.to_numeric(df["lots"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")

    bad_side = df[~df["side"].isin(["B", "S"])]
    if len(bad_side):
        raise ValueError(f"Bad Buy/Sell values: {sorted(bad_side['side'].unique())}")

    bad_num = df[df["lots"].isna() | df["price"].isna()]
    if len(bad_num):
        raise ValueError(f"{len(bad_num)} rows have unparseable lots or price.")

    bad_ts = df[df["ts"].isna()]
    if len(bad_ts):
        raise ValueError(f"{len(bad_ts)} rows have unparseable dates.")

    return df[["ts", "exchange", "raw_contract_string", "side", "lots", "price"]]


def content_key(ts, raw, side, lots, price):
    """Identity of a fill's content, ignoring how many times it occurred."""
    stamp = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")
    return f"{stamp}|{raw}|{side}|{float(lots):.10g}|{float(price):.10g}"

def dedup_hash(ts, raw, side, lots, price, seq):
    """Content plus occurrence number — distinguishes genuinely repeated fills."""
    return hashlib.sha256(f"{content_key(ts, raw, side, lots, price)}|{seq}".encode()).hexdigest()

def resolve(df, conn):
    """Attach contract_id via alias then canonical name. Adds contract_id + resolved_via."""
    aliases = {
        clean(a): cid
        for a, cid in conn.execute(text("select alias_string, contract_id from contract_aliases"))
    }
    canon = {
        clean(n): cid
        for n, cid in conn.execute(text("select canonical_name, id from contracts"))
    }

    ids, via = [], []
    for s in df["raw_contract_string"]:
        if s in aliases:
            ids.append(aliases[s])
            via.append("alias")
        elif s in canon:
            ids.append(canon[s])
            via.append("direct")
        else:
            ids.append(None)
            via.append("unmapped")

    out = df.copy()
    out["contract_id"] = ids
    out["resolved_via"] = via
    return out


def find_existing(df, conn):
    """Assign seq numbers by reconciling paste counts against stored counts.

    For each group of identical fills, the database already holds N of them.
    The paste's 1st..Nth are duplicates; the (N+1)th onward are new.
    """
    out = df.copy()
    out["content_key"] = [
        content_key(r.ts, r.raw_contract_string, r.side, r.lots, r.price)
        for r in out.itertuples()
    ]

    # Occurrence number within this paste: 1, 2, 3...
    out["paste_seq"] = out.groupby("content_key").cumcount() + 1

    # How many of each already stored?
    keys = out["content_key"].unique().tolist()
    stored = {
        k: n
        for k, n in conn.execute(
            text("""select content_key, count(*)
                    from fills where content_key = any(:k)
                    group by content_key"""),
            {"k": keys},
        )
    }
    out["stored_count"] = out["content_key"].map(stored).fillna(0).astype(int)

    out["is_duplicate"] = out["paste_seq"] <= out["stored_count"]
    out["seq"] = out["paste_seq"]
    out["dedup_hash"] = [
        dedup_hash(r.ts, r.raw_contract_string, r.side, r.lots, r.price, r.seq)
        for r in out.itertuples()
    ]
    return out


def commit(df, conn, batch_id):
    """Insert non-duplicate rows. Returns count inserted."""
    rows = df[~df["is_duplicate"]]
    n = 0
    for r in rows.itertuples():
        res = conn.execute(
            text("""insert into fills
                    (ts, exchange, raw_contract_string, contract_id, side, lots,
                     price, source, import_batch_id, dedup_hash, seq, content_key)
                    values (:ts, :ex, :raw, :cid, :side, :lots, :price,
                            'paste', :batch, :h, :seq, :ck)
                    on conflict (dedup_hash) do nothing
                    returning id"""),
            {
                "ts": r.ts,
                "ex": r.exchange,
                "raw": r.raw_contract_string,
                "cid": None if pd.isna(r.contract_id) else int(r.contract_id),
                "side": r.side,
                "lots": float(r.lots),
                "price": float(r.price),
                "batch": batch_id,
                "h": r.dedup_hash,
                "seq": int(r.seq),
                "ck": r.content_key,
            },
        ).scalar()
        if res is not None:
            n += 1
    return n