# Addis Ababa Restaurant Scraper

A 3-layer data pipeline that collects comprehensive restaurant data for Addis Ababa,
including category, location, rating, website, and all links found on each restaurant's site.

## Directory Structure

```
Adiss Abbeba clients/
├── directives/
│   └── scrape_restaurants_addis.md   # SOP / directive
├── execution/
│   └── scrape_restaurants.py         # Deterministic scraping script
├── output/
│   ├── restaurants_addis_abeba.csv   # Final deliverable (CSV)
│   └── restaurants_addis_abeba.json  # Final deliverable (JSON)
├── venv/                             # Python virtual env (ignored by git)
├── .env                              # API keys (ignored by git)
├── .gitignore
└── README.md
```

## Setup

### 1. Get a free SerpApi key
Sign up at https://serpapi.com — free tier gives 100 searches/month.

### 2. Create `.env`
```
SERPAPI_KEY=your_key_here
```

### 3. Create virtual environment & install deps
```powershell
python -m venv venv
.\venv\Scripts\pip install requests beautifulsoup4 python-dotenv pandas lxml
```

### 4. Run the scraper
```powershell
# Normal run (appends new restaurants, skips already-scraped ones)
.\venv\Scripts\python.exe execution\scrape_restaurants.py

# Full refresh (re-fetches everything)
.\venv\Scripts\python.exe execution\scrape_restaurants.py --refresh
```

## Output Fields

| Field           | Description                                      |
|-----------------|--------------------------------------------------|
| name            | Restaurant name                                  |
| category        | Cuisine / place type                             |
| neighborhood    | Sub-city within Addis Ababa                      |
| full_address    | Street address                                   |
| rating          | Google Maps rating (1.0–5.0)                     |
| review_count    | Number of reviews                                |
| phone           | Contact number                                   |
| website         | Official website URL                             |
| links_on_site   | All links found on the restaurant's homepage     |
| google_maps_url | Direct Google Maps link                          |
| scraped_at      | Timestamp of collection (UTC)                    |

## Notes
- `venv/`, `.env` are **never committed** to git
- Output files are always overwritten (single file protocol)
- The scraper is polite: 1.2s delay between API calls, 0.5s between site scrapes
