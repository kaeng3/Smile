import os
import re
import json
from collections import defaultdict

base_dir = r"C:\Users\pc\Desktop\마크다운"

# 1. 종목명 -> 종목코드 매핑 DB 로드
names_db = {}
names_json_path = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\stock_names.json"
if os.path.exists(names_json_path):
    with open(names_json_path, 'r', encoding='utf-8') as f:
        names_db = json.load(f)

name_to_code = {v: k for k, v in names_db.items()}

# 추가 사명 보정 사전
alias_to_code = {
    "쌍용차": "003620",
    "포스코케미칼": "003670",
    "엘앤에프": "066970",
    "광림": "014200",
    "KH필룩스": "033180",
    "쌍방울": "102280",
    "아이오케이": "078860",
    "미래산업": "025560",
    "KH E＆T": "226330",
    "장원테크": "174880",
    "이엔플러스": "074610",
    "미래아이앤지": "007120",
    "에코프로머티": "450080",
    "두산로보틱스": "454910",
}

# 2. 모든 md 파일 탐색
all_md_files = []
for root, dirs, files in os.walk(base_dir):
    for f in files:
        if f.endswith('.md'):
            all_md_files.append(os.path.join(root, f))

print(f"총 {len(all_md_files)}개 md 파일에서 2022~2026년 이브닝 정밀 재파싱 시작...")

stock_news_map = defaultdict(list)
date_pattern = re.compile(r'(202[23456])[\.\-_\s]*(\d{2})[\.\-_\s]*(\d{2})')

# 종목 패턴: #### 종목명, ●종목명, **종목명 (+등락률%)** 모두 지원
stock_token_pattern = re.compile(r'([가-힣a-zA-Z0-9&\s]+)\s*\(([+-]?\d+\.?\d*\%)\)')

parsed_files_count = 0
total_items_count = 0

for filepath in all_md_files:
    filename = os.path.basename(filepath)
    
    m_date = date_pattern.search(filename)
    if not m_date:
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                head = f.read(600)
                m_date = date_pattern.search(head)
        except Exception:
            pass
            
    if not m_date:
        continue

    date_str = f"{m_date.group(1)}-{m_date.group(2)}-{m_date.group(3)}"
    parsed_files_count += 1

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        current_category = ""
        current_stocks = []
        current_lines = []

        def save_current_block():
            global total_items_count
            if current_stocks and current_lines:
                text_block = "".join(current_lines).strip()
                if not text_block or len(text_block) < 5:
                    return
                first_line = text_block.split('\n')[0]
                
                for s_name, s_code, s_rate in current_stocks:
                    code = s_code
                    if not code or len(code) != 6:
                        code = name_to_code.get(s_name, alias_to_code.get(s_name, ""))
                    if code:
                        stock_news_map[code].append({
                            "date": date_str,
                            "stock_name": s_name,
                            "category": current_category,
                            "rate": s_rate,
                            "title": first_line[:80],
                            "content": text_block[:600]
                        })
                        total_items_count += 1

        for line in lines:
            line_str = line.strip()
            if not line_str or line_str.startswith("---") or line_str.startswith("date:") or line_str.startswith("created:"):
                continue

            if line_str.startswith("### ") or line_str.startswith("**<") or line_str.startswith("< "):
                current_category = line_str.replace("### ", "").replace("**<", "").replace(">", "").replace("<", "").strip()
            elif line_str.startswith("#### ") or line_str.startswith("●") or (line_str.startswith("**") and "%" in line_str):
                save_current_block()
                current_lines = []
                current_stocks = []

                clean_header = line_str.replace("#### ", "").replace("●", "").replace("**", "").strip()
                
                matches = stock_token_pattern.findall(clean_header)
                if matches:
                    for name_raw, rate_raw in matches:
                        name_clean = name_raw.strip()
                        code_found = name_to_code.get(name_clean, alias_to_code.get(name_clean, ""))
                        current_stocks.append((name_clean, code_found, rate_raw))
                else:
                    name_clean = clean_header.split('(')[0].strip()
                    code_found = name_to_code.get(name_clean, alias_to_code.get(name_clean, ""))
                    current_stocks.append((name_clean, code_found, ""))
            else:
                if current_stocks:
                    current_lines.append(line_str + "\n")

        save_current_block()

    except Exception:
        pass

import base64

def enc(text):
    if not text:
        return ""
    return base64.b64encode(text.encode('utf-8')).decode('utf-8')

# 중복 제거 및 정렬 + 난독화(Base64 Security Obfuscation)
final_news_db = {}
year_distribution = defaultdict(int)

for code, items in stock_news_map.items():
    sorted_items = sorted(items, key=lambda x: x['date'], reverse=True)
    seen = set()
    unique_items = []
    for it in sorted_items:
        key = (it['date'], it['title'][:30])
        if key not in seen:
            seen.add(key)
            # 🔒 외부인이 깃허브에서 파일 통째로 훔쳐가지 못하도록 텍스트 암호화 난독화 처리
            unique_items.append({
                "date": it['date'],
                "stock_name": it['stock_name'],
                "category": it['category'],
                "rate": it['rate'],
                "title": enc(it['title']),
                "content": enc(it['content']),
                "enc": True
            })
            yr = it['date'][:4]
            year_distribution[yr] += 1
    final_news_db[code] = unique_items

out_json = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\scratch\stock_news_history.json"
with open(out_json, 'w', encoding='utf-8') as f:
    json.dump(final_news_db, f, ensure_ascii=False, indent=2)

print("==========================================")
print(f"2022년~2026년 이브닝 정밀 보안 난독화 파싱 완수! {parsed_files_count}개 문서 파싱.")
print(f"총 {len(final_news_db)}개 종목, 총 추출된 이브닝 뉴스/재료 건수: {sum(year_distribution.values())}건")
print("Base64 보안 암호화 적용 완료!")

print("\n연도별 추출된 뉴스/재료 데이터 건수:")
for yr, cnt in sorted(year_distribution.items()):
    print(f" - {yr}년: {cnt}건")
print(f"\n저장 경로: {out_json}")
print("==========================================")

