#!/usr/bin/env python3
"""Google Shopping price tracker: record prices on a schedule in SQLite, export CSV, draw a chart.

Uses the CrawlerData API (https://crawlerdata.com). Set CRAWLERDATA_API_KEY first.

Commands:
    python tracker.py check                  # check every product in products.csv, store the prices
    python tracker.py check --mode info      # cheaper: 1 credit per product, headline price only
    python tracker.py history                # latest prices and change since the previous check
    python tracker.py export -o history.csv  # full history as CSV
    python tracker.py chart -o chart.html    # self-contained HTML line chart (no dependencies)
"""
import argparse
import csv
import html
import sqlite3
import sys
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY,
    checked_at TEXT NOT NULL,
    product_id TEXT NOT NULL,
    country TEXT NOT NULL,
    label TEXT,
    mode TEXT NOT NULL,
    price REAL,
    total_price REAL,
    currency TEXT,
    merchant TEXT,
    sellers_count INTEGER,
    job_id TEXT,
    credits INTEGER
);
CREATE TABLE IF NOT EXISTS offers (
    check_id INTEGER NOT NULL REFERENCES checks(id),
    merchant TEXT,
    offer_title TEXT,
    price REAL,
    shipping REAL,
    total_price REAL,
    availability TEXT
);
CREATE INDEX IF NOT EXISTS checks_product ON checks(product_id, country, checked_at);
"""


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def value(m):
    return m["value"] if m else None


def split_words(s):
    return [w.strip().lower() for w in (s or "").replace(",", ";").split(";") if w.strip()]


def load_products(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("product_id") or "").strip()]
    if not rows:
        sys.exit(f"No products in {path}. Columns: product_id,country,label,include,exclude")
    return rows


def check_sellers(client, row, compare):
    result = client.live("google-shopping-product", {"product_id": row["product_id"], "country": row["country"]})
    if result.get("error"):
        raise RuntimeError(result["error"])
    include, exclude = split_words(row.get("include")), split_words(row.get("exclude"))
    offers = []
    for s in result.get("sellers") or []:
        title = (s.get("offer_title") or "").lower()
        if include and not all(w in title for w in include):
            continue
        if any(w in title for w in exclude):
            continue
        offers.append({
            "merchant": s.get("merchant"), "offer_title": s.get("offer_title"),
            "price": value(s.get("price")), "shipping": value(s.get("shipping")),
            "total_price": value(s.get("total_price")), "availability": s.get("availability"),
            "currency": (s.get("price") or {}).get("currency"),
        })
    key = "total_price" if compare == "total" else "price"
    priced = [o for o in offers if o[key] is not None]
    best = min(priced, key=lambda o: o[key]) if priced else {}
    summary = {
        "price": best.get("price"), "total_price": best.get("total_price"), "currency": best.get("currency"),
        "merchant": best.get("merchant"), "sellers_count": len(offers),
    }
    return summary, offers


def check_info(client, row):
    result = client.live("google-shopping-product-info", {"product_id": row["product_id"], "country": row["country"]})
    if result.get("error"):
        raise RuntimeError(result["error"])
    price = (result.get("product") or {}).get("price")
    return {"price": value(price), "total_price": None, "currency": (price or {}).get("currency"),
            "merchant": None, "sellers_count": None}, []


def cmd_check(args):
    from crawlerdata_client import CrawlerData, CrawlerDataError

    try:
        client = CrawlerData()
    except CrawlerDataError as exc:
        sys.exit(str(exc))
    db = connect(args.db)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for row in load_products(args.products):
        row["country"] = (row.get("country") or "us").strip()
        label = row.get("label") or row["product_id"]
        try:
            if args.mode == "sellers":
                summary, offers = check_sellers(client, row, args.compare)
            else:
                summary, offers = check_info(client, row)
        except CrawlerDataError as exc:
            if exc.status in (401, 402):
                sys.exit(str(exc))
            print(f"[skip] {label}: {exc}", file=sys.stderr)
            continue
        except RuntimeError as exc:
            print(f"[skip] {label}: {exc}", file=sys.stderr)
            continue
        job = client.last_job
        cur = db.execute(
            "INSERT INTO checks (checked_at, product_id, country, label, mode, price, total_price, currency,"
            " merchant, sellers_count, job_id, credits) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, row["product_id"], row["country"], label, args.mode, summary["price"], summary["total_price"],
             summary["currency"], summary["merchant"], summary["sellers_count"], job["id"], job["credits"]))
        db.executemany(
            "INSERT INTO offers VALUES (?,?,?,?,?,?,?)",
            [(cur.lastrowid, o["merchant"], o["offer_title"], o["price"], o["shipping"], o["total_price"],
              o["availability"]) for o in offers])
        db.commit()
        where = f" at {summary['merchant']}" if summary["merchant"] else ""
        sellers = f", {summary['sellers_count']} sellers" if summary["sellers_count"] is not None else ""
        print(f"{label} ({row['country']}): {summary['price']} {summary['currency'] or ''}{where}{sellers}")
    print(f"Saved to {args.db}. Credits used: {client.credits_used}")


def series(db):
    """Yield (product_id, country, mode, label, [rows oldest first])."""
    keys = db.execute("SELECT DISTINCT product_id, country, mode FROM checks ORDER BY label").fetchall()
    for k in keys:
        rows = db.execute("SELECT * FROM checks WHERE product_id=? AND country=? AND mode=? ORDER BY checked_at",
                          (k["product_id"], k["country"], k["mode"])).fetchall()
        yield k["product_id"], k["country"], k["mode"], rows[-1]["label"], rows


def cmd_history(args):
    db = connect(args.db)
    any_rows = False
    for pid, country, mode, label, rows in series(db):
        any_rows = True
        last = rows[-1]
        prev = rows[-2] if len(rows) > 1 else None
        change = ""
        if prev and prev["price"] is not None and last["price"] is not None:
            diff = last["price"] - prev["price"]
            change = "no change" if abs(diff) < 0.005 else f"{'+' if diff > 0 else ''}{diff:.2f} since {prev['checked_at']}"
        low = min((r["price"] for r in rows if r["price"] is not None), default=None)
        print(f"{label} [{pid}, {country}, {mode}]")
        print(f"  latest  {last['checked_at']}  {last['price']} {last['currency'] or ''}"
              f"{'  at ' + last['merchant'] if last['merchant'] else ''}  {change}")
        print(f"  checks  {len(rows)}   lowest seen {low}")
        for r in rows[-args.last:]:
            print(f"    {r['checked_at']}  {r['price']}  {r['merchant'] or ''}")
    if not any_rows:
        print(f"No data in {args.db} yet. Run: python tracker.py check")


def cmd_export(args):
    db = connect(args.db)
    rows = db.execute("SELECT checked_at, product_id, country, label, mode, price, total_price, currency, merchant,"
                      " sellers_count, job_id, credits FROM checks ORDER BY product_id, checked_at").fetchall()
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(rows[0].keys() if rows else ["checked_at"])
        writer.writerows([tuple(r) for r in rows])
    print(f"Wrote {len(rows)} rows to {args.output}")


COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#be185d", "#4d7c0f"]


def svg_chart(label, rows, color, w=720, h=260, pad=48):
    pts = [(r["checked_at"], r["price"]) for r in rows if r["price"] is not None]
    if not pts:
        return f"<p>{html.escape(label)}: no prices yet</p>"
    prices = [p for _, p in pts]
    lo, hi = min(prices), max(prices)
    if hi == lo:
        lo, hi = lo * 0.95, hi * 1.05 or 1
    n = len(pts)

    def x(i):
        return pad + (w - 2 * pad) * (i / (n - 1) if n > 1 else 0.5)

    def y(p):
        return h - pad - (h - 2 * pad) * (p - lo) / (hi - lo)

    line = " ".join(f"{x(i):.1f},{y(p):.1f}" for i, (_, p) in enumerate(pts))
    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(p):.1f}" r="3.5" fill="{color}"><title>{html.escape(t)}: {p}</title></circle>'
        for i, (t, p) in enumerate(pts))
    cur = rows[-1]["currency"] or ""
    return f"""<figure>
