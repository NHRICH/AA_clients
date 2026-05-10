# Directive: Scrape Addis Ababa Venues via Brave Search API

## Goal
Collect structured venue data (restaurants, cafes, bakeries, bars, nightclubs)
in Addis Ababa using the **Brave Search API** — which provides 2,000 free
queries/month, far exceeding the SerpApi free tier used previously.

## Why Brave Search API
| Feature              | SerpApi Free | Brave Free   |
|----------------------|-------------|--------------|
| Searches/month       | 100          | 2,000        |
| Cost beyond free     | $50+/mo      | $3/1000 req  |
| Local/POI endpoint   | Yes          | Yes (Web Search + Local Results) |
| Rate limit           | Low          | Generous     |

## API Used
- **Endpoint**: `https://api.search.brave.com/res/v1/web/search`
- **Docs**: https://api.search.brave.com/app/documentation/web-search
- **Auth**: `X-Subscription-Token: <BRAVE_API_KEY>` header
- **Key fields**: `web.results`, each result has `title`, `url`, `description`, `extra_snippets`

## Supplemental: Local POI (if available on plan)
- **Endpoint**: `https://api.search.brave.com/res/v1/local/pois`
- Returns structured business data: name, address, phone, rating, hours
- Available on paid plans — falls back to web search on free tier

## Strategy
1. **Query pattern**: `"{type} in {neighborhood} Addis Ababa Ethiopia"`
2. **Pagination**: `offset` param, max 20 results/page, up to 10 pages
3. **Types**: restaurants, cafes, bakeries, bars, nightclubs
4. **Neighborhoods**: all 10 Addis sub-cities
5. **Phase 2**: Visit each website URL → extract homepage links (parallel, 8 workers)

## Virtual Environment
**Reuse existing venv** from parent project:
```
VENV = ..\venv\Scripts\python.exe
```
No new installation needed — all required packages already installed.

## Output Files (output/ directory)
- `restaurants_addis_brave.csv` + `.json`
- `cafes_addis_brave.csv` + `.json`
- `bakeries_addis_brave.csv` + `.json`
- `bars_addis_brave.csv` + `.json`
- `nightclubs_addis_brave.csv` + `.json`

## Data Fields
| Field           | Source                    |
|-----------------|---------------------------|
| name            | Brave result title        |
| url             | Brave result URL          |
| description     | Brave snippet             |
| category        | Inferred from query type  |
| neighborhood    | From query                |
| address         | Extracted from snippet    |
| phone           | Extracted from snippet    |
| rating          | Extracted if present      |
| links_on_site   | Scraped from URL homepage |
| query_type      | e.g. "cafes"              |
| scraped_at      | ISO-8601 UTC timestamp    |

## Execution
```powershell
# All types (uses parent venv)
..\venv\Scripts\python.exe execution\scrape_brave.py

# Specific types
..\venv\Scripts\python.exe execution\scrape_brave.py --types bars nightclubs

# Full refresh
..\venv\Scripts\python.exe execution\scrape_brave.py --types restaurants --refresh
```

## Edge Cases & Learnings
- Brave free tier: 2,000 queries/month — budget ~200 queries per type (10 hoods × up to 20 pages)
- Rate limit: 1 request/second recommended to avoid 429s
- Web search results are less structured than Maps API — use regex to extract phone/address from snippets
- Some results will be aggregator sites (TripAdvisor, Yelp) — deduplicate by domain

## Updates
- 2026-05-10: Directive created. Brave API chosen as primary source for bars/nightclubs.
