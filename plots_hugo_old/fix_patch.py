# Quick fix to remove the + prefix from lines
with open('robotray_dash.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

fixed_lines = []
for line in lines:
    if line.startswith('+'):
        fixed_lines.append(line[1:])
    else:
        fixed_lines.append(line)

with open('robotray_dash.py', 'w', encoding='utf-8') as f:
    f.writelines(fixed_lines)

print("Fixed!")
