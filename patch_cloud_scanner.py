import os
import re

cloud_dir = r"C:\Users\pc\Desktop\Smile_Stock_System\cloud_scanner"
git_dir = r"C:\Users\pc\Desktop\Smile_Stock_System"

def patch_file(filename, replacements):
    filepath = os.path.join(cloud_dir, filename)
    if not os.path.exists(filepath):
        return
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    for old, new in replacements:
        content = content.replace(old, new)
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

# 1. ai_commentator.py
patch_file('ai_commentator.py', [
    (r'config_path = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\config.json"', 'config_path = "config.json"'),
    (r'''        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                api_key = json.load(f).get('GEMINI_API_KEY')
        except Exception:
            pass''', '''        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                api_key = json.load(f).get('GEMINI_API_KEY')
        except Exception:
            pass
    if not api_key:
        api_key = os.environ.get('GEMINI_API_KEY')''')
])

# 2. historical_report_compiler.py
patch_file('historical_report_compiler.py', [
    (r'font_path = "C:\\Windows\\Fonts\\malgun.ttf"', 'font_path = "NanumGothic.ttf"'),
    (r'font_bold_path = "C:\\Windows\\Fonts\\malgunbd.ttf"', 'font_bold_path = "NanumGothicBold.ttf"'),
    (r'themes_json_path = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\alphasquare_themes.json"', "themes_json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'alphasquare_themes.json')"),
    (r'names_json_path = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\stock_names.json"', "names_json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'stock_names.json')"),
    (r'artifact_dir = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34"', "artifact_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'charts')"),
    (r'charts_dir = os.path.join(artifact_dir, f"charts_{date_str}")', 'charts_dir = os.path.join(artifact_dir, date_str)'),
    (r'desktop_dir = r"C:\Users\pc\Desktop\양음양 리포트"', "desktop_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))")
])

# 3. local_data_manager.py
patch_file('local_data_manager.py', [
    (r'DB_PATH = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\scratch\stock_ohlcv_cache.db"', 'DB_PATH = os.path.join(base_dir, "stock_ohlcv_cache.db")')
])

# 4. yangeumyang_tracker.py
patch_file('yangeumyang_tracker.py', [
    (r'WATCHLIST_PATH = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\scratch\yangeumyang_watchlist.json"', 'WATCHLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yangeumyang_watchlist.json")')
])

# 5. 500m scanner files
patch_file('generate_charts.py', [
    (r'charts_dir = r"C:\Users\pc\Desktop\Smile_Stock_System\stock_scanner_500m\charts"', 'charts_dir = "charts"')
])
patch_file('compile_pdf_report.py', [
    (r'font_path = "C:\\Windows\\Fonts\\malgun.ttf"', 'font_path = "NanumGothic.ttf"'),
    (r'font_bold_path = "C:\\Windows\\Fonts\\malgunbd.ttf"', 'font_bold_path = "NanumGothicBold.ttf"'),
    (r'desktop_dir = r"C:\Users\pc\Desktop\양음양 리포트\500억봉"', "desktop_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))")
])
patch_file('run_scan_and_report.py', [
    (r'desktop_dir = r"C:\Users\pc\Desktop\양음양 리포트\500억봉"', "desktop_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))")
])

print('Patch complete!')
