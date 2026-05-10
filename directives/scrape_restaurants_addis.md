# Directive: Scrape Restaurants in Addis Ababa

## Goal
Collect a comprehensive, structured dataset of restaurants in Addis Ababa, Ethiopia.
Each record must capture: name, category/cuisine, location/neighborhood, rating, phone,
website URL, and any social/menu links found on the restaurant's own site.

## Data Fields (per restaurant)

| Field            | Source                          | Notes                                  |
|------------------|---------------------------------|----------------------------------------|
| name             | Google Maps / listing           | Full business name                     |
| category         | Google Maps / listing           | Cuisine type (e.g. Ethiopian, Italian) |
| neighborhood     | Google Maps / listing           | Sub-city or area within Addis          |
| full_address     | Google Maps / listing           | Street-level address if available      |
| rating           | Google Maps / listing           | Float 1.0–5.0; None if unavailable     |
| review_count     | Google Maps / listing           | Integer                                |
| phone            | Google Maps / listing           | Local or international format          |
| website          | Google Maps / listing           | Direct URL from listing                |
| links_on_site    | Restaurant's own website        | All <a href> links found on homepage   |
| google_maps_url  | Google Maps                     | Direct link to the place               |
| scraped_at       | Script timestamp                | ISO-8601 UTC                           |

## Data Source Strategy

### Primary: Google Maps (via SerpApi or googlemaps Places API)
- Query: `restaurants in Addis Ababa`
- Paginate through all results (up to API limits)
- Use the `places` endpoint or `local_results` from SerpApi

### Fallback: Yelp / Foursquare public pages
- Only if Google Maps quota is exceeded

### Secondary (per restaurant): Scrape own website
- Visit `website` field URL with `requests` + `BeautifulSoup`
- Extract all unique `<a href>` values from the homepage
- Skip if `website` is None or times out after 5 seconds

## API Keys Required
- `SERPAPI_KEY` — stored in `.env` (get free key at https://serpapi.com)
- `GOOGLE_MAPS_API_KEY` — optional fallback, stored in `.env`

## Output
- **Single file**: `output/restaurants_addis_abeba.csv`
- Never create timestamped copies; overwrite/append to the single file
- Also produce `output/restaurants_addis_abeba.json` for downstream use

## Script
- `execution/scrape_restaurants.py`
- Uses venv at `./venv/`

## Edge Cases & Known Issues
- SerpApi free tier: 100 searches/month — use pagination wisely (max 20 results/page)
- Google Maps Places API: charges after $200 free monthly credit
- Some restaurants have no website → `website` and `links_on_site` will be None/empty
- Websites may block bots → catch connection errors gracefully, log skip
- Addis Ababa sub-cities: Bole, Kirkos, Yeka, Lideta, Gulele, Arada, Kolfe, Akaky, Nifas Silk, Lemi
- Run with neighborhoods as sub-queries to maximize coverage

## Execution
```powershell
# First run — installs deps and runs
.\venv\Scripts\python.exe execution\scrape_restaurants.py

# Re-run to refresh data
.\venv\Scripts\python.exe execution\scrape_restaurants.py --refresh
```

## Updates / Learnings
- 2026-05-10: Initial directive created. SerpApi chosen as primary source.
