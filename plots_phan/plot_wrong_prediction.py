import pandas as pd
import plotly.graph_objs as go
from plotly.subplots import make_subplots

# Load data
wrong_df = pd.read_csv('models_phan/wrong_predictions.csv', low_memory=False)
median_df = pd.read_csv('plots_phan/cached_spectrums/median_snr_all.csv', low_memory=False)

# Only consider mininghighvoltage
median_df = median_df[median_df['voltage'] == 'mininghighvoltage']

# Find unique targets in wrong_predictions
unique_targets = wrong_df['target'].unique()


# Plot setup
fig = make_subplots(rows=len(unique_targets), cols=1, shared_xaxes=True, vertical_spacing=0.03,
                    subplot_titles=[f"Target: {t}" for t in unique_targets])

# Load snr_all.csv only once
snr_all = pd.read_csv('plots_phan/cached_spectrums/snr_all.csv', low_memory=False)

for idx, target in enumerate(unique_targets, 1):
    # Median and confidence bands for this target
    tdf = median_df[median_df['target'] == target]
    if tdf.empty:
        continue
    energy = tdf['Energy (keV)']
    # Confidence bands
    x_band1 = list(energy) + list(energy[::-1])
    y_band1 = list(tdf['q25']) + list(tdf['q75'][::-1])
    x_band2 = list(energy) + list(energy[::-1])
    y_band2 = list(tdf['q05']) + list(tdf['q95'][::-1])
    fig.add_trace(go.Scatter(x=x_band2, y=y_band2, fill='toself', fillcolor='rgba(0,100,200,0.07)',
                             line=dict(width=0), showlegend=False, name=f'{target} Q05-Q95', hoverinfo='skip'), row=idx, col=1)
    fig.add_trace(go.Scatter(x=x_band1, y=y_band1, fill='toself', fillcolor='rgba(0,100,200,0.15)',
                             line=dict(width=0), showlegend=False, name=f'{target} Q25-Q75', hoverinfo='skip'), row=idx, col=1)
    # Median line
    fig.add_trace(go.Scatter(x=energy, y=tdf['SNR_median'], mode='lines', name=f'{target} median',
                             line=dict(color='blue')), row=idx, col=1)
    # Superimpose only the first 10 wrong predictions for this target
    wrong_target = wrong_df[(wrong_df['target'] == target) & (wrong_df['voltage'] == 'mininghighvoltage')].head(10)
    if not wrong_target.empty:
        for _, row in wrong_target.iterrows():
            test_val = row['test']
            indiv = snr_all[(snr_all['test'] == test_val) & (snr_all['voltage'] == 'mininghighvoltage')]
            if not indiv.empty:
                fig.add_trace(go.Scatter(x=indiv['Energy (keV)'], y=indiv['SNR'], mode='lines',
                                         name=f'Wrong: {test_val}', line=dict(color='red', dash='solid', width=1),
                                         showlegend=True), row=idx, col=1)

fig.update_layout(height=400*len(unique_targets), showlegend=True,
                  title="Median SNR and Wrong Predictions (mininghighvoltage)")
fig.show(renderer="browser")
