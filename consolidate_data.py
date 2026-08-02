import pandas as pd
from pathlib import Path
import logging
import sys
from typing import List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")

KEYS_TO_KEEP = ['cycle', 'state_name', 'district_name', 'block_name', 'village_name']


def load_and_combine(file_paths: List[Path]) -> pd.DataFrame:
    """Read a list of CSV paths and combine them into a single DataFrame."""
    dfs = []
    for path in file_paths:
        try:
            df = pd.read_csv(path)
            if not df.empty:
                dfs.append(df)
        except pd.errors.EmptyDataError:
            logger.warning("File is empty and skipped: %s", path)
        except Exception as e:
            logger.error("Error reading %s: %s", path, e)

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True)


def clean_and_standardize(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to required columns, rename nutrient columns, and standardize formats."""
    if df.empty:
        return df

    results_cols = [c for c in df.columns if c.startswith('results_')]
    columns_to_keep = [c for c in KEYS_TO_KEEP + results_cols if c in df.columns]
    df = df[columns_to_keep].copy()

    rename_map = {
        col: col.replace('results_', '')[0].upper() + col.replace('results_', '')[1:]
        for col in df.columns
        if col.startswith('results_')
    }
    df = df.rename(columns=rename_map)

    for col in KEYS_TO_KEEP:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.title()

    numeric_cols = df.select_dtypes(include=['number']).columns
    df[numeric_cols] = df[numeric_cols].fillna(0)

    return df


def main() -> None:
    logger.info("Starting data consolidation...")

    if not RAW_DIR.exists():
        logger.critical("Raw directory not found: %s", RAW_DIR)
        sys.exit(1)

    macro_files = list(RAW_DIR.rglob("*_macro.csv"))
    micro_files = list(RAW_DIR.rglob("*_micro.csv"))

    logger.info(
        "Found %d Macro files and %d Micro files.", len(macro_files), len(micro_files)
    )

    logger.info("Combining and cleaning Macro data...")
    macro_df = load_and_combine(macro_files)
    macro_df = clean_and_standardize(macro_df)

    logger.info("Combining and cleaning Micro data...")
    micro_df = load_and_combine(micro_files)
    micro_df = clean_and_standardize(micro_df)

    if macro_df.empty and micro_df.empty:
        logger.error("No data found to consolidate. Exiting.")
        sys.exit(1)

    logger.info("Merging Macro and Micro datasets...")

    if not macro_df.empty and not micro_df.empty:
        final_df = pd.merge(
            macro_df,
            micro_df,
            on=KEYS_TO_KEEP,
            how='outer',
            suffixes=('', '_micro_duplicate'),
        )
        duplicate_cols = [c for c in final_df.columns if c.endswith('_micro_duplicate')]
        final_df = final_df.drop(columns=duplicate_cols)
    else:
        final_df = macro_df if not macro_df.empty else micro_df

    front_cols = KEYS_TO_KEEP
    back_cols = [c for c in final_df.columns if c not in front_cols]
    final_df = final_df[front_cols + back_cols]

    numeric_cols = final_df.select_dtypes(include=['number']).columns
    final_df[numeric_cols] = final_df[numeric_cols].fillna(0)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DIR / "consolidated_soil_data.csv"

    final_df.to_csv(output_path, index=False)
    logger.info("Consolidation complete! Saved %d rows to %s", len(final_df), output_path)

    logger.info("Data Preview:")
    print(final_df.head(3).to_markdown(index=False))


if __name__ == "__main__":
    main()
