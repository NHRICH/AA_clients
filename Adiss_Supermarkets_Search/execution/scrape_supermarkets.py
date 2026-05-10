"""
execution/scrape_supermarkets.py
---------------------------------
Scrapes supermarket & grocery store data in Addis Ababa using Brave Search API.
Generates comprehensive details including website, social media links, and
Google Maps search links.

Virtual env: uses the shared venv from the parent project (..\\venv\\)

Usage:
  ..\\venv\\Scripts\\python.exe execution\\scrape_supermarkets.py
"""

import os
import re
import sys
import time
import warnings
import argparse
import urllib.parse
import requests
import pandas as pd
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Config
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
load_dotenv(dotenv_path=os.path.join(_ROOT, ".env"))

BRAVE_API_KEY  = os.getenv("BRAVE_API_KEY", "")
BRAVE_WEB_URL  = "https://api.search.brave.com/res/v1/web/search"

OUTPUT_DIR = os.path.join(_ROOT, "output")
CSV_PATH = os.path.join(OUTPUT_DIR, "supermarkets_addis_abeba.csv")
JSON_PATH = os.path.join(OUTPUT_DIR, "supermarkets_addis_abeba.json")

NEIGHBORHOODS = [
    "Bole", "Kirkos", "Yeka", "Lideta", "Gulele",
    "Arada", "Kolfe Keranio", "Akaky Kaliti", "Nifas Silk Lafto", "Lemi Kura"
]

REQUEST_TIMEOUT = 10
POLITE_DELAY    = 1.1
WORKERS         = 8
RESULTS_PER_PAGE = 20
MAX_PAGES        = 10  # Brave Search API only allows offset 0-9

# Regex patterns
_PHONE_RE   = re.compile(r"(\+?251[\s\-]?\d[\d\s\-]{6,}|\+?0\d{9})")
_RATING_RE  = re.compile(r"(\d\.\d)\s*(?:out of 5|stars?|★|/5)", re.I)
_ADDRESS_RE = re.compile(r"(?:address|location)[:\s]+([^,\n]{5,60}(?:,\s*Addis Ababa)?)", re.I)

_AGGREGATOR_DOMAINS = {
    "tripadvisor.com", "yelp.com", "foursquare.com", "zomato.com",
    "google.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "booking.com", "expedia.com", "hotels.com", "maps.apple.com", "yellowpages"
}

def _brave_headers() -> dict:
    return {
        "Accept":                "application/json",
        "Accept-Encoding":       "gzip",
        "X-Subscription-Token":  BRAVE_API_KEY,
    }

