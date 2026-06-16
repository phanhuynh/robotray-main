# Script to fix the corrupted robotray_dash.py file
# Remove all lines that start with '+' and are duplicate/misplaced

with open('robotray_dash.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find and remove the corrupted section between line 825-850
lines = content.split('\n')

# Remove lines that are clearly corrupted (start with + in the middle of code)
fixed_lines = []
skip_next = 0
for i, line in enumerate(lines):
    # Skip corrupted inserted lines in the middle of the except block
    if i >= 831 and i <= 834 and line.strip().startswith('#') and 'Get next test number' in line:
        continue
    if i >= 831 and i <= 834 and 'test_num = get_next_test_number()' in line:
        continue
    if i >= 831 and i <= 850 and line.strip().startswith('timestamp = datetime.datetime.now()'):
        continue
    if i >= 856 and i <= 860 and 'csv_filename = f"{test_num:06d}_' in line:
        continue
        
    fixed_lines.append(line)

with open('robotray_dash_fixed.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(fixed_lines))

print("Created fixed version")
