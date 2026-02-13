import sys
sys.stdout.flush()
print("START", flush=True)

try:
    import pandas as pd
    print("pd ok", flush=True)
    import plotly.graph_objects as go
    print("go ok", flush=True)
    from collections import defaultdict
    print("col ok", flush=True)
    import glob
    print("glob ok", flush=True)
    
    sample_configs = {
        'MiningHighVoltage': '#1f77b4',
        'MiningLowVoltage': '#ff7f0e',
        'SoilHighVoltage': '#2ca02c',
        'SoilMidVoltage': '#d62728',
        'SoilLowVoltage': '#9467bd'
    }
    print("Configs ok", flush=True)
    
    fig = go.Figure()
    print("Fig created", flush=True)
    
    # Just add first trace for testing
    energies = [1, 2, 3, 4, 5]
    values = [10, 20, 15, 25, 30]
    
    fig.add_trace(go.Scatter(x=energies, y=values, name='Test'))
    print("Trace added", flush=True)
    
    fig.update_layout(title="Test", xaxis_title="X", yaxis_title="Y")
    print("Layout updated", flush=True)
    
    fig.write_html("test_combined.html")
    print("HTML written successfully!", flush=True)
    
except Exception as e:
    print(f"ERROR: {str(e)}", flush=True)
    import traceback
    traceback.print_exc()
