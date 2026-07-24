import streamlit as st

import db
from pnl import compute_frame

from datetime import datetime

import importer

def check_password():
    if st.session_state.get("authed"):
        return True
    pw = st.text_input("Password", type="password")
    if pw:
        if pw == st.secrets.get("APP_PASSWORD"):
            st.session_state["authed"] = True
            return True
        st.error("Wrong password.")
    return False


if not check_password():
    st.stop()

st.set_page_config(page_title="Trade Log", layout="wide")


raw = db.load_positions()
pos = compute_frame(raw)

st.title("Trade Log")

if st.button("Refresh"):
    st.cache_data.clear()
    st.rerun()

tab_paste, tab_dash, tab_active, tab_all, tab_unmapped = st.tabs(
    ["Paste Fills", "Dashboard", "Active", "All Contracts", "Unmapped"]
)

with tab_paste:
    st.subheader("Paste fills")
    st.caption("7 columns, tab-separated: date, time, exchange, contract, B/S, lots, price")

    pasted = st.text_area("Fills", height=250, key="paste_box",
                          placeholder="24Jul26\t16:53:46.192\tASE\tZS - [DFLY] - Jan27 [1:-3] - ASE\tS\t1\t2.75")

    if pasted.strip():
        try:
            parsed = importer.parse_paste(pasted)
        except ValueError as e:
            st.error(str(e))
            st.stop()

        eng = db.get_engine()
        with eng.connect() as conn:
            resolved = importer.resolve(parsed, conn)
            checked = importer.find_existing(resolved, conn)

        n_new = int((~checked.is_duplicate).sum())
        n_dup = int(checked.is_duplicate.sum())
        n_unmapped = int(((~checked.is_duplicate) & (checked.resolved_via == "unmapped")).sum())

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Parsed", len(checked))
        c2.metric("New", n_new)
        c3.metric("Duplicates", n_dup)
        c4.metric("Unmapped", n_unmapped)

        if n_unmapped:
            st.warning(
                f"{n_unmapped} fills have contracts not in your mapping. "
                "They will import and appear in the Unmapped tab."
            )

        st.dataframe(
            checked[["ts", "exchange", "raw_contract_string", "side", "lots",
                     "price", "resolved_via", "is_duplicate"]],
            use_container_width=True, hide_index=True,
        )

        if n_new == 0:
            st.info("Nothing new to import.")
        else:
            if st.button(f"Import {n_new} fills", type="primary"):
                batch = datetime.now().strftime("%Y%m%d-%H%M%S")
                with eng.begin() as conn:
                    inserted = importer.commit(checked, conn, batch)
                st.cache_data.clear()
                st.success(f"Imported {inserted} fills (batch {batch}).")

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