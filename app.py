import streamlit as st

import db
from pnl import compute_frame

st.set_page_config(page_title="Trade Log", layout="wide")


raw = db.load_positions()
pos = compute_frame(raw)

st.title("Trade Log")

if st.button("Refresh"):
    st.cache_data.clear()
    st.rerun()

tab_dash, tab_active, tab_all, tab_unmapped = st.tabs(
    ["Dashboard", "Active", "All Contracts", "Unmapped"]
)

MONEY = "%.2f"

with tab_dash:
    by_product = (
        pos.groupby("product")
        .agg(
            booked_pl=("booked_pl", "sum"),
            running_pl=("running_pl", "sum"),
            rt=("rt", "sum"),
            commission=("commission", "sum"),
            rebate=("rebate", "sum"),
            net_pl=("net_pl", "sum"),
        )
        .reset_index()
        .sort_values("net_pl", ascending=False)
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Booked P/L", f"{by_product.booked_pl.sum():,.2f}")
    c2.metric("Running P/L", f"{by_product.running_pl.sum():,.2f}")
    c3.metric("Total RT", f"{by_product.rt.sum():,.0f}")
    c4.metric("Net P/L", f"{by_product.net_pl.sum():,.2f}")

    st.dataframe(
        by_product,
        use_container_width=True,
        hide_index=True,
        column_config={
            "booked_pl": st.column_config.NumberColumn("Booked P/L", format=MONEY),
            "running_pl": st.column_config.NumberColumn("Running P/L", format=MONEY),
            "commission": st.column_config.NumberColumn("Commission", format=MONEY),
            "rebate": st.column_config.NumberColumn("Rebate", format=MONEY),
            "net_pl": st.column_config.NumberColumn("Net P/L", format=MONEY),
        },
    )

with tab_active:
    active = pos[pos.open_pos != 0].sort_values(["product", "contract"])
    st.caption(f"{len(active)} contracts with an open position")
    st.dataframe(
        active[["product", "contract", "exchange", "buy_lots", "avg_buy",
                "sell_lots", "avg_sell", "open_pos", "avg_open",
                "last_price", "running_pl", "booked_pl"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "avg_buy": st.column_config.NumberColumn("Avg Buy", format="%.4f"),
            "avg_sell": st.column_config.NumberColumn("Avg Sell", format="%.4f"),
            "avg_open": st.column_config.NumberColumn("Avg Open", format="%.4f"),
            "running_pl": st.column_config.NumberColumn("Running P/L", format=MONEY),
            "booked_pl": st.column_config.NumberColumn("Booked P/L", format=MONEY),
        },
    )

with tab_all:
    products = ["(all)"] + sorted(pos["product"].dropna().unique().tolist())
    pick = st.selectbox("Product", products)
    view = pos if pick == "(all)" else pos[pos["product"] == pick]
    st.dataframe(
        view[["product", "contract", "exchange", "buy_lots", "avg_buy",
              "sell_lots", "avg_sell", "open_pos", "booked_pl",
              "rt", "net_pl"]].sort_values(["product", "contract"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "avg_buy": st.column_config.NumberColumn("Avg Buy", format="%.4f"),
            "avg_sell": st.column_config.NumberColumn("Avg Sell", format="%.4f"),
            "booked_pl": st.column_config.NumberColumn("Booked P/L", format=MONEY),
            "net_pl": st.column_config.NumberColumn("Net P/L", format=MONEY),
        },
    )

with tab_unmapped:
    un = db.load_unmapped()
    if un.empty:
        st.success("No unmapped fills.")
    else:
        st.warning(f"{len(un)} unmapped contract strings")
        st.dataframe(un, use_container_width=True, hide_index=True)