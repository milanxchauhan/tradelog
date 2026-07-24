"""Position and P/L engine. Pure functions — no DB, no I/O."""
import numpy as np

from dataclasses import dataclass


@dataclass
class Fill:
    side: str      # 'B' or 'S'
    lots: float
    price: float


@dataclass
class Position:
    buy_lots: float = 0.0
    sell_lots: float = 0.0
    avg_buy: float = 0.0
    avg_sell: float = 0.0
    open_pos: float = 0.0
    avg_open: float = 0.0
    booked_lots: float = 0.0
    booked_pl: float = 0.0
    running_pl: float = 0.0
    rt: float = 0.0
    avg_ticks: float = 0.0


def compute(fills, tick_size, tick_value, rt_count=1.0, last=None):
    """Average-price P/L for one contract."""
    buy_lots = sum(f.lots for f in fills if f.side == "B")
    sell_lots = sum(f.lots for f in fills if f.side == "S")
    buy_notional = sum(f.lots * f.price for f in fills if f.side == "B")
    sell_notional = sum(f.lots * f.price for f in fills if f.side == "S")

    p = Position()
    p.buy_lots = buy_lots
    p.sell_lots = sell_lots
    p.avg_buy = buy_notional / buy_lots if buy_lots else 0.0
    p.avg_sell = sell_notional / sell_lots if sell_lots else 0.0
    p.open_pos = buy_lots - sell_lots

    p.booked_lots = min(buy_lots, sell_lots)
    if p.booked_lots:
        ticks = (p.avg_sell - p.avg_buy) / tick_size
        p.booked_pl = p.booked_lots * ticks * tick_value
        p.avg_ticks = ticks

    if p.open_pos > 0:
        p.avg_open = p.avg_buy
    elif p.open_pos < 0:
        p.avg_open = p.avg_sell

    if p.open_pos and last is not None:
        ticks = (last - p.avg_open) / tick_size
        p.running_pl = p.open_pos * ticks * tick_value

    p.rt = (buy_lots + sell_lots) * rt_count
    return p


def net_pl(p, commission_per_rt=1.42, rebate_per_rt=0.30):
    """Booked P/L after commission and rebate."""
    return p.booked_pl - p.rt * commission_per_rt + p.rt * rebate_per_rt

def compute_frame(df):
    """Apply the P/L formulas to a positions dataframe. Same math as compute()."""
    d = df.copy()

    d["avg_buy"] = np.where(d.buy_lots > 0, d.buy_notional / d.buy_lots.replace(0, np.nan), 0.0)
    d["avg_sell"] = np.where(d.sell_lots > 0, d.sell_notional / d.sell_lots.replace(0, np.nan), 0.0)
    d[["avg_buy", "avg_sell"]] = d[["avg_buy", "avg_sell"]].fillna(0.0)

    d["open_pos"] = d.buy_lots - d.sell_lots
    d["booked_lots"] = np.minimum(d.buy_lots, d.sell_lots)

    d["avg_ticks"] = np.where(
        d.booked_lots > 0, (d.avg_sell - d.avg_buy) / d.tick_size, 0.0
    )
    d["booked_pl"] = d.booked_lots * d.avg_ticks * d.tick_value

    d["avg_open"] = np.where(d.open_pos > 0, d.avg_buy,
                    np.where(d.open_pos < 0, d.avg_sell, 0.0))
    d["running_pl"] = np.where(
        (d.open_pos != 0) & d.last_price.notna(),
        d.open_pos * (d.last_price - d.avg_open) / d.tick_size * d.tick_value,
        0.0,
    )

    d["rt"] = (d.buy_lots + d.sell_lots) * d.rt_count
    d["commission"] = d.rt * d.commission_per_rt
    d["rebate"] = d.rt * d.rebate_per_rt
    d["net_pl"] = d.booked_pl - d.commission + d.rebate
    d["total_pl"] = d.booked_pl + d.running_pl

    return d