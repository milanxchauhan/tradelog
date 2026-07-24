"""Validate the P/L engine against known Excel values, reading from Postgres."""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from pnl import Fill, compute

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])

EXPECTED = [
    ("ZS Mar26 2mo Butterfly",               35,  35,   0, 537.50),
    ("ZS - [DFLY] - Jan27 - [1:-2:1] - ASE", 20,  18,   2, 768.75),
    ("ZS - [CSTM] - Nov26 - ASE [2:-1]",      9,  11,  -2, -1047.73),
    ("ZS - [DFLY] - Mar27 - [1:-2:1] - ASE",  6,  14,  -8, 364.29),
    ("ZS Jul26 1mo Butterfly",                7,   7,   0, -700.00),
]

failures = 0
with engine.connect() as conn:
    for name, exp_bq, exp_sq, exp_pos, exp_pl in EXPECTED:
        row = conn.execute(
            text("select id, tick_size, tick_value, rt_count from contracts where canonical_name = :n"),
            {"n": name},
        ).first()
        if not row:
            print(f"NOT FOUND: {name}")
            failures += 1
            continue

        cid, tick_size, tick_value, rt_count = row
        fills = [
            Fill(side=r[0], lots=float(r[1]), price=float(r[2]))
            for r in conn.execute(
                text("select side, lots, price from fills where contract_id = :c"),
                {"c": cid},
            )
        ]

        p = compute(fills, float(tick_size), float(tick_value), float(rt_count))
        ok = (
            abs(p.buy_lots - exp_bq) < 1e-6
            and abs(p.sell_lots - exp_sq) < 1e-6
            and abs(p.open_pos - exp_pos) < 1e-6
            and abs(p.booked_pl - exp_pl) < 0.01
        )
        if not ok:
            failures += 1
        print(
            f"{'PASS' if ok else 'FAIL'}  {name[:38]:40s} "
            f"bq {p.buy_lots:5.0f}/{exp_bq:<5.0f} "
            f"sq {p.sell_lots:5.0f}/{exp_sq:<5.0f} "
            f"pos {p.open_pos:4.0f}/{exp_pos:<4.0f} "
            f"pl {p.booked_pl:10.2f}/{exp_pl:<10.2f}"
        )

print(f"\n{len(EXPECTED) - failures}/{len(EXPECTED)} passed")