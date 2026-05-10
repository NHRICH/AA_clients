# Addis Ababa Venue Scraper — Brave Search API

Scrapes restaurants, cafes, bakeries, bars, and nightclubs in Addis Ababa
using the **Brave Search API** (2,000 free queries/month).

## Structure

```
Adiss Brave Search/
├── directives/
│   └── scrape_addis_brave.md      # SOP / directive
├── execution/
│   └── scrape_brave.py            # Deterministic scraping script
├── output/
│   ├── restaurants_addis_brave.csv / .json
│   ├── cafes_addis_brave.csv / .json
│   ├── bakeries_addis_brave.csv / .json
│   ├── bars_addis_brave.csv / .json
│   └── nightclubs_addis_brave.csv / .json
├── .env                           # API key (never committed)
├── .env.example                   # Template
├── .gitignore
└── README.md
```

> **Shared venv**: This project reuses the virtual environment from the parent
> project at `..\venv\`. No separate installation needed.

## Setup

### 1. Get a free Brave Search API key
→ [https://brave.com/search/api/](https://brave.com/search/api/)
Free Data for Independents plan: **2,000 queries/month**

### 2. Create `.env` in this folder
```
BRAVE_API_KEY=your_key_here
```

### 3. Run the scraper (uses parent venv)
```powershell
# From this folder:
..\venv\Scripts\python.exe execution\scrape_brave.py

# Specific types only:
..\venv\Scripts\python.exe execution\scrape_brave.py --types bars nightclubs

# Full refresh:
..\venv\Scripts\python.exe execution\scrape_brave.py --refresh
```

## Output Fields

| Field         | Description                                    |
|---------------|------------------------------------------------|
| name          | Venue name (from page title)                   |
| url           | Venue website URL                              |
| description   | Search snippet                                 |
| category      | Inferred from search type                      |
| neighborhood  | Sub-city searched                              |
| address       | Extracted from snippet (regex)                 |
| phone         | Extracted from snippet (regex)                 |
| rating        | Extracted if present in snippet                |
| links_on_site | All links found on the venue's homepage        |
| query_type    | e.g. "bars", "nightclubs"                      |
| scraped_at    | UTC timestamp                                  |

## Why Brave over SerpApi

| | SerpApi Free | Brave Free |
|---|---|---|
| Queries/month | 100 | **2,000** |
| Local POI data | ✅ | ✅ (paid) / Web search (free) |
| Price beyond free | $50/mo | $3/1000 queries |

## Notes
- `venv/` and `.env` are **never committed** to git
- Aggregator sites (TripAdvisor, Yelp, Facebook etc.) are automatically filtered out
- Script is crash-safe: checkpoints after every neighbourhood
- Re-runs append only new results (URL-based deduplication)