<figcaption>{html.escape(label)} &middot; latest {pts[-1][1]} {cur} &middot; low {min(prices)} &middot; high {max(prices)}</figcaption>
<svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(label)} price history">
<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="#cbd5e1"/>
<text x="{pad - 6}" y="{y(hi) + 4:.1f}" text-anchor="end">{hi:.2f}</text>
<text x="{pad - 6}" y="{y(lo) + 4:.1f}" text-anchor="end">{lo:.2f}</text>
<text x="{pad}" y="{h - pad + 18}">{html.escape(pts[0][0][:10])}</text>
<text x="{w - pad}" y="{h - pad + 18}" text-anchor="end">{html.escape(pts[-1][0][:10])}</text>
<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2"/>{dots}
</svg></figure>"""


def cmd_chart(args):
    db = connect(args.db)
    figures = [svg_chart(f"{label} ({country}, {mode})", rows, COLORS[i % len(COLORS)])
               for i, (pid, country, mode, label, rows) in enumerate(series(db))]
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Google Shopping price history</title>
<style>body{{font:14px system-ui,sans-serif;max-width:780px;margin:24px auto;padding:0 16px;color:#0f172a}}
figure{{margin:0 0 28px}}figcaption{{font-weight:600;margin-bottom:6px}}svg{{width:100%;height:auto}}
text{{font-size:11px;fill:#475569}}</style></head><body>
<h1>Google Shopping price history</h1>
<p>Lowest price per check, generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.</p>
{''.join(figures) or '<p>No data yet.</p>'}
</body></html>"""
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote {len(figures)} charts to {args.output}")


def main():
    ap = argparse.ArgumentParser(description="Track Google Shopping prices over time.")
    ap.add_argument("--db", default="prices.db", help="SQLite file (default: prices.db)")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="fetch current prices for every product and store them")
    p.add_argument("-i", "--products", default="products.csv", help="products CSV (default: products.csv)")
    p.add_argument("--mode", choices=["sellers", "info"], default="sellers",
                   help="sellers: lowest offer across all sellers (1 credit per 10 sellers); "
                        "info: product headline price (1 credit)")
    p.add_argument("--compare", choices=["total", "price"], default="total",
                   help="sellers mode: pick the lowest offer by total (with shipping) or item price")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("history", help="show latest prices and changes")
    p.add_argument("--last", type=int, default=10, help="checks to list per product (default: 10)")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("export", help="export the full history as CSV")
    p.add_argument("-o", "--output", default="price_history.csv")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("chart", help="write an HTML chart of the history")
    p.add_argument("-o", "--output", default="price_chart.html")
    p.set_defaults(func=cmd_chart)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
