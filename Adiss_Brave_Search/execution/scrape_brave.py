"""
execution/scrape_brave.py
--------------------------
Scrapes food & nightlife venues in Addis Ababa using the Brave Search API.
More generous free tier than SerpApi: 2,000 queries/month.

Supports: restaurants, cafes, bakeries, bars, nightclubs

Optimisations:
  - Parallel website scraping (ThreadPoolExecutor, 8 workers)
  - Per-type output files (separate CSV + JSON per category)
  - Checkpoint saves after every neighbourhood (crash-safe)
  - Resume support — re-run safely, already-scraped rows skipped

Virtual env: uses the shared venv from the parent project (..\venv\)

Usage:
  # All types
  ..\venv\Scripts\python.exe execution\scrape_brave.py

  # Specific types only
  ..\venv\Scripts\python.exe execution\scrape_brave.py --types bars nightclubs

  # Force re-fetch
  ..\venv\Scripts\python.exe execution\scrape_brave.py --types bars --refresh

Requirements (all installed in shared venv):
  requests, beautifulsoup4, python-dotenv, pandas, lxml
"""

import os
import re
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

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Load .env from THIS project folder (not parent)
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")   # Adiss Brave Search/
load_dotenv(dotenv_path=os.path.join(_ROOT, ".env"))

BRAVE_API_KEY  = os.getenv("BRAVE_API_KEY", "")
BRAVE_WEB_URL  = "https://api.search.brave.com/res/v1/web/search"
BRAVE_LOCAL_URL = "https://api.search.brave.com/res/v1/local/pois"

OUTPUT_DIR = os.path.join(_ROOT, "output")

NEIGHBORHOODS = [
    "Bole", "Kirkos", "Yeka", "Lideta", "Gulele",
    "Arada", "Kolfe Keranio", "Akaky Kaliti", "Nifas Silk Lafto", "Lemi Kura"
]

# Entity type → output filename stem
ENTITY_TYPES: dict[str, str] = {
    "restaurants": "restaurants_addis_brave",
    "cafes":       "cafes_addis_brave",
    "bakeries":    "bakeries_addis_brave",
    "bars":        "bars_addis_brave",
    "nightclubs":  "nightclubs_addis_brave",
}

REQUEST_TIMEOUT = 8    # seconds — per website visit
POLITE_DELAY    = 1.1  # seconds — between Brave API calls
WORKERS         = 8    # parallel threads for Phase 2 website scraping
RESULTS_PER_PAGE = 20  # Brave API max per request
MAX_PAGES        = 10  # max pagination depth per neighbourhood

# Regex patterns for extracting structured data from search snippets
_PHONE_RE   = re.compile(r"(\+?251[\s\-]?\d[\d\s\-]{6,}|\+?0\d{9})")
_RATING_RE  = re.compile(r"(\d\.\d)\s*(?:out of 5|stars?|★|/5)", re.I)
_ADDRESS_RE = re.compile(
    r"(?:address|location)[:\s]+([^,\n]{5,60}(?:,\s*Addis Ababa)?)", re.I
)

# Domains that are aggregators — we skip their URLs as "venue websites"
_AGGREGATOR_DOMAINS = {
    "tripadvisor.com", "yelp.com", "foursquare.com", "zomato.com",
    "google.com", "facebook.com", "instagram.com", "twitter.com",
    "booking.com", "expedia.com", "hotels.com", "maps.apple.com",
}

# ---------------------------------------------------------------------------
# Brave API helpers
# ---------------------------------------------------------------------------

def _brave_headers() -> dict:
    return {
        "Accept":                "application/json",
        "Accept-Encoding":       "gzip",
        "X-Subscription-Token":  BRAVE_API_KEY,
    }


