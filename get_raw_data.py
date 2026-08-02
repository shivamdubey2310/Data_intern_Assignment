import requests
import json
import pandas as pd
from pathlib import Path
import time
import random
import sys
import logging
import re
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log", mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

BASE_URL = "https://soilhealth4.dac.gov.in/"
HEADERS = {
    "Content-Type": "application/json",
    "x-client-type": "portal",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

CYCLES = ["2023-24", "2024-25"]

SCHEMES = {
    "macro": "660f941a5c8405ca8375c7c6",
    "micro": "68ed22b85e3f58e8c92ea3b4",
}

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
SLEEP_MIN = 2.0
SLEEP_MAX = 5.0

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


def sanitize_name(name: str) -> str:
    """Replace characters illegal in file paths with underscores."""
    if not name:
        return "Unknown"
    return re.sub(r'[\\/*?:"<>|]', '_', str(name)).strip()


def _get_id(entity: dict) -> Optional[str]:
    """Return the 'id' or '_id' value from an API entity dict."""
    return entity.get('id') or entity.get('_id')


def fetch_graphql(
    operation_name: str,
    variables: dict,
    query_string: str,
    max_retries: int = MAX_RETRIES,
) -> Optional[dict]:
    """Execute a GraphQL POST request with exponential backoff retries."""
    payload = {
        "operationName": operation_name,
        "variables": variables,
        "query": query_string,
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(
                BASE_URL, json=payload, headers=HEADERS, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
            logger.warning(
                "Network error during %s: %s. Retrying in %.1fs...",
                operation_name, e, wait_time,
            )
            time.sleep(wait_time)

    logger.error("Failed %s entirely after %d attempts.", operation_name, max_retries)
    return None


def parse_graphql_response(response_dict: Optional[dict], query_key: str) -> list:
    """Extract data from a GraphQL response, handling stringified JSON if needed."""
    if not response_dict or 'data' not in response_dict:
        return []

    raw_content = response_dict['data'].get(query_key)
    if not raw_content:
        return []

    if isinstance(raw_content, str):
        try:
            return json.loads(raw_content)
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON string for %s", query_key)
            return []
    return raw_content


def get_states() -> list:
    res = fetch_graphql("GetState", {}, QUERY_STATE)
    return parse_graphql_response(res, "getState")


def get_districts(state_id: str) -> list:
    variables = {"state": state_id}
    res = fetch_graphql("GetdistrictAndSubdistrictBystate", variables, QUERY_DISTRICT)
    return parse_graphql_response(res, "getdistrictAndSubdistrictBystate")


def get_blocks(state_id: str, district_id: str) -> list:
    variables = {"state": state_id, "district": district_id}
    res = fetch_graphql("GetBlocks", variables, QUERY_BLOCK)
    return parse_graphql_response(res, "getBlocks")


def get_nutrient_data(
    state_id: str, district_id: str, block_id: str, cycle: str, scheme: str
) -> list:
    variables = {
        "cycle": cycle,
        "scheme": scheme,
        "state": state_id,
        "district": district_id,
        "block": block_id,
    }
    res = fetch_graphql("GetNutrientDashboardForPortal", variables, QUERY_DATA)
    return parse_graphql_response(res, "getNutrientDashboardForPortal")


def main() -> None:
    logger.info("Initializing Soil Health Scraper...")

    states = get_states()
    if not states:
        logger.critical("Failed to fetch states. Check headers or internet connection.")
        sys.exit(1)

    logger.info("Found %d states. Starting extraction...", len(states))

    for state in states:
        state_id = _get_id(state)
        raw_state_name = state.get('name', 'Unknown_State')
        safe_state_name = sanitize_name(raw_state_name)

        logger.info("--> Accessing State: %s", raw_state_name)
        districts = get_districts(state_id)

        for district in districts:
            district_id = _get_id(district)
            raw_district_name = district.get('name', 'Unknown_District')
            safe_district_name = sanitize_name(raw_district_name)

            blocks = get_blocks(state_id, district_id)

            for block in blocks:
                block_id = _get_id(block)
                raw_block_name = block.get('name', 'Unknown_Block')
                safe_block_name = sanitize_name(raw_block_name)

                for cycle in CYCLES:
                    for nutrient_type, scheme_id in SCHEMES.items():
                        folder_path = Path(
                            f"data/raw/{cycle}/{safe_state_name}/"
                            f"{safe_district_name}"
                        )
                        folder_path.mkdir(parents=True, exist_ok=True)

                        file_name = f"{safe_block_name}_{nutrient_type}.csv"
                        file_path = folder_path / file_name

                        if file_path.exists():
                            logger.info(
                                "[~] SKIP: %s in %s (Already exists)", file_name, cycle
                            )
                            continue

                        sleep_time = random.uniform(SLEEP_MIN, SLEEP_MAX)
                        time.sleep(sleep_time)

                        raw_data = get_nutrient_data(
                            state_id, district_id, block_id, cycle, scheme_id
                        )

                        if raw_data:
                            df = pd.json_normalize(raw_data, sep='_')
                            df.to_csv(file_path, index=False)
                            logger.info(
                                "[+] SAVED: %d records -> %s", len(df), file_path
                            )
                        else:
                            logger.debug(
                                "[-] EMPTY: No %s data for %s (%s)",
                                nutrient_type, safe_block_name, cycle,
                            )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Scraper manually stopped by user.")
        sys.exit(0)
    except Exception as e:
        logger.critical("An unexpected fatal error occurred: %s", e, exc_info=True)
        sys.exit(1)
