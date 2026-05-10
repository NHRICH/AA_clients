"""
execution/smart_scrape.py
--------------------------
Universal interactive scraper for ANY business type in Addis Ababa.

Features:
  - Interactive prompt: type "massage house", "gym", "spas", "hotel" etc.
  - Gemini API auto-corrects typos and normalizes the search term
  - Brave Search API retrieves results across all 10 sub-cities
  - Parallel website crawling extracts social media links
  - Crash-safe checkpointing — resume anytime
  - Auto-generates Google Maps search links for every venue
  - Clean CSV + JSON output, no HTML junk

Usage:
  .\\venv\\Scripts\\python.exe execution\\smart_scrape.py

  # Or pass the type directly (skip the interactive prompt):
  .\\venv\\Scripts\\python.exe execution\\smart_scrape.py --type "massage parlor"

  # Force re-fetch from scratch:
  .\\venv\\Scripts\\python.exe execution\\smart_scrape.py --type "gym" --refresh
"""

import os
import re
import sys
import time
import json
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

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)  # project root
load_dotenv(dotenv_path=os.path.join(_ROOT, ".env"))

BRAVE_API_KEY  = os.getenv("BRAVE_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
BRAVE_WEB_URL  = "https://api.search.brave.com/res/v1/web/search"
GEMINI_URL     = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

OUTPUT_DIR = os.path.join(_ROOT, "output")

NEIGHBORHOODS = [
    "Bole", "Kirkos", "Yeka", "Lideta", "Gulele",
    "Arada", "Kolfe Keranio", "Akaky Kaliti", "Nifas Silk Lafto", "Lemi Kura"
]

REQUEST_TIMEOUT  = 10
POLITE_DELAY     = 1.1
WORKERS          = 8
RESULTS_PER_PAGE = 20
MAX_PAGES        = 10

# Regex patterns
_PHONE_RE   = re.compile(r"(\+?251[\s\-]?\d[\d\s\-]{6,}|\+?0\d{9})")
_RATING_RE  = re.compile(r"(\d\.\d)\s*(?:out of 5|stars?|★|/5)", re.I)
_ADDRESS_RE = re.compile(r"(?:address|location)[:\s]+([^,\n]{5,60}(?:,\s*Addis Ababa)?)", re.I)

_AGGREGATOR_DOMAINS = {
    "tripadvisor.com", "yelp.com", "foursquare.com", "zomato.com",
    "google.com", "booking.com", "expedia.com", "hotels.com",
    "maps.apple.com", "wikipedia.org", "wikiwand.com", "yellowpages",
    "sewasew.com", "mapcarta.com",
}

_SOCIAL_DOMAINS = ["facebook.com", "instagram.com", "twitter.com", "x.com",
                   "linkedin.com", "t.me", "tiktok.com", "youtube.com"]

# ---------------------------------------------------------------------------
# Gemini smart normalization
# ---------------------------------------------------------------------------

def normalize_with_gemini(raw_input: str) -> dict:
    """
    Uses Gemini to:
    1. Fix spelling errors in the input
    2. Produce a clean search label (e.g. 'massage parlors')
    3. Generate a clean filename slug (e.g. 'massage_parlors')
    4. Confirm if it is a valid business type in Addis Ababa context

    Returns dict: {label, slug, corrected, is_valid, message}
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        # Fallback: basic local normalization without Gemini
        slug = re.sub(r"[^a-z0-9]+", "_", raw_input.lower().strip()).strip("_")
        label = raw_input.strip().lower()
        return {
            "label": label,
            "slug": slug,
            "corrected": raw_input,
            "is_valid": True,
            "message": "[No Gemini key] Using raw input as-is."
        }

    prompt = f"""You are a business search assistant for Addis Ababa, Ethiopia.

The user typed: "{raw_input}"

Your job:
1. Fix any spelling errors or typos.
2. Produce the most accurate English plural search term for this business type (e.g. "masage house" → "massage parlors").
3. Produce a clean lowercase underscore filename slug (e.g. "massage_parlors").
4. Decide if this is a valid/real business type that could exist in Addis Ababa. Set is_valid=false for nonsense inputs like "ajhfksjdhf".

Respond ONLY with a valid JSON object. No explanation. No markdown. Example:
{{"corrected": "massage parlors", "label": "massage parlors", "slug": "massage_parlors", "is_valid": true, "message": "Corrected from: masage house"}}"""

    try:
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(GEMINI_URL, json=payload, timeout=10)
        resp.raise_for_status()
        raw = resp.json()
        text = raw["candidates"][0]["content"]["parts"][0]["text"].strip()
        # Strip markdown code fences if Gemini wraps it
        text = re.sub(r"^```[a-z]*\n?", "", text).rstrip("` \n")
        return json.loads(text)
    except Exception as exc:
        print(f"  [WARN] Gemini normalization failed ({exc}). Using raw input.")
        slug = re.sub(r"[^a-z0-9]+", "_", raw_input.lower().strip()).strip("_")
        return {
            "label": raw_input.strip().lower(),
            "slug": slug,
            "corrected": raw_input,
            "is_valid": True,
            "message": "Gemini unavailable — using raw input."
        }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    if not isinstance(text, str):
        return text
    clean = re.sub(r"<[^>]+>", "", text)
    clean = re.sub(r"[\r\n]+", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()

def _is_aggregator(url: str) -> bool:
    try:
        domain = urlparse(url).netloc.lower().lstrip("www.")
        return any(agg in domain for agg in _AGGREGATOR_DOMAINS)
    except Exception:
        return False

def _generate_maps_link(name: str, neighborhood: str) -> str:
    q = urllib.parse.quote_plus(f"{name} {neighborhood} Addis Ababa Ethiopia")
    return f"https://www.google.com/maps/search/?api=1&query={q}"

def _brave_headers() -> dict:
    return {
        "Accept":               "application/json",
        "Accept-Encoding":      "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }

def _fetch_brave_page(query: str, page: int) -> dict:
    params = {"q": query, "count": RESULTS_PER_PAGE, "offset": page}
    resp = requests.get(BRAVE_WEB_URL, headers=_brave_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()

def _parse_result(result: dict, category_label: str, neighborhood: str) -> dict | None:
    url = result.get("url", "")
    if _is_aggregator(url):
        return None

    title       = _strip_html(result.get("title", ""))
    description = _strip_html(result.get("description", ""))
    extras      = [_strip_html(s) for s in result.get("extra_snippets", [])]
    all_text    = " ".join([description] + extras)

    addr_m   = _ADDRESS_RE.search(all_text)
    phone_m  = _PHONE_RE.search(all_text)
    rating_m = _RATING_RE.search(all_text)

    return {
        "name":            title,
        "url":             url,
        "description":     description,
        "category":        category_label.title(),
        "neighborhood":    neighborhood,
        "address":         _strip_html(addr_m.group(1)) if addr_m else "",
        "phone":           phone_m.group(0).strip() if phone_m else "",
        "rating":          float(rating_m.group(1)) if rating_m else None,
        "google_maps_url": _generate_maps_link(title, neighborhood),
        "links_on_site":   None,
        "scraped_at":      datetime.now(timezone.utc).isoformat(),
    }

# ---------------------------------------------------------------------------
# Phase 2 — parallel social / website link extraction
# ---------------------------------------------------------------------------

def _scrape_links(row_data: tuple) -> tuple[int, str]:
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

        social = sorted(l for l in links if any(s in l.lower() for s in _SOCIAL_DOMAINS))
        return idx, " | ".join(social) if social else " | ".join(sorted(links)[:8])
    except Exception as exc:
        return idx, ""

def enrich_with_links(df: pd.DataFrame) -> pd.DataFrame:
    needs = [
        (idx, row["url"])
        for idx, row in df.iterrows()
        if (row.get("url") and pd.notna(row.get("url"))
            and str(row.get("url")).startswith("http")
            and not _is_aggregator(str(row.get("url", "")))
            and (not row.get("links_on_site") or pd.isna(row.get("links_on_site"))))
    ]
    pending = len(needs)
    print(f"\n[PHASE 2] {pending} sites to crawl for links | {WORKERS} workers")
    if not pending:
        return df
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as exe:
        futures = {exe.submit(_scrape_links, item): item for item in needs}
        for fut in as_completed(futures):
            idx, links_str = fut.result()
            df.at[idx, "links_on_site"] = links_str
            done += 1
            if done % 20 == 0 or done == pending:
                print(f"  … {done}/{pending} crawled")
    return df

# ---------------------------------------------------------------------------
# Phase 1 — Brave Search scraping
# ---------------------------------------------------------------------------

def fetch_listings(category_label: str, csv_path: str, refresh: bool) -> list[dict]:
    records: list[dict] = []
    seen_urls: set[str] = set()

    if not refresh and os.path.exists(csv_path) and os.path.getsize(csv_path) > 10:
        try:
            existing = pd.read_csv(csv_path)
            seen_urls = set(existing["url"].dropna().str.strip())
            records = existing.to_dict("records")
            print(f"[RESUME] Loaded {len(records)} existing records from checkpoint.")
        except pd.errors.EmptyDataError:
            pass

    for hood in NEIGHBORHOODS:
        query = f"{category_label} in {hood} Addis Ababa Ethiopia"
        print(f"\n  [QUERY] {query}")

        for page in range(MAX_PAGES):
            try:
                data = _fetch_brave_page(query, page)
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response else "?"
                print(f"    [HTTP {code}] Stopping {hood}")
                break
            except Exception as exc:
                print(f"    [ERROR] {exc} — stopping {hood}")
                break

            results = (data.get("web") or {}).get("results", [])
            if not results:
                break

            new_count = 0
            for result in results:
                parsed = _parse_result(result, category_label, hood)
                if parsed is None:
                    continue
                url = parsed["url"].strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                records.append(parsed)
                new_count += 1

            print(f"    page {page} → {len(results)} results, {new_count} new")
            time.sleep(POLITE_DELAY)

            if len(results) < RESULTS_PER_PAGE:
                break

        # Checkpoint after each neighborhood
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pd.DataFrame(records).to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"  [CHECKPOINT] {len(records)} records → {os.path.basename(csv_path)}")

    return records

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Universal smart venue scraper for Addis Ababa"
    )
    parser.add_argument("--type",    type=str, help="Business type to search (skips prompt)")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch from scratch")
    args = parser.parse_args()

    if not BRAVE_API_KEY:
        print("[ERROR] BRAVE_API_KEY not set in .env")
        sys.exit(1)

    # ── Step 1: Get user input ──────────────────────────────────────────────
    if args.type:
        raw_input_str = args.type
    else:
        print("\n" + "="*60)
        print("  ADDIS ABABA SMART VENUE SCRAPER")
        print("="*60)
        print("  Enter the type of business you want to scrape.")
        print("  Examples: gyms, hotels, spas, pharmacies, massage parlor")
        print("="*60)
        raw_input_str = input("\n  > What are you looking for? ").strip()

    if not raw_input_str:
        print("[ERROR] No input provided. Exiting.")
        sys.exit(1)

    # ── Step 2: Normalize with Gemini ──────────────────────────────────────
    print(f"\n[AI] Analyzing your input: '{raw_input_str}' ...")
    meta = normalize_with_gemini(raw_input_str)

    print(f"[AI] {meta.get('message', '')}")
    print(f"[AI] Search term : {meta['label']}")
    print(f"[AI] Output file : {meta['slug']}_addis_abeba.csv")

    if not meta.get("is_valid", True):
        print("[AI] This doesn't look like a valid business type. Please try again.")
        sys.exit(1)

    category_label = meta["label"]
    slug           = meta["slug"]

    # ── Step 3: Confirm with user ──────────────────────────────────────────
    print(f"\n  Scraping: '{category_label}' across all 10 sub-cities of Addis Ababa")
    confirm = input("  Proceed? [Y/n]: ").strip().lower()
    if confirm == "n":
        print("Aborted.")
        sys.exit(0)

    csv_path  = os.path.join(OUTPUT_DIR, f"{slug}_addis_abeba.csv")
    json_path = os.path.join(OUTPUT_DIR, f"{slug}_addis_abeba.json")

    # ── Step 4: Scrape ────────────────────────────────────────────────────
    print(f"\n{'#'*60}")
    print(f"#  SCRAPING: {category_label.upper()}")
    print(f"{'#'*60}")

    records = fetch_listings(category_label, csv_path, args.refresh)
    df = pd.DataFrame(records)

    if df.empty:
        print(f"  [WARN] No records found for '{category_label}'.")
        sys.exit(0)

    # ── Step 5: Enrich with links ──────────────────────────────────────────
    df = enrich_with_links(df)

    # ── Step 6: Save final output ─────────────────────────────────────────
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_json(json_path, orient="records", force_ascii=False, indent=2)

    # ── Step 7: Summary ───────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  {category_label.upper()} — RESULTS")
    print(f"{'='*60}")
    print(f"  Total records  : {len(df)}")
    print(f"  With phone     : {(df['phone'].notna() & (df['phone'] != '')).sum()}")
    print(f"  With maps link : {df['google_maps_url'].notna().sum()}")
    if "rating" in df.columns:
        print(f"  With rating    : {df['rating'].notna().sum()}")
    print("\n  By neighbourhood:")
    for hood, cnt in df["neighborhood"].value_counts().items():
        print(f"    {cnt:>4}  {hood}")
    print(f"\n  [SAVED] {csv_path}")
    print(f"  [SAVED] {json_path}")
    print(f"\n[DONE] Successfully scraped {len(df)} venues.")

if __name__ == "__main__":
    main()
