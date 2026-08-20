# ScrapeFlow

A from-scratch, portfolio-safe rebuild of a production scraping-pipeline architecture I've worked with professionally. It's not derived from any employer's codebase — every line here targets public scrape-practice sites (`books.toscrape.com`, `quotes.toscrape.com`) and was written independently to demonstrate the same engineering patterns: a **FastAPI** service that accepts a URL, dispatches it to a domain-specific crawler, renders it with **Playwright**, converts content to Markdown with **Crawl4AI**, optionally indexes it into **Elasticsearch**, and serves a static search/browse dashboard over the result.

---

## Why this exists

Real recruiting-platform / job-board scraping code is client work and isn't mine to publish. This project exists so the *architecture* — the part that's actually interview-relevant — has a public, runnable home. Everything below is either a direct reimplementation of a generic engineering pattern (retry/restart logic, event-loop bridging, upsert semantics) or built fresh against public target sites.

---

## What it demonstrates

| Pattern | Where |
|---|---|
| Domain → crawler dispatch via a registry dict (no if/elif chains) | `dispatcher/crawler_dispatcher.py` |
| Abstract crawler interface with an opt-out for self-managed rendering | `crawlers/base_crawler.py` |
| Running Playwright under a web framework whose event loop can't spawn subprocesses | `core/browser.py` |
| "Hybrid" pattern — orchestrator pre-renders page one, crawler then owns its own click-through phase | `crawlers/books_crawler.py` |
| "Fully self-managed" pattern — crawler owns pagination *and* the detail-page crawl | `crawlers/quotes_authors_crawler.py`, `crawlers/click_through_base.py` |
| Streaming results out mid-crawl instead of buffering everything in memory (both crawlers) | `crawlers/books_crawler.py::stream_extract`, `crawlers/quotes_authors_crawler.py::stream_extract` |
| Scoping Crawl4AI to just the freeform-prose element via `css_selector`, leaving structured fields to BeautifulSoup | `crawlers/books_crawler.py::_extract_book` |
| Generic any-URL scraping (no dispatch) with HTML→Markdown via Crawl4AI | `services/scrape_service.py` |
| Idempotent upsert keyed by `md5(url)`, preserving `createdAt` across re-crawls | `db/elasticsearch_indexer.py` |
| Optional dependency — the whole app runs with `indexer=None` if ES isn't configured | `api/dependencies.py` |
| `TEST_MODE` capping collection without truncating pagination | `crawlers/pagination.py` |
| Read-only search/browse API over the same index, decoupled from the write path | `api/dashboard_router.py` |
| Static frontend served by FastAPI's `StaticFiles`, mounted after all API routes | `main.py`, `frontend/` |

---

## Architecture

```text
webscraping-learning/
├── api/
│   ├── dependencies.py         # FastAPI DI — ExtractionService/ScrapeService wiring
│   ├── routers.py               # POST /extract, POST /scrape, GET /health
│   └── dashboard_router.py      # read-only GET /api/dashboard/{domains,search,report/today}
├── core/                   # config, logging, exceptions, the Playwright renderer
├── crawlers/                
│   ├── base_crawler.py         # BaseCrawler ABC — extract() / stream_extract()
│   ├── click_through_base.py   # shared browser-restart + retry + streaming utility
│   ├── pagination.py           # shared "walk Next-page links, cap collection" helper
│   ├── books_crawler.py        # hybrid pattern: pre-rendered listing + its own detail-page crawl
│   └── quotes_authors_crawler.py  # fully self-managed: paginate + visit N detail pages
├── db/                      # Elasticsearch client + upsert indexer
├── dispatcher/              # DOMAIN_REGISTRY + resolve_crawler()
├── models/                  # RawJobData / ScrapedItem dataclasses, Pydantic schemas
├── services/                
│   ├── extraction_service.py   # orchestrates dispatch -> crawl -> clean -> index
│   ├── scrape_service.py       # generic Playwright -> Crawl4AI -> Markdown, any URL
│   ├── text_cleaner.py         # Markdown -> plain text normalization
│   └── batch_runner.py         # standalone script: crawl every registered domain
├── frontend/                # static dashboard, served via FastAPI StaticFiles
│   ├── index.html               # Search page
│   ├── domain-browser.html      # Browse Domains page
│   ├── css/
│   └── js/
│       ├── common.js            # shared table/pagination/report-modal rendering
│       ├── app.js               # search page logic
│       └── domain-browser.js    # domain card grid + per-domain jobs view
├── tests/
└── main.py
```

### Why two crawlers, not thirty

