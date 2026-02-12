"""
Clean up robotray_dash.py by removing corrupted lines and properly adding test counter functionality
"""
import re

with open('robotray_dash.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

cleaned_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    
    # Skip the corrupted duplicate lines around line 832-850
    if (i >= 827 and i <= 860) and (
        ('# Get next test number for filenames' in line and line.strip().startswith('+')) or
        ('test_num = get_next_test_number()' in line and line.strip().startswith('+')) or
        ('timestamp = datetime.datetime.now().strftime("%Y_%m_%d_%H%M%S")' in line and 'except' not in lines[i-1]) or
        ('csv_filename = f"{test_num:06d}_' in line and '@app.callback' in lines[i+2])
    ):
        i += 1
        continue
    
    cleaned_lines.append(line)
    i += 1

# Write cleaned version
with open('robotray_dash.py', 'w', encoding='utf-8') as f:
    f.writelines(cleaned_lines)

print(f"Cleaned {len(lines) - len(cleaned_lines)} corrupted lines")
