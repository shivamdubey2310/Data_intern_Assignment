import pandas as pd
import numpy as np

def generate_summary():
    print("Loading data...")
    df = pd.read_csv('data/processed/consolidated_soil_data.csv')
    
    # 1. Engineer the percentage columns safely
    macronutrients = [('N', 'N_Low'), ('P', 'P_Low'), ('K', 'K_Low')]
    for prefix, low_col in macronutrients:
        tot_col = f"{prefix}_Total"
        df[tot_col] = df[f"{prefix}_High"] + df[f"{prefix}_Medium"] + df[f"{prefix}_Low"]
        df[f"{prefix}_Deficiency_Pct"] = np.where(df[tot_col] > 0, (df[low_col] / df[tot_col]) * 100, 0)

    micro_elements = ['S', 'Fe', 'Zn', 'Cu', 'B', 'Mn']
    for el in micro_elements:
        tot_col = f"{el}_Total"
        df[tot_col] = df[f"{el}_Sufficient"] + df[f"{el}_Deficient"]
        df[f"{el}_Deficiency_Pct"] = np.where(df[tot_col] > 0, (df[f"{el}_Deficient"] / df[tot_col]) * 100, 0)

    df['OC_Total'] = df['OC_High'] + df['OC_Medium'] + df['OC_Low']
    df['OC_Deficiency_Pct'] = np.where(df['OC_Total'] > 0, (df['OC_Low'] / df['OC_Total']) * 100, 0)
    
    df['EC_Total'] = df['EC_Saline'] + df['EC_NonSaline']
    df['Saline_Pct'] = np.where(df['EC_Total'] > 0, (df['EC_Saline'] / df['EC_Total']) * 100, 0)

    # 2. Extract Key Statistics
    output = []
    output.append("=== NATIONAL AVERAGES ===")
    
    all_pct_cols = [f"{n[0]}_Deficiency_Pct" for n in macronutrients] + \
                   [f"{el}_Deficiency_Pct" for el in micro_elements] + \
                   ['OC_Deficiency_Pct', 'Saline_Pct']
                   
    national_avgs = df[df['OC_Total'] > 0][all_pct_cols].mean()
    for col, val in national_avgs.items():
        output.append(f"{col}: {val:.2f}%")
        
    output.append("\n=== WORST PERFORMING STATES (MACRO) ===")
    state_avgs = df.groupby('state_name')[all_pct_cols].mean()
    
    output.append(f"Highest N Deficiency: {state_avgs['N_Deficiency_Pct'].idxmax()} ({state_avgs['N_Deficiency_Pct'].max():.2f}%)")
    output.append(f"Highest P Deficiency: {state_avgs['P_Deficiency_Pct'].idxmax()} ({state_avgs['P_Deficiency_Pct'].max():.2f}%)")
    output.append(f"Highest K Deficiency: {state_avgs['K_Deficiency_Pct'].idxmax()} ({state_avgs['K_Deficiency_Pct'].max():.2f}%)")
    output.append(f"Highest OC Deficiency: {state_avgs['OC_Deficiency_Pct'].idxmax()} ({state_avgs['OC_Deficiency_Pct'].max():.2f}%)")

    output.append("\n=== HIGHEST SOIL SALINITY STATES ===")
    top_saline = state_avgs.sort_values('Saline_Pct', ascending=False).head(3)
    for state, val in top_saline['Saline_Pct'].items():
        output.append(f"{state}: {val:.2f}%")
        
    # Write to file
    with open('insight_summary.txt', 'w') as f:
        f.write("\n".join(output))
        
    print("Successfully generated insight_summary.txt")

if __name__ == "__main__":
    generate_summary()