The production system this is modeled on registers ~30 domains. Two is enough to prove out every non-trivial code path (both branches of `requires_prerendered_html()`, the streaming queue bridge, browser-restart batching, scoped Crawl4AI extraction) without thirty near-duplicate files. Adding an eleventh, twelfth, thirtieth crawler is what the `DOMAIN_REGISTRY` + `BaseCrawler` split is *for* — see "Adding a new crawler" below.

---

## The two crawlers

Both crawlers now use Crawl4AI and both stream results via the same `asyncio.Queue` bridge — the deliberate difference between them is *who owns page-one rendering*.

### `BooksCatalogCrawler` — books.toscrape.com (hybrid)

`requires_prerendered_html()` returns `True` — `ExtractionService` renders the listing page once with Playwright and hands the crawler finished HTML for free. From there the crawler runs its own two-phase crawl, same shape as `QuotesAuthorsCrawler` below:

1. **Collect** (`_collect_book_urls`, pure/no I/O): parses the already-rendered listing page's book cards for each book's detail-page URL, capped by `TEST_MODE_JOB_LIMIT`.
2. **Visit** (`run_pages_with_restart`): visits each book's detail page in batches, restarting Chromium between batches. For each page, structured fields (title, price, availability, rating) are parsed directly with BeautifulSoup, and Crawl4AI — scoped via `css_selector="#product_description ~ p"` — converts *only* the freeform "Product Description" paragraph to Markdown, skipping the product-info table and page chrome entirely. Results stream out through the queue exactly like the author bios below.

### `QuotesAuthorsCrawler` — quotes.toscrape.com (fully self-managed)

`requires_prerendered_html()` returns `False` — this crawler manages its own Playwright session end-to-end, in two phases:

1. **Collect** (`_collect_author_urls_in_thread`): walks `/page/N/` pagination via `crawlers/pagination.py`, gathering every unique author bio URL referenced by a quote's "(about)" link. Pagination is always followed to completion; only *collection* stops once `TEST_MODE_JOB_LIMIT` is hit.
2. **Visit** (`run_pages_with_restart`, from `crawlers/click_through_base.py`): visits each author URL in batches of `BROWSER_RESTART_AFTER_PAGES`, restarting Chromium between batches. Each batch's `(url, html)` pairs go through Crawl4AI (`AsyncHTTPCrawlerStrategy` + a `raw:` pseudo-URL, so no second browser is spawned) to convert the whole bio into Markdown, then get pushed onto an `asyncio.Queue` via `loop.call_soon_threadsafe` so `ExtractionService` can index each author as soon as it's ready — instead of waiting for the entire crawl to finish.

### Why streaming matters here

`run_pages_with_restart` never holds more than one batch's worth of `(url, html)` pairs in memory: each batch's raw HTML is converted, pushed onto the queue, then explicitly freed (`del chunk; gc.collect()`) before the next batch's browser session even opens. `ExtractionService` drains that queue one item at a time — indexing (or, for the batch runner, writing to disk) as each item arrives rather than after the whole crawl finishes. For a two-book demo this is invisible; at the batch runner's actual production scale it's the difference between flat memory usage and a multi-GB accumulation that gets OOM-killed halfway through a long crawl.

This is the pattern that matters most in an interview: it's the difference between "I called `requests.get` in a loop" and understanding why a long scraping job needs bounded memory, resumable batching, and a producer/consumer bridge between a worker thread and the async event loop.

---

## Why Playwright runs in its own thread with a fresh event loop

FastAPI under Uvicorn defaults to a `SelectorEventLoop`. On Windows, `SelectorEventLoop` cannot spawn subprocesses — and Playwright launching Chromium *is* a subprocess spawn. `core/browser.py:render_page_in_thread` (and the equivalent in `click_through_base.py`) is called via `asyncio.to_thread(...)`, and inside that worker thread it creates a brand-new `asyncio.ProactorEventLoop`, which *can* spawn subprocesses, runs the Playwright session on it, and tears it down. FastAPI's own loop never touches Playwright directly.

This is a Windows-hosting-specific problem — on Linux, Uvicorn's default loop can spawn subprocesses fine — but it's a good illustration of understanding *why* an async framework's event loop choice constrains what you can call synchronously inside it, not just copying a workaround.

---

## Getting started

Two ways to run this: entirely in Docker (nothing but Docker needed), or locally with a Python virtualenv.

### Option A — Run entirely in Docker (zero setup)

```bash
docker compose up --build
```

This builds the app image (Python 3.11-slim + `playwright install --with-deps chromium`, so Chromium and every OS-level library it needs are installed inside the container at build time) and starts it alongside an Elasticsearch container — no local Python, Playwright, or Elasticsearch install required. `app` waits for `elasticsearch` to pass its healthcheck before starting.

