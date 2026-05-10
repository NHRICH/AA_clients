# Directive: Scrape Addis Ababa Supermarkets via Brave Search API

## Goal
Collect comprehensive, structured data of supermarkets, mini-marts, and 
grocery stores in Addis Ababa.
Data must include: location, rating, map links, websites, and any social media links.

## Data Source Strategy
We use the **Brave Search API** for deep queries due to its generous free tier (2,000 queries/month).
- **Queries:** `supermarkets in {neighborhood} Addis Ababa Ethiopia`
- **Sub-cities:** Bole, Kirkos, Yeka, Lideta, Gulele, Arada, Kolfe Keranio, Akaky Kaliti, Nifas Silk Lafto, Lemi Kura.

## Extraction Strategy
1. **Brave Web Search API** to fetch results page by page (pages 0-9).
2. **Regex Parsing** to extract phone numbers and ratings from the description snippet.
3. **Map Link Generation:** We dynamically generate a Google Maps search URL from the parsed name and neighborhood to fulfill the map requirement.
4. **Website Deep Crawl (Phase 2):** We visit each extracted `url` (using 8 parallel workers) to extract `links_on_site`. This fetches internal links and **social media profiles** (Instagram, Facebook, LinkedIn, Twitter).

## Target Fields
| Field           | Source                                           |
|-----------------|--------------------------------------------------|
| name            | Brave API Title                                  |
| url             | Brave API Result URL                             |
| description     | Snippet from search                              |
| category        | Inferred ("Supermarket")                         |
| neighborhood    | Search query parameter                           |
| address         | Extracted from description                       |
| phone           | Regex `\+?251...` from description               |
| rating          | Regex from description                           |
| google_maps_url | Generated: `https://www.google.com/maps/search/?api=1&query=...` |
| links_on_site   | Extracted via parallel website crawl (Phase 2)   |
| scraped_at      | Timestamp                                        |

## Execution
```powershell
# Copy the `.env` file from the Brave Search project or use the same key
copy ..\Adiss_Brave_Search\.env .\.env

# Run using the parent virtual environment
..\venv\Scripts\python.exe execution\scrape_supermarkets.py
```

## Resilience & Deduplication
- **Checkpoints:** Saves results progressively after each neighborhood to `output/supermarkets_addis_abeba.csv` to prevent data loss.
- **De-duping:** Avoids processing the same `url` twice. Filters out aggregator sites like Yelp, Facebook directly (but records social media links from actual websites).

## Updates
- 2026-05-10: Created dedicated directive for supermarkets. Added Google Maps link generator.
