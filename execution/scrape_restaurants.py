"""
execution/scrape_restaurants.py
--------------------------------
Unified scraper for food & nightlife venues in Addis Ababa via SerpApi.
Supports: restaurants, cafes, bakeries, bars, nightclubs (run one or all).

Key optimisations vs v1:
  - Parallel website scraping with ThreadPoolExecutor (8 workers) → ~8x faster
  - Per-type output files so datasets stay separate and clean
  - Checkpoint save after every neighbourhood (crash-safe)
  - Skip website scraping for already-scraped rows on resume

Output files (output/ directory):
  restaurants_addis_abeba.csv / .json
  cafes_addis_abeba.csv / .json
  bakeries_addis_abeba.csv / .json
  bars_addis_abeba.csv / .json
  nightclubs_addis_abeba.csv / .json

Usage:
  # All types (default)
  .\\venv\\Scripts\\python.exe execution\\scrape_restaurants.py

  # Specific types only
  .\\venv\\Scripts\\python.exe execution\\scrape_restaurants.py --types cafes bars

  # Force re-fetch everything
  .\\venv\\Scripts\\python.exe execution\\scrape_restaurants.py --types cafes --refresh

Requirements (installed via venv):
  requests, beautifulsoup4, python-dotenv, pandas, lxml
"""

import os
import sys
import time
import warnings
import argparse
import requests
import pandas as pd
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from dotenv import load_dotenv

# Suppress benign BS4 warning for XML documents parsed as HTML
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
SERPAPI_URL = "https://serpapi.com/search.json"
OUTPUT_DIR  = os.path.join(os.path.dirname(__file__), "..", "output")

# All sub-cities/neighbourhoods for full Addis Ababa coverage
NEIGHBORHOODS = [
    "Bole", "Kirkos", "Yeka", "Lideta", "Gulele",
    "Arada", "Kolfe Keranio", "Akaky Kaliti", "Nifas Silk Lafto", "Lemi Kura"
]

# Entity type → (search query template, output filename stem)
ENTITY_TYPES: dict[str, tuple[str, str]] = {
    "restaurants": ("{type} in {hood}, Addis Ababa, Ethiopia", "restaurants_addis_abeba"),
    "cafes":       ("{type} in {hood}, Addis Ababa, Ethiopia", "cafes_addis_abeba"),
    "bakeries":    ("{type} in {hood}, Addis Ababa, Ethiopia", "bakeries_addis_abeba"),
    "bars":        ("{type} in {hood}, Addis Ababa, Ethiopia", "bars_addis_abeba"),
    "nightclubs":  ("{type} in {hood}, Addis Ababa, Ethiopia", "nightclubs_addis_abeba"),
}

REQUEST_TIMEOUT = 8    # seconds — per website scrape attempt
POLITE_DELAY    = 1.2  # seconds — between SerpApi calls (rate-limit safety)
WORKERS         = 8    # parallel threads for website scraping

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_neighborhood(address: str) -> str:
    """Return the second-to-last comma segment; falls back to first segment."""
    if not address:
        return ""
    parts = [p.strip() for p in address.split(",")]
    return parts[-2] if len(parts) >= 2 else parts[0]


def fetch_serpapi_page(query: str, start: int = 0) -> dict:
    """Fetch one page of Google Maps local results from SerpApi."""
    params = {
        "engine":  "google_maps",
        "q":       query,
        "type":    "search",
        "start":   start,
        "api_key": SERPAPI_KEY,
    }
    resp = requests.get(SERPAPI_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def parse_place(place: dict) -> dict:
    """Normalise one SerpApi local_result entry into our unified schema."""
    return {
        "name":            place.get("title", ""),
        "category":        ", ".join(place.get("types", [])) or place.get("type", ""),
        "neighborhood":    _safe_neighborhood(place.get("address", "")),
        "full_address":    place.get("address", ""),
        "rating":          place.get("rating"),
        "review_count":    place.get("reviews"),
        "phone":           place.get("phone", ""),
        "website":         place.get("website", ""),
        "links_on_site":   None,   # populated in Phase 2
        "google_maps_url": place.get("link", ""),
        "scraped_at":      datetime.now(timezone.utc).isoformat(),
    }


def scrape_website_links(row_data: tuple) -> tuple[int, str]:
    """
    Worker function: given (index, url), return (index, pipe-joined links string).
    Designed to run in a ThreadPoolExecutor.
    """
    idx, url = row_data
    if not url or pd.isna(url):
        return idx, ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AddisVenueBot/2.0)"}
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        links: set[str] = set()
        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if href.startswith("http"):
                links.add(href)
            elif href.startswith("/"):
                links.add(urljoin(base, href))
        return idx, " | ".join(sorted(links))
    except Exception as exc:
        print(f"    [SKIP] {url} → {type(exc).__name__}: {exc}")
        return idx, ""


# ---------------------------------------------------------------------------
# Phase 1 — Fetch listings from Google Maps via SerpApi
# ---------------------------------------------------------------------------

