import requests
import json
import pandas as pd
from pathlib import Path
import time
import sys

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

def fetch_graphql(operation_name, variables, query_string):
    """Executes a GraphQL POST request."""
    payload = {
        "operationName": operation_name,
        "variables": variables,
        "query": query_string
    }
    
    try:
        response = requests.post(BASE_URL, json=payload, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Network Error during {operation_name}: {e}")
        return None

def parse_graphql_response(response_dict, query_key):
    """
    Extracts data from the response. The portal often returns the actual 
    JSON array as a stringified string, so we must parse it twice.
    """
    if not response_dict or 'data' not in response_dict:
        return []
    
    raw_content = response_dict['data'].get(query_key)
    if not raw_content:
        return []
        
    if isinstance(raw_content, str):
        try:
            return json.loads(raw_content)
        except json.JSONDecodeError:
            print(f"Failed to parse JSON string for {query_key}")
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
    print("Initializing Soil Health Scraper...")
    
    states = get_states()
    if not states:
        print("Failed to fetch states. Check headers or internet connection.")
        sys.exit(1)
        
    print(f"Found {len(states)} states. Starting extraction...\n")

    for state in states:
        state_id = state.get('id') or state.get('_id')
        state_name = state.get('name', 'Unknown_State').strip()
        
        print(f"\n--> Accessing State: {state_name}")
        districts = get_districts(state_id)
        
        for district in districts:
            district_id = district.get('id') or district.get('_id')
            district_name = district.get('name', 'Unknown_District').strip()
            
            blocks = get_blocks(state_id, district_id)
            
            for block in blocks:
                block_id = block.get('id') or block.get('_id')
                block_name = block.get('name', 'Unknown_Block').strip()
                
                for cycle in CYCLES:
                    for nutrient_type, scheme_id in SCHEMES.items():
                        
                        # 1. Fetch
                        raw_data = get_nutrient_data(state_id, district_id, block_id, cycle, scheme_id)
                        
                        if raw_data and len(raw_data) > 0:
                            # 2. Transform nested JSON to flat DataFrame
                            # This completely flattens the dictionaries into columns like 'state_name', 'results_pH_Neutral'
                            df = pd.json_normalize(raw_data, sep='_')
                            
                            # 3. Create folder architecture
                            folder_path = Path(f"data/raw/{cycle}/{state_name}/{district_name}")
                            folder_path.mkdir(parents=True, exist_ok=True)
                            
                            # 4. Save
                            file_name = f"{block_name}_{nutrient_type}.csv"
                            file_path = folder_path / file_name
                            df.to_csv(file_path, index=False)
                            
                            print(f"    [+] Saved {len(df)} records -> {file_path}")
                        else:
                            print(f"    [-] No {nutrient_type} data for {block_name} ({cycle})")
                        
                        # Be polite to the API to avoid IP bans
                        time.sleep(0.5)

if __name__ == "__main__":
    main()