| Service | Host port | Notes |
|---|---|---|
| `app` | `9000` | Browse to `http://localhost:9000` — not `http://0.0.0.0:9000`. The container binds `0.0.0.0` internally so Docker's port mapping can reach it, but `0.0.0.0` isn't a browsable address from the host. |
| `elasticsearch` | `9201` | Remapped off the default `9200` so it doesn't clash with an Elasticsearch already running on the host; the `app` container still reaches it internally as `elasticsearch:9200` over Docker's network |

Open `http://localhost:9000/` for the dashboard, or `http://localhost:9000/docs` for Swagger UI.

```bash
docker compose down          # stop and remove both containers
```

### Option B — Run locally with a virtualenv

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
playwright install chromium

copy .env.example .env         # optional — the app runs fine with ES unset
```

### Run the API

```bash
uvicorn main:app --reload
```

| Endpoint | Description |
|---|---|
| `POST /extract` | `{"url": "https://books.toscrape.com/"}` or `{"url": "https://quotes.toscrape.com/"}` — dispatches to the registered crawler |
| `POST /scrape` | `{"url": "<any url>"}` — generic Playwright + Crawl4AI, no dispatch |
| `GET /health` | `{"status": "ok", "elasticsearch": "connected"\|"disconnected", ...}` |
| `GET /` | Search dashboard (static, see below) |
| `GET /domain-browser.html` | Browse Domains page |
| `GET /docs` | Swagger UI |

### The dashboard

`api/dashboard_router.py` is a **read-only** layer over the same Elasticsearch index the crawlers write to — it never calls `.upsert()`, only `.search()` / `.count()`. In a real deployment this would be its own service reading a shared index (the way a production job board separates the ingestion pipeline from the search UI); it's folded into one app here to keep the demo to a single `uvicorn` process.

| Page | What it does |
|---|---|
| `/` — Search | Keyword search (`extractedContent` full-text + `sourceRefid` wildcard) with an optional domain filter, paginated results, a **Clear** button to reset both, and a **Today's Report** modal |
| `/domain-browser.html` — Browse Domains | Card grid of the registered domains with live item counts; domains with items sort to the top, empty domains are greyed out and disabled; clicking a card drills into that domain's paginated item list |
| Today's Report (both pages) | `GET /api/dashboard/report/today` — per-domain totals, items indexed today, and items re-indexed (updated) today; domains with zero items are omitted |

Run `python services/batch_runner.py` (or a few `POST /extract` calls) against a real Elasticsearch instance first if you want the dashboard to show actual data — with no ES configured it still renders correctly, just with everything at zero.

### Run the batch runner

```bash
python services/batch_runner.py
```

Crawls every URL in `services/batch_runner.py::URLS` sequentially, streaming results to `batch_output/items_<timestamp>.json` and a summary to `batch_output/report_<timestamp>.txt`.

### Run only Elasticsearch in Docker, app locally (optional)

If you're running the app locally (Option B) but still want a real Elasticsearch to index into, without also containerizing the app:

```bash
docker compose up -d elasticsearch
# then set ELASTICSEARCH_HOST=http://localhost:9201 in .env (security is disabled in docker-compose.yml, so username/password are ignored)
```

Without it, `indexer=None` throughout — extraction and scraping both still work; `indexed: false` just shows up in every response.

### Run the tests

```bash
pytest
```

Crawler and text-cleaning tests run against inline HTML fixtures (no live network calls). API tests mock `ExtractionService`/`ScrapeService` via FastAPI's `dependency_overrides`.

---

## Adding a new crawler

1. `crawlers/<site>_crawler.py` extending `BaseCrawler`, implementing `extract()`.
2. Override `requires_prerendered_html()` → `False` if the crawler needs its own Playwright session (click-through, pagination).
3. For click-through crawlers: a `_collect_*_urls_in_thread()` helper (optionally via `crawlers/pagination.py`) + `stream_extract()` using the queue-bridge pattern in `QuotesAuthorsCrawler` + `run_pages_with_restart` from `click_through_base.py`.
4. Register the domain in `dispatcher/crawler_dispatcher.py::DOMAIN_REGISTRY`.
5. Add the canonical URL to `services/batch_runner.py::URLS`.
6. Add a test in `tests/test_crawlers/`.

No changes to routing, services, or the indexer required.

---

## Environment variables

See `.env.example`. Elasticsearch settings are the only ones that are genuinely optional — leaving `ELASTICSEARCH_HOST` blank runs the whole app with indexing disabled rather than failing startup.
