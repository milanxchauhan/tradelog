"""Create contracts/aliases for unmapped strings and backfill fills."""

from sqlalchemy import text


def products(conn):
    return [r[0] for r in conn.execute(
        text("select symbol from products order by symbol"))]


def contracts_for_product(conn, symbol):
    return [
        (r[0], r[1])
        for r in conn.execute(
            text("""select c.id, c.canonical_name
                    from contracts c join products p on p.id = c.product_id
                    where p.symbol = :s order by c.canonical_name"""),
            {"s": symbol},
        )
    ]


def product_defaults(conn, symbol):
    """Tick size/value and a typical RT for a product, to prefill the form."""
    row = conn.execute(
        text("""select tick_size, tick_value from products where symbol = :s"""),
        {"s": symbol},
    ).first()
    return {"tick_size": float(row[0]), "tick_value": float(row[1])} if row else {}


def backfill(conn, raw_string):
    """Resolve every unmapped fill matching this string (direct or via alias)."""
    return conn.execute(
        text("""
            update fills f set contract_id = sub.cid
            from (
                select c.id as cid, c.canonical_name as name from contracts c
                union all
                select a.contract_id, a.alias_string from contract_aliases a
            ) sub
            where f.contract_id is null
              and f.raw_contract_string = sub.name
              and sub.name = :raw
        """),
        {"raw": raw_string},
    ).rowcount


def create_direct(conn, symbol, raw_string, tick_size, tick_value, rt_count,
                  sub_category, exchange):
    """CME/ICE: the string is the canonical name."""
    pid = conn.execute(
        text("select id from products where symbol = :s"), {"s": symbol}
    ).scalar()
    conn.execute(
        text("""insert into contracts
                (product_id, canonical_name, tick_size, tick_value, rt_count,
                 sub_category, exchange)
                values (:p, :name, :ts, :tv, :rt, :sub, :ex)
                on conflict (canonical_name) do nothing"""),
        {"p": pid, "name": raw_string, "ts": tick_size, "tv": tick_value,
         "rt": rt_count, "sub": sub_category, "ex": exchange},
    )
    return backfill(conn, raw_string)


def create_aliased(conn, raw_string, contract_id):
    """ASE: point the string at an existing contract as an alias."""
    conn.execute(
        text("""insert into contract_aliases (contract_id, source, alias_string)
                values (:c, 'ASE', :a) on conflict do nothing"""),
        {"c": contract_id, "a": raw_string},
    )
    return backfill(conn, raw_string)