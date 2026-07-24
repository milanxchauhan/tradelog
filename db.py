"""Database access. Returns dataframes for the UI."""

import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()


@st.cache_resource
def get_engine():
    return create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


@st.cache_data(ttl=60)
def load_positions():
    """One row per contract that has fills, with aggregates the engine needs."""
    q = """
    select
        c.id            as contract_id,
        p.symbol        as product,
        c.canonical_name as contract,
        c.sub_category,
        c.exchange,
        c.tick_size,
        c.tick_value,
        c.rt_count,
        p.commission_per_rt,
        p.rebate_per_rt,
        sum(case when f.side = 'B' then f.lots else 0 end)            as buy_lots,
        sum(case when f.side = 'B' then f.lots * f.price else 0 end)  as buy_notional,
        sum(case when f.side = 'S' then f.lots else 0 end)            as sell_lots,
        sum(case when f.side = 'S' then f.lots * f.price else 0 end)  as sell_notional,
        m.last_price
    from fills f
    join contracts c on c.id = f.contract_id
    join products  p on p.id = c.product_id
    left join marks m on m.contract_id = c.id
    group by c.id, p.symbol, c.canonical_name, c.sub_category,
             c.exchange, c.tick_size, c.tick_value, c.rt_count,
             p.commission_per_rt, p.rebate_per_rt, m.last_price
    """
    with get_engine().connect() as conn:
        return pd.read_sql(text(q), conn)


@st.cache_data(ttl=60)
def load_settings():
    with get_engine().connect() as conn:
        rows = conn.execute(text("select key, value from settings")).all()
    return {k: float(v) for k, v in rows}


@st.cache_data(ttl=60)
def load_unmapped():
    q = """
    select raw_contract_string, exchange, count(*) as fills, sum(lots) as lots
    from fills where contract_id is null
    group by 1, 2 order by 3 desc
    """
    with get_engine().connect() as conn:
        return pd.read_sql(text(q), conn)