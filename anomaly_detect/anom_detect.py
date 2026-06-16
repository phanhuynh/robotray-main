import pandas as pd

def import_df_snr_elem_mininghigh():
    csv_path = r"C:\Users\phuynh\Projects\robotray-main\models_phan\df_snr_elem.csv"
    df = pd.read_csv(csv_path)
    df_snr_elem_mininghigh = df[df['voltage'] == 'mininghighvoltage']
    print(df_snr_elem_mininghigh.head())
    return df_snr_elem_mininghigh

if __name__ == "__main__":
    df_snr_elem_mininghigh = import_df_snr_elem_mininghigh()
