import streamlit as st

import db
from pnl import compute_frame

from datetime import datetime
import admin
import mapper
import importer

def check_password():
    if st.session_state.get("authed"):
        return True

    placeholder = st.empty()
    pw = placeholder.text_input("Password", type="password")
    if pw:
        if pw == st.secrets.get("APP_PASSWORD"):
            st.session_state["authed"] = True
            placeholder.empty()   # remove the box from the page
            st.rerun()            # redraw cleanly without it
        else:
            st.error("Wrong password.")
    return False


if not check_password():
    st.stop()

st.set_page_config(page_title="Trade Log", page_icon="▤", layout="wide")

import style
style.apply()

raw = db.load_positions()
pos = compute_frame(raw)

st.title("Trade Log")

if st.button("Refresh"):
    st.cache_data.clear()
    st.rerun()

(tab_paste, tab_dash, tab_active, tab_all, tab_unmapped, tab_settings) = st.tabs(
    ["Paste Fills", "Dashboard", "Active", "All Contracts", "Unmapped", "Settings"]
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

    total_booked = by_product.booked_pl.sum()
    total_running = by_product.running_pl.sum()
    total_net = by_product.net_pl.sum()

    def pl_delta(v):
        return f"{v:,.2f}"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Booked P/L", f"${total_booked:,.0f}", pl_delta(total_booked))
    c2.metric("Running P/L", f"${total_running:,.0f}", pl_delta(total_running))
    c3.metric("Total RT", f"{by_product.rt.sum():,.0f}")
    c4.metric("Net P/L", f"${total_net:,.0f}", pl_delta(total_net))

    st.dataframe(
        by_product.style.map(
            lambda v: f"color: {'#22c55e' if v >= 0 else '#ef4444'}",
            subset=["booked_pl", "running_pl", "net_pl"],
        ),
        use_container_width=True, hide_index=True,
        column_config={
            "booked_pl": st.column_config.NumberColumn("Booked P/L", format="%.2f"),
            "running_pl": st.column_config.NumberColumn("Running P/L", format="%.2f"),
            "commission": st.column_config.NumberColumn("Commission", format="%.2f"),
            "rebate": st.column_config.NumberColumn("Rebate", format="%.2f"),
            "net_pl": st.column_config.NumberColumn("Net P/L", format="%.2f"),
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

        st.divider()
        st.subheader("Map a contract")

        raw = st.selectbox("Unmapped string", un["raw_contract_string"].tolist())
        row = un[un.raw_contract_string == raw].iloc[0]
        st.caption(f"{int(row.fills)} fills · exchange {row.exchange}")

        eng = db.get_engine()
        with eng.connect() as conn:
            prods = mapper.products(conn)

        mode = st.radio(
            "How should this resolve?",
            ["New contract (CME/ICE — string is the name)",
             "Alias to existing contract (ASE code)"],
        )

        # Guess the product from the leading token of the string
        guess = raw.split()[0].split("-")[0].strip()
        default_idx = prods.index(guess) if guess in prods else 0

        if mode.startswith("New"):
            symbol = st.selectbox("Product", prods, index=default_idx)
            with eng.connect() as conn:
                d = mapper.product_defaults(conn, symbol)
            c1, c2, c3 = st.columns(3)
            tick_size = c1.number_input("Tick size", value=d.get("tick_size", 0.25), format="%.6f")
            tick_value = c2.number_input("Tick value", value=d.get("tick_value", 12.5), format="%.4f")
            rt_count = c3.number_input("RT count", value=2.0, step=1.0)
            sub_category = st.text_input("Sub-category", value=symbol)

            if st.button("Create & map", type="primary"):
                with eng.begin() as conn:
                    n = mapper.create_direct(
                        conn, symbol, raw, tick_size, tick_value, rt_count,
                        sub_category, row.exchange,
                    )
                st.cache_data.clear()
                st.success(f"Mapped. {n} fills resolved.")
                st.rerun()

        else:
            symbol = st.selectbox("Product", prods, index=default_idx)
            with eng.connect() as conn:
                choices = mapper.contracts_for_product(conn, symbol)
            if not choices:
                st.info("No contracts for this product yet — create one via the other mode first.")
            else:
                labels = {name: cid for cid, name in choices}
                pick = st.selectbox("Point to contract", list(labels.keys()))
                if st.button("Create alias & map", type="primary"):
                    with eng.begin() as conn:
                        n = mapper.create_aliased(conn, raw, labels[pick])
                    st.cache_data.clear()
                    st.success(f"Aliased. {n} fills resolved.")
                    st.rerun()

with tab_settings:
    st.subheader("Settings")
    eng = db.get_engine()
    with eng.connect() as conn:
        c = admin.counts(conn)
    st.caption(
        f"{c['fills']:,} fills · {c['contracts']:,} contracts · "
        f"{c['aliases']:,} aliases · {c['products']:,} products"
    )

    # ---- Import ----
    st.divider()
    st.markdown("#### Import data")
    st.caption("Upload an Excel in the standard format. Fills are added and de-duplicated — re-uploading is safe.")
    up = st.file_uploader("Excel file", type=["xlsx"])
    if up is not None:
        try:
            parsed = admin.load_excel_fills(up)
            with eng.begin() as conn:
                np_, nc_ = admin.load_excel_full(up, conn)
            st.info(f"Loaded mapping: {np_} products, {nc_} contracts.")
        except Exception as e:
            st.error(f"Could not read file: {e}")
            parsed = None

        if parsed is not None and len(parsed):
            with eng.connect() as conn:
                resolved = importer.resolve(parsed, conn)
                checked = importer.find_existing(resolved, conn)
            n_new = int((~checked.is_duplicate).sum())
            n_dup = int(checked.is_duplicate.sum())
            n_unmapped = int(((~checked.is_duplicate) & (checked.resolved_via == "unmapped")).sum())

            m1, m2, m3 = st.columns(3)
            m1.metric("New", n_new)
            m2.metric("Duplicates", n_dup)
            m3.metric("Unmapped", n_unmapped)

            if n_new and st.button(f"Import {n_new} fills", type="primary"):
                from datetime import datetime
                batch = "xlsx-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                with eng.begin() as conn:
                    inserted = importer.commit(checked, conn, batch)
                st.cache_data.clear()
                st.success(f"Imported {inserted} fills.")
                st.rerun()

    # ---- Danger zone ----
    st.divider()
    st.markdown("#### :red[Danger zone]")

    scope = st.radio(
        "What to delete",
        ["Fills only (keep contracts & mapping)", "Everything (fills, contracts, aliases, products)"],
    )
    everything = scope.startswith("Everything")

    st.warning(
        "This permanently deletes data and cannot be undone. "
        + ("Your contract mapping will be wiped too — you'd need to re-import or re-map."
           if everything else "Your contract mapping is kept; only fills are removed.")
    )

    phrase = "DELETE EVERYTHING" if everything else "DELETE FILLS"
    typed = st.text_input(f"Type **{phrase}** to confirm")
    if st.button("Delete", type="primary", disabled=(typed != phrase)):
        with eng.begin() as conn:
            n = admin.delete_everything(conn) if everything else admin.delete_fills_only(conn)
        st.cache_data.clear()
        st.success(f"Deleted {n:,} fills." + (" All mapping removed." if everything else ""))
        st.rerun()