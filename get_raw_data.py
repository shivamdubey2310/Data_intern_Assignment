import requests
import json
import pandas as pd
from pathlib import Path
import time
import random
import sys
import logging
import re

# --- LOGGING SETUP ---
# This will print to your console AND save everything to scraper.log
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log", mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
BASE_URL = "https://soilhealth4.dac.gov.in/"
HEADERS = {
    "Content-Type": "application/json",
    "x-client-type": "portal",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

CYCLES = ["2023-24", "2024-25"]

SCHEMES = {
    "macro": "660f941a5c8405ca8375c7c6",
    "micro": "68ed22b85e3f58e8c92ea3b4" 
}

# --- GRAPHQL QUERIES ---
QUERY_STATE = """query GetState($getStateId: String, $code: String) {
  getState(id: $getStateId, code: $code)
}"""

QUERY_DISTRICT = """query GetdistrictAndSubdistrictBystate($getdistrictAndSubdistrictBystateId: String, $name: String, $state: ID, $subdistrict: Boolean, $code: String, $aspirationaldistrict: Boolean) {
  getdistrictAndSubdistrictBystate(
    id: $getdistrictAndSubdistrictBystateId
    name: $name
    state: $state
    subdistrict: $subdistrict
    code: $code
    aspirationaldistrict: $aspirationaldistrict
  )
}"""

QUERY_BLOCK = """query GetBlocks($getBlocksId: String, $name: String, $code: String, $state: ID, $district: ID, $subdistrict: ID, $aspirationalblock: Boolean) {
  getBlocks(
    id: $getBlocksId
    name: $name
    code: $code
    state: $state
    district: $district
    subdistrict: $subdistrict
    aspirationalblock: $aspirationalblock
  )
}"""

QUERY_DATA = """query GetNutrientDashboardForPortal($state: ID, $district: ID, $block: ID, $village: ID, $cycle: String, $count: Boolean, $scheme: String) {
  getNutrientDashboardForPortal(
    state: $state
    district: $district
    block: $block
    village: $village
    cycle: $cycle
    count: $count
    scheme: $scheme
  )
}"""

# --- CORE FUNCTIONS ---

def sanitize_name(name: str) -> str:
    """Removes characters that are illegal in file/folder paths."""
    if not name:
        return "Unknown"
    # Replace slashes, backslashes, colons, asterisks, etc., with an underscore
    return re.sub(r'[\\/*?:"<>|]', '_', str(name)).strip()

def fetch_graphql(operation_name, variables, query_string, max_retries=3):
    """Executes a GraphQL POST request with exponential backoff retries."""
    payload = {
        "operationName": operation_name,
        "variables": variables,
        "query": query_string
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.post(BASE_URL, json=payload, headers=HEADERS, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
            logger.warning(f"Network Error during {operation_name}: {e}. Retrying in {wait_time:.1f}s...")
            time.sleep(wait_time)
            
    logger.error(f"Failed {operation_name} entirely after {max_retries} attempts.")
    return None

def parse_graphql_response(response_dict, query_key):
    """Extracts data from the response, handling stringified JSON if needed."""
    if not response_dict or 'data' not in response_dict:
        return []
    
    raw_content = response_dict['data'].get(query_key)
    if not raw_content:
        return []
        
    if isinstance(raw_content, str):
        try:
            return json.loads(raw_content)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON string for {query_key}")
            return []
    return raw_content

# --- DATA FETCHERS ---

def get_states():
    res = fetch_graphql("GetState", {}, QUERY_STATE)
    return parse_graphql_response(res, "getState")

def get_districts(state_id):
    variables = {"state": state_id}
    res = fetch_graphql("GetdistrictAndSubdistrictBystate", variables, QUERY_DISTRICT)
    return parse_graphql_response(res, "getdistrictAndSubdistrictBystate")

def get_blocks(state_id, district_id):
    variables = {"state": state_id, "district": district_id}
    res = fetch_graphql("GetBlocks", variables, QUERY_BLOCK)
    return parse_graphql_response(res, "getBlocks")

def get_nutrient_data(state_id, district_id, block_id, cycle, scheme):
    variables = {
        "cycle": cycle,
        "scheme": scheme,
        "state": state_id,
        "district": district_id,
        "block": block_id
    }
    res = fetch_graphql("GetNutrientDashboardForPortal", variables, QUERY_DATA)
    return parse_graphql_response(res, "getNutrientDashboardForPortal")

# --- MAIN SCRAPER LOGIC ---

def main():
    logger.info("Initializing Soil Health Scraper...")
    
    states = get_states()
    if not states:
        logger.critical("Failed to fetch states. Check headers or internet connection.")
        sys.exit(1)
        
    logger.info(f"Found {len(states)} states. Starting extraction...")

    for state in states:
        state_id = state.get('id') or state.get('_id')
        raw_state_name = state.get('name', 'Unknown_State')
        safe_state_name = sanitize_name(raw_state_name)
        
        logger.info(f"--> Accessing State: {raw_state_name}")
        districts = get_districts(state_id)
        
        for district in districts:
            district_id = district.get('id') or district.get('_id')
            raw_district_name = district.get('name', 'Unknown_District')
            safe_district_name = sanitize_name(raw_district_name)
            
            blocks = get_blocks(state_id, district_id)
            
            for block in blocks:
                block_id = block.get('id') or block.get('_id')
                raw_block_name = block.get('name', 'Unknown_Block')
                safe_block_name = sanitize_name(raw_block_name)
                
                for cycle in CYCLES:
                    for nutrient_type, scheme_id in SCHEMES.items():
                        
                        # --- 1. SET UP PATHS & CHECKPOINTING ---
                        folder_path = Path(f"data/raw/{cycle}/{safe_state_name}/{safe_district_name}")
                        folder_path.mkdir(parents=True, exist_ok=True)
                        
                        file_name = f"{safe_block_name}_{nutrient_type}.csv"
                        file_path = folder_path / file_name
                        
                        if file_path.exists():
                            logger.info(f"[~] SKIP: {file_name} in {cycle} (Already exists)")
                            continue
                        
                        # --- 2. ORGANIC DELAY ---
                        # Sleep between 2 to 5 seconds to prevent rate limits
                        sleep_time = random.uniform(2.0, 5.0)
                        time.sleep(sleep_time)

                        # --- 3. FETCH & PROCESS ---
                        raw_data = get_nutrient_data(state_id, district_id, block_id, cycle, scheme_id)
                        
                        if raw_data and len(raw_data) > 0:
                            df = pd.json_normalize(raw_data, sep='_')
                            df.to_csv(file_path, index=False)
                            logger.info(f"[+] SAVED: {len(df)} records -> {file_path}")
                        else:
                            # Not an error, just an empty dataset from the government
                            logger.debug(f"[-] EMPTY: No {nutrient_type} data for {safe_block_name} ({cycle})")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Scraper manually stopped by user.")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"An unexpected fatal error occurred: {e}", exc_info=True)
        sys.exit(1)