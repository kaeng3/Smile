# -*- coding: utf-8 -*-
import csv
import json
import os

def update_db():
    txt_path = r"C:\Users\pc\Desktop\양음양 리포트\종목명,종목코드,대분류,중분류,키워드_중복제거.txt"
    json_path = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\alphasquare_themes.json"
    
    themes_db = {}
    
    if not os.path.exists(txt_path):
        print(f"오류: {txt_path} 파일이 존재하지 않습니다.")
        return
        
    with open(txt_path, 'r', encoding='utf-8') as f:
        # csv reader handles quotes and commas correctly
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            print("오류: 파일이 비어 있습니다.")
            return
            
        for row_idx, row in enumerate(reader, 2):
            if len(row) < 5:
                continue
            name = row[0].strip()
            code = row[1].strip()
            medium_cat = row[3].strip()
            
            # Split themes by ' | '
            themes = []
            if medium_cat:
                parts = [p.strip() for p in medium_cat.split('|')]
                for p in parts:
                    if p.startswith('#'):
                        p = p[1:].strip()
                    if p and p not in themes:
                        themes.append(p)
            
            if code:
                # pad code to 6 digits if it is a number
                if code.isdigit() and len(code) < 6:
                    code = code.zfill(6)
                themes_db[code] = themes
                
    # Save to json
    output_data = {"themes": themes_db}
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
        
    print(f"성공: {len(themes_db)}개 종목의 테마 데이터를 {json_path}에 저장 완료했습니다.")

if __name__ == '__main__':
    update_db()