def fetch_listings(entity_type: str, csv_path: str, refresh: bool) -> tuple[list, set]:
    """
    Paginate through all SerpApi results for a given entity type.
    Returns (records list, set of already-known names) — crash-safe via checkpoint.
    """
    existing_names: set[str] = set()
    records: list[dict] = []

    if not refresh and os.path.exists(csv_path):
        existing_df = pd.read_csv(csv_path)
        existing_names = set(existing_df["name"].dropna().str.strip())
        records = existing_df.to_dict("records")
        print(f"[RESUME] Loaded {len(records)} existing {entity_type} records.")

    for hood in NEIGHBORHOODS:
        query = f"{entity_type} in {hood}, Addis Ababa, Ethiopia"
        print(f"\n  [QUERY] {query}")
        start = 0

        while True:
            try:
                data = fetch_serpapi_page(query, start=start)
            except requests.HTTPError as exc:
                print(f"    [HTTP ERROR] {exc} — skipping rest of {hood}")
                break

            places = data.get("local_results", [])
            if not places:
                print(f"    No more results at offset {start}.")
                break

            new_count = 0
            for place in places:
                parsed = parse_place(place)
                name = parsed["name"].strip()
                if not name or name in existing_names:
                    continue
                existing_names.add(name)
                records.append(parsed)
                new_count += 1

            print(f"    offset={start:>3} → {len(places):>2} results, {new_count} new")

            if data.get("serpapi_pagination", {}).get("next"):
                start += 20
                time.sleep(POLITE_DELAY)
            else:
                break

            time.sleep(POLITE_DELAY)

        # Checkpoint after every neighbourhood
        _checkpoint(records, csv_path)

    return records, existing_names


# ---------------------------------------------------------------------------
# Phase 2 — Parallel website link scraping
# ---------------------------------------------------------------------------

def enrich_with_website_links(df: pd.DataFrame) -> pd.DataFrame:
    """
    Scrape homepage links for all rows that have a website but no links yet.
    Uses ThreadPoolExecutor for parallel I/O — ~8x faster than sequential.
    """
    # Rows that still need scraping
    needs_scrape = [
        (idx, row["website"])
        for idx, row in df.iterrows()
        if (
            row.get("website")
            and pd.notna(row.get("website"))
            and str(row.get("website")).startswith("http")
            and (not row.get("links_on_site") or pd.isna(row.get("links_on_site")))
        )
    ]

    total = len(df)
    pending = len(needs_scrape)
    print(f"\n[PHASE 2] Parallel website scraping — {pending} sites to visit "
          f"({total - pending} already done / no website) | {WORKERS} workers")

    if not needs_scrape:
        print("  Nothing to scrape.")
        return df

    completed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(scrape_website_links, item): item for item in needs_scrape}
        for future in as_completed(futures):
            idx, links_str = future.result()
            df.at[idx, "links_on_site"] = links_str
            completed += 1
            if completed % 50 == 0 or completed == pending:
                print(f"  … {completed}/{pending} sites scraped")

    return df


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _checkpoint(records: list, csv_path: str) -> None:
    """Intermediate save — overwrites the CSV so a crash loses at most 1 neighbourhood."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pd.DataFrame(records).to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"  [CHECKPOINT] {len(records)} records → {os.path.basename(csv_path)}")


def save_final(df: pd.DataFrame, csv_path: str, json_path: str) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_json(json_path, orient="records", force_ascii=False, indent=2)
    print(f"\n[SAVED] {len(df):>5} records → {os.path.basename(csv_path)}")
    print(f"[SAVED]          JSON → {os.path.basename(json_path)}")


def print_summary(entity_type: str, df: pd.DataFrame) -> None:
    print(f"\n{'='*50}")
    print(f"  {entity_type.upper()} SUMMARY")
    print(f"{'='*50}")
    print(f"  Total records  : {len(df)}")
    if "rating" in df.columns:
        print(f"  With rating    : {df['rating'].notna().sum()}")
    if "website" in df.columns:
        has_site = df["website"].notna() & df["website"].str.startswith("http", na=False)
        print(f"  With website   : {has_site.sum()}")
    if "category" in df.columns:
        cats = df["category"].dropna().str.split(",").explode().str.strip()
        top = cats.value_counts().head(8)
        print(f"  Top categories :")
        for cat, cnt in top.items():
            print(f"    {cnt:>4}  {cat}")
    print()


# ---------------------------------------------------------------------------
# Main pipeline — one entity type at a time
# ---------------------------------------------------------------------------

def run_for_type(entity_type: str, refresh: bool) -> None:
    _, file_stem = ENTITY_TYPES[entity_type]
    csv_path  = os.path.join(OUTPUT_DIR, f"{file_stem}.csv")
    json_path = os.path.join(OUTPUT_DIR, f"{file_stem}.json")

    print(f"\n{'#'*60}")
    print(f"#  SCRAPING: {entity_type.upper()}")
    print(f"{'#'*60}")

    # Phase 1 — listings
    records, _ = fetch_listings(entity_type, csv_path, refresh)
    df = pd.DataFrame(records)

    if df.empty:
        print(f"  [WARN] No records found for {entity_type}. Skipping.")
        return

    # Phase 2 — enrich with website links
    df = enrich_with_website_links(df)

    # Final save
    save_final(df, csv_path, json_path)
    print_summary(entity_type, df)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape food & nightlife venues in Addis Ababa via SerpApi"
    )
    parser.add_argument(
        "--types",
        nargs="+",
        choices=list(ENTITY_TYPES.keys()),
        default=list(ENTITY_TYPES.keys()),
        metavar="TYPE",
        help=(
            "Which entity types to scrape. "
            f"Options: {', '.join(ENTITY_TYPES.keys())}. "
            "Default: all types."
        ),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore existing data and re-fetch from scratch for the selected types.",
    )
    args = parser.parse_args()

    if not SERPAPI_KEY:
        print("[ERROR] SERPAPI_KEY not set in .env — cannot continue.")
        sys.exit(1)

    # Skip restaurants if already done (unless explicitly requested or --refresh)
    selected = args.types
    print(f"[START] Types to scrape: {', '.join(selected)}")
    print(f"[START] Refresh mode   : {args.refresh}")

    for etype in selected:
        run_for_type(etype, refresh=args.refresh)

    print("\n[DONE] All requested types scraped successfully.")
