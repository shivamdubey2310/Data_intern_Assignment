import pandas as pd
from pathlib import Path
import logging
import sys

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")

# We only need these primary keys to identify the location
KEYS_TO_KEEP = ['cycle', 'state_name', 'district_name', 'block_name', 'village_name']

def load_and_combine(file_paths):
    """Reads a list of CSV paths and combines them into a single DataFrame."""
    dfs = []
    for path in file_paths:
        try:
            df = pd.read_csv(path)
            if not df.empty:
                dfs.append(df)
        except pd.errors.EmptyDataError:
            logger.warning(f"File is empty and skipped: {path}")
        except Exception as e:
            logger.error(f"Error reading {path}: {e}")
            
    if not dfs:
        return pd.DataFrame()
        
    return pd.concat(dfs, ignore_index=True)

def clean_and_standardize(df):
    """Uses an ALLOWLIST to strictly keep only required columns and formats them."""
    if df.empty:
        return df
        
    # 1. ALLOWLIST: Grab location keys + any column that holds nutrient test results
    results_cols = [c for c in df.columns if c.startswith('results_')]
    columns_to_keep = KEYS_TO_KEEP + results_cols
    
    # Filter the dataframe to ONLY include these columns (drops all hidden API junk)
    columns_to_keep = [c for c in columns_to_keep if c in df.columns]
    df = df[columns_to_keep].copy()
    
    # 2. RENAME: Remove the "results_" prefix and capitalize the first letter
    new_columns = {}
    for col in df.columns:
        if col.startswith('results_'):
            cleaned_name = col.replace('results_', '')
            cleaned_name = cleaned_name[0].upper() + cleaned_name[1:]
            new_columns[col] = cleaned_name
            
    df = df.rename(columns=new_columns)
    
    # 3. CLEAN STRINGS: Standardize text to Title Case
    for col in KEYS_TO_KEEP:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.title()
            
    # 4. HANDLE NULLS: Fill all missing numerical test data with 0
    numeric_cols = df.select_dtypes(include=['number']).columns
    df[numeric_cols] = df[numeric_cols].fillna(0)
    
    return df

def main():
    logger.info("Starting data consolidation...")
    
    if not RAW_DIR.exists():
        logger.critical(f"Raw directory not found: {RAW_DIR}")
        sys.exit(1)
        
    macro_files = list(RAW_DIR.rglob("*_macro.csv"))
    micro_files = list(RAW_DIR.rglob("*_micro.csv"))
    
    logger.info(f"Found {len(macro_files)} Macro files and {len(micro_files)} Micro files.")
    
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
            suffixes=('', '_micro_duplicate')
        )
        # Drop redundant duplicate metrics from the merge
        duplicate_cols = [c for c in final_df.columns if c.endswith('_micro_duplicate')]
        final_df = final_df.drop(columns=duplicate_cols)
    else:
        final_df = macro_df if not macro_df.empty else micro_df
        
    # Reorder columns logically (Locations on left, metrics on right)
    front_cols = KEYS_TO_KEEP
    back_cols = [c for c in final_df.columns if c not in front_cols]
    final_df = final_df[front_cols + back_cols]
    
    # FINAL NULL CHECK: Catch any nulls generated during the outer merge
    numeric_cols = final_df.select_dtypes(include=['number']).columns
    final_df[numeric_cols] = final_df[numeric_cols].fillna(0)
    
    # Save processed data
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DIR / "consolidated_soil_data.csv"
    
    final_df.to_csv(output_path, index=False)
    logger.info(f"Consolidation complete! Saved {len(final_df)} rows to {output_path}")
    
    logger.info("Data Preview:")
    print(final_df.head(3).to_markdown(index=False))

if __name__ == "__main__":
    main()