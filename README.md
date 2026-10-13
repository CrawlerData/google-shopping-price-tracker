# Google Shopping Price Tracker (Python)

Track Google Shopping prices over time. List your products in a CSV, run `tracker.py check` on a schedule (cron, Task Scheduler or GitHub Actions), and every run stores the lowest price, the seller offering it and the seller count in a local SQLite database. Then print the price history with changes, export it to CSV, or open a self-contained HTML chart. Python with one dependency (`requests`); SQLite and the chart use only the standard library.

> **Uses the CrawlerData API — you need an API key** (free trial credits available at https://app.crawlerdata.com/register). Sellers mode costs 1 credit per 10 sellers returned per product; info mode costs 1 credit per product.

## Features

- Products in a plain CSV: `product_id, country, label, include, exclude`
- **Sellers mode** (default): the lowest offer across all Google Shopping sellers, with merchant name and seller count; every offer is saved too, so you can query any seller's price history
- **Info mode** (`--mode info`): the product's headline price for exactly 1 credit per product
- Keyword filters per product so accessories, other sizes or renewed units don't become "the lowest price"
- `history`: latest price, change since the previous check, lowest price seen
- `export`: full history as CSV; `chart`: an HTML file with one SVG line chart per product (no JavaScript, no libraries)
- Ready-made [GitHub Actions workflow](examples/github-actions.yml) for a daily run

## Quickstart

```bash
git clone https://github.com/CrawlerData/google-shopping-price-tracker.git
cd google-shopping-price-tracker
pip install -r requirements.txt

export CRAWLERDATA_API_KEY="your_api_key"        # PowerShell: $env:CRAWLERDATA_API_KEY="your_api_key"

python tracker.py check            # run this on a schedule
python tracker.py history
python tracker.py export -o price_history.csv
python tracker.py chart -o price_chart.html
```

## Input: `products.csv`

```csv
product_id,country,label,include,exclude
11726664398501807381,us,Sony WH-1000XM5,,renewed;refurbished
7580511071886337697,us,Samsung Galaxy Buds3 FE,,case;renewed
```

- `product_id`: Google Shopping product ID. Get it with the [Google Shopping scraper](https://github.com/CrawlerData/google-shopping-scraper) (each result has one) or from `gpcid:` in a Google Shopping URL. Search by **brand + model**, not by GTIN/UPC: a bare barcode search often returns unrelated products.
- `country`: one of 31 country codes (`us`, `gb`, `de`, `fr`, `ca`, `au`, ...). Prices come back in that country's currency.
- `include` / `exclude`: optional words (separated by `;`) that an offer title must / must not contain. A product's offers can include accessories or other sizes; filter them here.

## Sample output

Real runs on 13 October 2026: `check` (sellers mode), `check --mode info`, then `check` again:

```text
$ python tracker.py check
Sony WH-1000XM5 (us): 228 USD at Best Buy, 10 sellers
Samsung Galaxy Buds3 FE (us): 94.99 USD at Walmart - Truly Trending, 10 sellers
Saved to prices.db. Credits used: 2

$ python tracker.py check --mode info
Sony WH-1000XM5 (us): 228 USD
Samsung Galaxy Buds3 FE (us): 99.99 USD
Saved to prices.db. Credits used: 2

$ python tracker.py history
Samsung Galaxy Buds3 FE [7580511071886337697, us, sellers]
  latest  2026-10-13T05:11:59Z  94.99 USD  at Walmart - Truly Trending  no change
  checks  2   lowest seen 94.99
    2026-10-13T05:11:01Z  94.99  Walmart - Truly Trending
    2026-10-13T05:11:59Z  94.99  Walmart - Truly Trending
Samsung Galaxy Buds3 FE [7580511071886337697, us, info]
  latest  2026-10-13T05:11:50Z  99.99 USD
  checks  1   lowest seen 99.99
...
```

Note the difference between the modes: the headline price (info) for the Buds was 99.99, while the cheapest seller was at 94.99. Use sellers mode when you need the actual lowest price and who offers it.

`export` writes one row per check ([`examples/sample-price-history.csv`](examples/sample-price-history.csv)):

```csv
checked_at,product_id,country,label,mode,price,total_price,currency,merchant,sellers_count,job_id,credits
2026-10-13T05:11:01Z,11726664398501807381,us,Sony WH-1000XM5,sellers,228.0,228.0,USD,Best Buy,10,6acdbd67aaddb7eaed95a8b7,1
2026-10-13T05:11:50Z,11726664398501807381,us,Sony WH-1000XM5,info,228.0,,USD,,,6acdbd97aaddb7eaed95a8d3,1
```

`chart` writes `price_chart.html` with one line chart per product and mode (hover a point for its date and price).

## Running it on a schedule

**Linux / macOS (cron), every day at 07:00:**

```cron
0 7 * * * cd /path/to/google-shopping-price-tracker && CRAWLERDATA_API_KEY=your_api_key /usr/bin/python3 tracker.py check >> tracker.log 2>&1
```

**Windows (Task Scheduler):**

```powershell
setx CRAWLERDATA_API_KEY your_api_key
schtasks /Create /SC DAILY /ST 07:00 /TN "PriceTracker" /TR "cmd /c cd /d C:\path\to\google-shopping-price-tracker && python tracker.py check >> tracker.log 2>&1"
```

**GitHub Actions:** see [`examples/github-actions.yml`](examples/github-actions.yml). It runs the check daily and commits `prices.db` and the chart back to your repo. Use a private copy.

## Cost per run

| Mode | Credits per product per check | Example: 50 products, daily for 30 days |
| --- | --- | --- |
| `sellers` | 1 per 10 sellers returned (rounded up, min 1) | 1,500 credits at up to 10 sellers per product, 4,500 at 21-30 sellers |
| `info` | 1 | 1,500 credits |

Both test products had 10 sellers, so each sellers check cost 1 credit; the test runs above used 6 credits in total. Failed jobs cost nothing. Packs run from $1.00 down to $0.30 per 1,000 credits ([pricing](https://crawlerdata.com/pricing)).

## Options

| Command / option | Default | Description |
| --- | --- | --- |
| `--db FILE` | `prices.db` | SQLite file (goes before the command: `python tracker.py --db x.db check`) |
| `check -i FILE` | `products.csv` | Products to check |
| `check --mode` | `sellers` | `sellers` (lowest offer across sellers) or `info` (headline price, 1 credit) |
| `check --compare` | `total` | Sellers mode: lowest by `total` (price + shipping) or `price` |
| `history --last N` | `10` | Checks listed per product |
| `export -o FILE` | `price_history.csv` | CSV export |
| `chart -o FILE` | `price_chart.html` | HTML chart |

The database has two tables: `checks` (one row per product per run) and `offers` (every seller offer for that check), so this gives a per-seller price history:

```sql
SELECT checks.checked_at, offers.merchant, offers.price
FROM offers JOIN checks ON checks.id = offers.check_id
WHERE checks.label = 'Sony WH-1000XM5'
ORDER BY offers.merchant, checks.checked_at;
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `HTTP 401` | The API key is missing or wrong. Check `echo $CRAWLERDATA_API_KEY` (or `$env:CRAWLERDATA_API_KEY` in PowerShell) and create a key under API Access in the [dashboard](https://app.crawlerdata.com). |
| `HTTP 402` | You are out of credits. Buy a credit pack in the dashboard (from $1.00 down to $0.30 per 1,000 credits, see [pricing](https://crawlerdata.com/pricing)). |
| `HTTP 429` | Rate limit: 100 requests per minute and 20 per second per key. The client waits until `X-RateLimit-Reset` and retries automatically; for big batches, spread requests out. |
| Timeouts | Live requests return when Google has been fetched: a few seconds for search, 30 to 120 seconds for Google Shopping sellers. The client uses a 200 second timeout. |
| `job ... failed` | The HTTP call worked but the job did not (for example Google blocked that attempt). Failed jobs cost 0 credits and the client retries them twice before giving up. |

## Links

- [CrawlerData](https://crawlerdata.com)
- [Google Shopping Sellers API](https://crawlerdata.com/apis/google-shopping-sellers-api) and [Google Shopping Product API](https://crawlerdata.com/apis/google-shopping-product-api)
- [API docs](https://app.crawlerdata.com/docs)
- [Google Shopping API pricing compared](https://crawlerdata.com/blog/google-shopping-api-pricing)

## More CrawlerData examples

| Repo | What it does |
| --- | --- |
| [google-shopping-scraper](https://github.com/CrawlerData/google-shopping-scraper) | Search Google Shopping, export products to CSV/JSON (Python + Node.js) |
| [google-shopping-sellers-scraper](https://github.com/CrawlerData/google-shopping-sellers-scraper) | Every seller and price for one product, as a comparison table |
| [google-shopping-price-tracker](https://github.com/CrawlerData/google-shopping-price-tracker) | Scheduled price history in SQLite, CSV export and an HTML chart |
| [competitor-price-monitoring](https://github.com/CrawlerData/competitor-price-monitoring) | Your catalog vs Google Shopping sellers, with undercut alerts |
| [map-violation-monitor](https://github.com/CrawlerData/map-violation-monitor) | Flag sellers below MAP with timestamped evidence |
| [google-search-scraper](https://github.com/CrawlerData/google-search-scraper) | Google SERP to JSON/CSV: organic, ads, People Also Ask, AI Overview (Python + Node.js) |
| [google-rank-tracker](https://github.com/CrawlerData/google-rank-tracker) | Daily keyword positions by country and device, with a change report |
| [google-local-business-leads](https://github.com/CrawlerData/google-local-business-leads) | Google Local results to a lead list CSV |
| [google-news-scraper](https://github.com/CrawlerData/google-news-scraper) | Brand and keyword news monitoring to CSV and JSON Feed |
| [google-search-mcp-server](https://github.com/CrawlerData/google-search-mcp-server) | Connect Claude, Cursor or n8n to the CrawlerData MCP server |
| [crawlerdata-examples](https://github.com/CrawlerData/crawlerdata-examples) | Python, Node.js and curl snippets for every endpoint |

## License

MIT. See [LICENSE](LICENSE). Google and Google Shopping are trademarks of Google LLC; this project is not affiliated with Google.