def fetch_brave_web(query: str, offset: int = 0) -> dict:
    """Fetch one page of Brave web search results."""
    params = {
        "q":      query,
        "count":  RESULTS_PER_PAGE,
        "offset": offset,
    }
    resp = requests.get(
        BRAVE_WEB_URL, headers=_brave_headers(), params=params, timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def _is_aggregator(url: str) -> bool:
    try:
        domain = urlparse(url).netloc.lower().lstrip("www.")
        return any(agg in domain for agg in _AGGREGATOR_DOMAINS)
    except Exception:
        return False


def _extract_phone(text: str) -> str:
    m = _PHONE_RE.search(text or "")
    return m.group(0).strip() if m else ""


def _extract_rating(text: str) -> float | None:
    m = _RATING_RE.search(text or "")
    return float(m.group(1)) if m else None


def _extract_address(text: str) -> str:
    m = _ADDRESS_RE.search(text or "")
    return m.group(1).strip() if m else ""


def parse_brave_result(result: dict, query_type: str, neighborhood: str) -> dict | None:
    """
    Convert one Brave web search result into our venue schema.
    Returns None if the result looks like an aggregator listing.
    """
    url  = result.get("url", "")
    if _is_aggregator(url):
        return None

    title       = result.get("title", "").strip()
    description = result.get("description", "")
    # extra_snippets is a list of additional text snippets Brave returns
    all_text    = " ".join([description] + result.get("extra_snippets", []))

    return {
        "name":          title,
        "url":           url,
        "description":   description,
        "category":      query_type.rstrip("s").capitalize(),  # "Cafe", "Bar" etc.
        "neighborhood":  neighborhood,
        "address":       _extract_address(all_text),
        "phone":         _extract_phone(all_text),
        "rating":        _extract_rating(all_text),
        "links_on_site": None,  # populated in Phase 2
        "query_type":    query_type,
        "scraped_at":    datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Phase 2 — parallel website link extraction
# ---------------------------------------------------------------------------

def scrape_website_links(row_data: tuple) -> tuple[int, str]:
    """Worker: (index, url) → (index, pipe-joined links). Runs in ThreadPool."""
    idx, url = row_data
    if not url or pd.isna(url):
        return idx, ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AddisVenueBot/2.0)"}
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        links: set[str] = set()
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if href.startswith("http"):
                links.add(href)
            elif href.startswith("/"):
                links.add(urljoin(base, href))
        return idx, " | ".join(sorted(links))
    except Exception as exc:
        print(f"    [SKIP] {url} → {type(exc).__name__}")
        return idx, ""


def enrich_with_links(df: pd.DataFrame) -> pd.DataFrame:
    """Parallel Phase 2: visit each venue URL and harvest homepage links."""
    needs = [
        (idx, row["url"])
        for idx, row in df.iterrows()
        if (
            row.get("url")
            and pd.notna(row.get("url"))
            and str(row.get("url")).startswith("http")
            and not _is_aggregator(str(row.get("url", "")))
            and (not row.get("links_on_site") or pd.isna(row.get("links_on_site")))
        )
    ]
    total, pending = len(df), len(needs)
    print(f"\n[PHASE 2] {pending} sites to visit ({total - pending} skipped) | {WORKERS} workers")

    if not needs:
        print("  Nothing to scrape.")
        return df

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as exe:
        futures = {exe.submit(scrape_website_links, item): item for item in needs}
        for future in as_completed(futures):
            idx, links_str = future.result()
            df.at[idx, "links_on_site"] = links_str
            done += 1
            if done % 50 == 0 or done == pending:
                print(f"  … {done}/{pending} scraped")
    return df


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _checkpoint(records: list, csv_path: str) -> None:
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
    print(f"\n{'='*52}")
    print(f"  {entity_type.upper()} — BRAVE SEARCH RESULTS")
    print(f"{'='*52}")
    print(f"  Total records  : {len(df)}")
    if "rating" in df.columns:
        print(f"  With rating    : {df['rating'].notna().sum()}")
    if "phone" in df.columns:
        has_phone = df["phone"].notna() & (df["phone"] != "")
        print(f"  With phone     : {has_phone.sum()}")
    if "url" in df.columns:
        has_url = df["url"].notna() & df["url"].str.startswith("http", na=False)
        print(f"  With website   : {has_url.sum()}")
    if "neighborhood" in df.columns:
        print("  By neighbourhood:")
        for hood, cnt in df["neighborhood"].value_counts().items():
            print(f"    {cnt:>4}  {hood}")
    print()


# ---------------------------------------------------------------------------
# Phase 1 — fetch listings via Brave web search
# ---------------------------------------------------------------------------

def fetch_listings(entity_type: str, csv_path: str, refresh: bool) -> list[dict]:
    records: list[dict] = []
    seen_urls: set[str] = set()

    if not refresh and os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
        try:
            existing = pd.read_csv(csv_path)
            seen_urls = set(existing["url"].dropna().str.strip())
            records = existing.to_dict("records")
            print(f"[RESUME] Loaded {len(records)} existing {entity_type} records.")
        except pd.errors.EmptyDataError:
            pass # File exists but is empty, skip loading

    for hood in NEIGHBORHOODS:
        query = f'{entity_type} in {hood} Addis Ababa Ethiopia'
        print(f"\n  [QUERY] {query}")

        for page in range(MAX_PAGES):
            offset = page
            try:
                data = fetch_brave_web(query, offset=offset)
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response else "?"
                print(f"    [HTTP {code}] {exc} — stopping {hood}")
                break
            except Exception as exc:
                print(f"    [ERROR] {exc} — stopping {hood}")
                break

            results = (data.get("web") or {}).get("results", [])
            if not results:
                print(f"    No more results at offset {offset}.")
                break

            new_count = 0
            for result in results:
                parsed = parse_brave_result(result, entity_type, hood)
                if parsed is None:
                    continue
                url = parsed["url"].strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                records.append(parsed)
                new_count += 1

            print(f"    offset={offset:>3} → {len(results):>2} results, {new_count} new")
            time.sleep(POLITE_DELAY)

            if len(results) < RESULTS_PER_PAGE:
                break  # last page

        _checkpoint(records, csv_path)

    return records


# ---------------------------------------------------------------------------
# Main pipeline — one entity type at a time
# ---------------------------------------------------------------------------

def run_for_type(entity_type: str, refresh: bool) -> None:
    file_stem = ENTITY_TYPES[entity_type]
    csv_path  = os.path.join(OUTPUT_DIR, f"{file_stem}.csv")
    json_path = os.path.join(OUTPUT_DIR, f"{file_stem}.json")

    print(f"\n{'#'*60}")
    print(f"#  BRAVE SCRAPING: {entity_type.upper()}")
    print(f"{'#'*60}")

    records = fetch_listings(entity_type, csv_path, refresh)
    df = pd.DataFrame(records)

    if df.empty:
        print(f"  [WARN] No records found for {entity_type}.")
        return

    df = enrich_with_links(df)
    save_final(df, csv_path, json_path)
    print_summary(entity_type, df)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape Addis Ababa venues via Brave Search API"
    )
    parser.add_argument(
        "--types",
        nargs="+",
        choices=list(ENTITY_TYPES.keys()),
        default=list(ENTITY_TYPES.keys()),
        metavar="TYPE",
        help=f"Types to scrape: {', '.join(ENTITY_TYPES.keys())}. Default: all.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch from scratch (ignore existing output files).",
    )
    args = parser.parse_args()

    if not BRAVE_API_KEY:
        print("[ERROR] BRAVE_API_KEY not set in .env")
        print("        Get a free key at: https://brave.com/search/api/")
        print(f"        Then create: {os.path.join(_ROOT, '.env')}")
        print("        Contents: BRAVE_API_KEY=your_key_here")
        sys.exit(1)

    print(f"[START] Types   : {', '.join(args.types)}")
    print(f"[START] Refresh : {args.refresh}")

    for etype in args.types:
        run_for_type(etype, refresh=args.refresh)

    print("\n[DONE] All requested types scraped successfully.")
