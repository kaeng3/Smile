import glob
import json
import os

print("=== 포도시 스캔 결과 비교 ===")
for f in sorted(glob.glob("*.json")):
    if "scan" in f or "podosi" in f or "yey" in f:
        try:
            with open(f, 'r', encoding='utf-8') as file:
                data = json.load(file)
            if isinstance(data, list):
                podosi_stocks = [s for s in data if '포도시' in str(s.get('pattern', ''))]
                if podosi_stocks:
                    names = [f"{s.get('name','')}({s.get('code','')})" for s in podosi_stocks]
                    print(f"{f}: 총 {len(podosi_stocks)}개 포도시 포착 -> {names}")
        except Exception as e:
            pass
