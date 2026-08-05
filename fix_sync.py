import os
import re

with open(r'C:\Users\pc\Desktop\Smile_Stock_System\sync_and_push.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Fix the GITSCANNER_DIR mistake
code = re.sub(r'SCANNER_DIR\s*=\s*r"C:\\Users\\pc\\Desktop\\Smile_Stock_Auto_Scanner"\s*\nGITSCANNER_DIR\s*=\s*os\.path\.join\(GIT_DIR, "cloud_scanner"\)\s*\nARTIFACT_BASE\s*=\s*GIT_DIR',
              'GIT_DIR       = os.path.dirname(os.path.abspath(__file__))\nSCANNER_DIR   = os.path.join(GIT_DIR, "cloud_scanner")\nARTIFACT_BASE = GIT_DIR', code)

with open(r'C:\Users\pc\Desktop\Smile_Stock_System\sync_and_push.py', 'w', encoding='utf-8') as f:
    f.write(code)
print("sync_and_push.py correctly fixed")
