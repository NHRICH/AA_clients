"""
execution/combine_and_clean.py
-------------------------------
Merges all venue datasets (restaurants, cafes, bakeries from Google Maps/SerpApi
AND bars, nightclubs from Brave Search API) into a single, clean, deduplicated
master dataset organized by neighborhood.

Run using the shared venv:
  .\\venv\\Scripts\\python.exe execution\\combine_and_clean.py
"""

import os
import pandas as pd

# Define paths
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERP_OUTPUT_DIR = os.path.join(ROOT_DIR, "output")
BRAVE_OUTPUT_DIR = os.path.join(ROOT_DIR, "Adiss_Brave_Search", "output")
MASTER_CSV_PATH = os.path.join(SERP_OUTPUT_DIR, "all_venues_addis_abeba_master.csv")
MASTER_JSON_PATH = os.path.join(SERP_OUTPUT_DIR, "all_venues_addis_abeba_master.json")

# Define target columns to keep unified
UNIFIED_COLUMNS = [
    "name", "category", "neighborhood", "full_address", "phone", 
    "rating", "review_count", "website_url", "google_maps_url", 
    "links_on_site", "source", "scraped_at"
]

def load_serpapi_files() -> list[pd.DataFrame]:
    dfs = []
    files = ["restaurants_addis_abeba.csv", "cafes_addis_abeba.csv", "bakeries_addis_abeba.csv"]
    for f in files:
        path = os.path.join(SERP_OUTPUT_DIR, f)
        if os.path.exists(path) and os.path.getsize(path) > 10:
            df = pd.read_csv(path)
            # Map columns to unified schema
            df.rename(columns={"website": "website_url"}, inplace=True)
            df["source"] = "Google Maps / SerpApi"
            # Ensure missing columns exist
            for col in UNIFIED_COLUMNS:
                if col not in df.columns:
                    df[col] = None
            dfs.append(df[UNIFIED_COLUMNS])
    return dfs

def load_brave_files() -> list[pd.DataFrame]:
    dfs = []
    files = ["bars_addis_brave.csv", "nightclubs_addis_brave.csv"]
    for f in files:
        path = os.path.join(BRAVE_OUTPUT_DIR, f)
        if os.path.exists(path) and os.path.getsize(path) > 10:
            df = pd.read_csv(path)
            # Map columns to unified schema
            df.rename(columns={
                "url": "website_url",
                "address": "full_address"
            }, inplace=True)
            df["google_maps_url"] = None
            df["review_count"] = None
            df["source"] = "Brave Search API"
            
            for col in UNIFIED_COLUMNS:
                if col not in df.columns:
                    df[col] = None
            dfs.append(df[UNIFIED_COLUMNS])
    return dfs

def clean_and_organize(df: pd.DataFrame) -> pd.DataFrame:
    # 1. Clean strings
    for col in ["name", "category", "neighborhood", "full_address", "phone", "website_url"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().replace("nan", None).replace("None", None)
            
    # Fix some common missing values
    df.loc[df["name"] == "", "name"] = None
    df = df.dropna(subset=["name"]) # Name is strictly required
    
    # 2. Normalize Neighborhoods for clean sorting
    if "neighborhood" in df.columns:
        df["neighborhood"] = df["neighborhood"].str.title()
        
        # Helper to extract real neighborhood from address
        def clean_hood(row):
            h = str(row.get("neighborhood", "")).lower()
            addr = str(row.get("full_address", "")).lower()
            name = str(row.get("name", "")).lower()
            
            # List of known neighborhoods in Addis Ababa to map
            known_hoods = [
                "bole", "kirkos", "yeka", "lideta", "gulele", 
                "arada", "kolfe keranio", "kolfe", "akaky kaliti", "akaky", 
                "nifas silk lafto", "nifas silk", "lafto", "lemi kura",
                "kazanchis", "piassa", "merkato", "saris", "kality", 
                "ayat", "summit", "cmc", "jemo", "gerji", "megenagna", 
                "urael", "haile gar", "bisrate gebriel", "sar bet", "mexico"
            ]
            
            # Identify if current neighborhood is useless (e.g. contains Addis Ababa, is numeric, etc)
            is_generic = not h or h == "nan" or "addis" in h or "ethiopia" in h or h.isdigit() or len(h) <= 2
            
            if is_generic or h not in known_hoods:
                # Scan address and name for known neighborhoods
                search_text = f"{addr} {name}"
                for kh in known_hoods:
                    if kh in search_text:
                        return kh.title()
                
                if is_generic:
                    return "Unknown/Other"
                return h.title()
            
            return h.title()
        
        df["neighborhood"] = df.apply(clean_hood, axis=1)

    # 3. Deduplicate
    # Drop exact duplicates (same name and neighborhood)
    initial_count = len(df)
    # Convert name to lowercase just for deduplication comparison, but keep original
    df["name_lower"] = df["name"].str.lower()
    df = df.sort_values("scraped_at", ascending=False).drop_duplicates(subset=["name_lower", "neighborhood"], keep="first")
    df = df.drop(columns=["name_lower"])
    print(f"Dropped {initial_count - len(df)} duplicate records across categories/sources.")

    # 4. Sort / Organize
    # We will sort primarily by Neighborhood (alphabetical), then by Category, then by Rating (highest first)
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    df = df.sort_values(
        by=["neighborhood", "category", "rating", "name"], 
        ascending=[True, True, False, True],
        na_position="last"
    )
    
    return df

def main():
    print("Loading datasets...")
    serp_dfs = load_serpapi_files()
    brave_dfs = load_brave_files()
    
    all_dfs = serp_dfs + brave_dfs
    if not all_dfs:
        print("No valid data files found.")
        return
        
    master_df = pd.concat(all_dfs, ignore_index=True)
    print(f"Combined {len(master_df)} total raw records.")
    
    print("Cleaning, deduplicating, and organizing data...")
    final_df = clean_and_organize(master_df)
    
    print(f"\nFinal dataset contains {len(final_df)} unique venues.")
    print("\nSummary by Neighborhood:")
    print(final_df["neighborhood"].value_counts().head(15).to_string())
    
    print("\nSummary by Category:")
    print(final_df["category"].value_counts().head(10).to_string())
    
    # Save
    os.makedirs(SERP_OUTPUT_DIR, exist_ok=True)
    final_df.to_csv(MASTER_CSV_PATH, index=False, encoding="utf-8-sig")
    final_df.to_json(MASTER_JSON_PATH, orient="records", force_ascii=False, indent=2)
    
    print(f"\n[SAVED] Master CSV: {MASTER_CSV_PATH}")
    print(f"[SAVED] Master JSON: {MASTER_JSON_PATH}")

if __name__ == "__main__":
    main()