def fetch_brave_web(query: str, page: int = 0) -> dict:
    params = {
        "q":      query,
        "count":  RESULTS_PER_PAGE,
        "offset": page,
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

def generate_maps_link(name: str, neighborhood: str) -> str:
    query = f"{name} {neighborhood} Addis Ababa Ethiopia"
    encoded_query = urllib.parse.quote_plus(query)
    return f"https://www.google.com/maps/search/?api=1&query={encoded_query}"

def parse_brave_result(result: dict, neighborhood: str) -> dict | None:
    url  = result.get("url", "")
    if _is_aggregator(url):
        return None

    title       = result.get("title", "").strip()
    description = result.get("description", "")
    all_text    = " ".join([description] + result.get("extra_snippets", []))

    return {
        "name":          title,
        "url":           url,
        "description":   description,
        "category":      "Supermarket",
        "neighborhood":  neighborhood,
        "address":       _ADDRESS_RE.search(all_text).group(1).strip() if _ADDRESS_RE.search(all_text) else "",
        "phone":         _PHONE_RE.search(all_text).group(0).strip() if _PHONE_RE.search(all_text) else "",
        "rating":        float(_RATING_RE.search(all_text).group(1)) if _RATING_RE.search(all_text) else None,
        "google_maps_url": generate_maps_link(title, neighborhood),
        "links_on_site": None, 
        "scraped_at":    datetime.now(timezone.utc).isoformat(),
    }

def scrape_website_links(row_data: tuple) -> tuple[int, str]:
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
                
        # Filter for only social media + significant internal links to keep it clean
        social_links = [l for l in links if any(s in l.lower() for s in ["facebook.com", "instagram.com", "twitter.com", "linkedin.com", "t.me"])]
        if not social_links:
            # If no social links, keep up to 10 unique links
            return idx, " | ".join(sorted(list(links))[:10])
        return idx, " | ".join(sorted(social_links))
    except Exception as exc:
        print(f"    [SKIP] {url} → {type(exc).__name__}")
        return idx, ""

def enrich_with_links(df: pd.DataFrame) -> pd.DataFrame:
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
    print(f"\\n[PHASE 2] {pending} sites to visit ({total - pending} skipped) | {WORKERS} workers")

    if not needs:
        return df

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as exe:
        futures = {exe.submit(scrape_website_links, item): item for item in needs}
        for future in as_completed(futures):
            idx, links_str = future.result()
            df.at[idx, "links_on_site"] = links_str
            done += 1
            if done % 10 == 0 or done == pending:
                print(f"  … {done}/{pending} scraped")
    return df

def fetch_listings(refresh: bool) -> list[dict]:
    records: list[dict] = []
    seen_urls: set[str] = set()

    if not refresh and os.path.exists(CSV_PATH) and os.path.getsize(CSV_PATH) > 10:
        try:
            existing = pd.read_csv(CSV_PATH)
            seen_urls = set(existing["url"].dropna().str.strip())
            records = existing.to_dict("records")
            print(f"[RESUME] Loaded {len(records)} existing records.")
        except pd.errors.EmptyDataError:
            pass

    for hood in NEIGHBORHOODS:
        query = f'supermarkets in {hood} Addis Ababa Ethiopia'
        print(f"\\n  [QUERY] {query}")

        for page in range(MAX_PAGES):
            try:
                data = fetch_brave_web(query, page=page)
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response else "?"
                print(f"    [HTTP {code}] {exc} — stopping {hood}")
                break
            except Exception as exc:
                print(f"    [ERROR] {exc} — stopping {hood}")
                break

            results = (data.get("web") or {}).get("results", [])
            if not results:
                break

            new_count = 0
            for result in results:
                parsed = parse_brave_result(result, hood)
                if parsed is None:
                    continue
                url = parsed["url"].strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                records.append(parsed)
                new_count += 1

            print(f"    page {page:>2} → {len(results):>2} results, {new_count} new")
            time.sleep(POLITE_DELAY)

            if len(results) < RESULTS_PER_PAGE:
                break

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pd.DataFrame(records).to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
        print(f"  [CHECKPOINT] {len(records)} records saved.")

    return records

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Addis Ababa Supermarkets via Brave API")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch from scratch")
    args = parser.parse_args()

    if not BRAVE_API_KEY:
        print("[ERROR] BRAVE_API_KEY not set in .env")
        sys.exit(1)

    print("\\n############################################################")
    print("#  BRAVE SCRAPING: SUPERMARKETS")
    print("############################################################")

    records = fetch_listings(args.refresh)
    df = pd.DataFrame(records)

    if df.empty:
        print("  [WARN] No records found.")
        sys.exit(0)

    df = enrich_with_links(df)
    
    # Save final
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    df.to_json(JSON_PATH, orient="records", force_ascii=False, indent=2)
    
    print(f"\\n[SAVED] {len(df)} records → {CSV_PATH}")
    
    print("\\n====================================================")
    print("  SUPERMARKETS — SUMMARY")
    print("====================================================")
    print(f"  Total records  : {len(df)}")
    print(f"  With phone     : {df['phone'].notna().sum()}")
    print(f"  With map link  : {df['google_maps_url'].notna().sum()}")
    print("  By neighbourhood:")
    for hood, cnt in df["neighborhood"].value_counts().items():
        print(f"    {cnt:>4}  {hood}")
    print("\\n[DONE] Successfully extracted supermarkets.")
