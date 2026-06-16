# Fix indentation in robotray_dash.py
with open('robotray_dash.py', 'r') as f:
    lines = f.readlines()

# Fix lines 1351-1357 (0-indexed: 1350-1356)
# Remove 4 spaces from each of these lines
for i in range(1351, 1358):
    if i < len(lines) and lines[i].startswith('                        '):
        lines[i] = lines[i][4:]  # Remove 4 spaces

# Write back
with open('robotray_dash.py', 'w') as f:
    f.writelines(lines)

print("Fixed indentation")
