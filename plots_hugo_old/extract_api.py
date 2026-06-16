import os
import re

jar_path = r'XRF Profile Builder\extracted\com\sciaps\xrf\XRFHttpClient.class'
with open(jar_path, 'rb') as f:
    data = f.read()

text = ''.join(chr(b) if 32 <= b <= 126 else ' ' for b in data)

# Find anything around "liveupdate" context  
matches = re.findall(r'.{0,100}[Ll]iveupdate.{0,100}', text)
print("=== Live Update Context ===")
for i, match in enumerate(matches[:10]):
    print(f"\n[{i}] {repr(match)}")

# Also search for HTTP paths
print("\n\n=== All Paths with slashes ===")
matches = re.findall(r'/[a-zA-Z0-9/_-]*', text)
for m in sorted(set(matches)):
    if len(m) > 3:
        print(m)
