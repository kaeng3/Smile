import json
import datetime
import subprocess
import sys

dates_data = {
    '20260706': [
        {
            'code': '006340', 'name': '대원전선', 'close': 3825, 'rate': -3.16,
            'match_type': 'predictive', 'pattern': 'Pattern 1'
        },
        {
            'code': '457600', 'name': '벡트', 'close': 2205, 'rate': -3.92,
            'match_type': 'predictive', 'pattern': '60일의 법칙'
        },
        {
            'code': '092730', 'name': '네오팜', 'close': 18510, 'rate': -3.34,
            'match_type': 'predictive', 'pattern': '60일의 법칙'
        },
        {
            'code': '204620', 'name': '글로벌텍스프리', 'close': 4885, 'rate': -4.03,
            'match_type': 'predictive', 'pattern': '60일의 법칙'
        }
    ],
    '20260707': [
        {
            'code': '006340', 'name': '대원전선', 'close': 3760, 'rate': -1.70,
            'match_type': 'predictive', 'pattern': '60일의 법칙'
        },
        {
            'code': '119850', 'name': '지엔씨에너지', 'close': 5370, 'rate': -5.12,
            'match_type': 'predictive', 'pattern': 'Pattern 1'
        },
        {
            'code': '046940', 'name': '우원개발', 'close': 3435, 'rate': -4.58,
            'match_type': 'predictive', 'pattern': 'Pattern 1'
        },
        {
            'code': '362320', 'name': '청담글로벌', 'close': 4550, 'rate': -2.36,
            'match_type': 'predictive', 'pattern': '60일의 법칙'
        },
        {
            'code': '052460', 'name': '아이크래프트', 'close': 3075, 'rate': -3.91,
            'match_type': 'predictive', 'pattern': 'Pattern 2'
        }
    ],
    '20260708': [
        {
            'code': '122350', 'name': '삼기', 'close': 2345, 'rate': -2.29,
            'match_type': 'predictive', 'pattern': 'Pattern 2'
        },
        {
            'code': '092730', 'name': '네오팜', 'close': 19530, 'rate': -2.59,
            'match_type': 'predictive', 'pattern': 'Pattern 1'
        }
    ]
}

# Write JSON files
for date_str, stocks in dates_data.items():
    filename = f"scan_results_{date_str}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(stocks, f, ensure_ascii=False, indent=2)
    print(f"Saved {filename}")

# Run compiler
print("Running historical_report_compiler.py...")
subprocess.run([sys.executable, "-X", "utf8", "historical_report_compiler.py"])
print("Historical compilation process completed.")
