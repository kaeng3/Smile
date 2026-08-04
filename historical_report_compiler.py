# -*- coding: utf-8 -*-
import os
import sys
import datetime
import json
import socket
socket.setdefaulttimeout(10.0)
import FinanceDataReader as fdr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def get_previous_trading_day(target_date, stock_dfs=None):
    start_date = target_date - datetime.timedelta(days=15)
    try:
        df = None
        if stock_dfs and '005930' in stock_dfs:
            df = stock_dfs['005930']
        if df is None:
            df = fdr.DataReader('005930', start_date.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
        if len(df) >= 2:
            if df.index[-1].to_pydatetime().date() == target_date.date():
                return df.index[-2].to_pydatetime()
            else:
                return df.index[-1].to_pydatetime()
    except Exception as e:
        print("이전 영업일 구하기 실패:", e)
    return None

# 1. 맑은 고딕 폰트 등록
font_path = "C:\\Windows\\Fonts\\malgun.ttf"
font_bold_path = "C:\\Windows\\Fonts\\malgunbd.ttf"
if os.path.exists(font_path):
    pdfmetrics.registerFont(TTFont('Malgun', font_path))
if os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('MalgunBold', font_bold_path))
else:
    pdfmetrics.registerFont(TTFont('MalgunBold', font_path))

# 2. 테마 및 종목명 JSON DB 로드
themes_json_path = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\alphasquare_themes.json"
names_json_path = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\stock_names.json"
themes_db = {}
names_db = {}

if os.path.exists(themes_json_path):
    try:
        with open(themes_json_path, 'r', encoding='utf-8') as f:
            themes_db = json.load(f).get('themes', {})
    except Exception as e:
        print("테마 DB 로딩 실패:", e)

if os.path.exists(names_json_path):
    try:
        with open(names_json_path, 'r', encoding='utf-8') as f:
            names_db = json.load(f)
    except Exception as e:
        print("종목명 DB 로딩 실패:", e)

def get_clean_name(code, default_name):
    return names_db.get(code, default_name)

manual_themes = {
    '457600': ['디스플레이', '에듀테크'],
    '226320': ['화장품', '중국소비'],
    '204620': ['중국소비', '면세점환급'],
    '362320': ['중국소비', '화장품유통'],
    '092730': ['화장품 (아토팜)'],
    '214450': ['바이오', '의료기기 (리쥬란)']
}

def get_stock_themes(code):
    t_themes = themes_db.get(code, [])
    if not t_themes and code in manual_themes:
        t_themes = manual_themes[code]
    if len(t_themes) > 4:
        t_themes = t_themes[:4]
    return ", ".join(t_themes) if t_themes else "기타"

def make_chart_historical(code, name, save_dir, target_date, stock_dfs=None):
    save_path = os.path.join(save_dir, f"{code}.png")
    if os.path.exists(save_path):
        return True
    start_date = target_date - datetime.timedelta(days=380)
    try:
        df = None
        if stock_dfs and code in stock_dfs:
            df = stock_dfs[code]
        if df is None:
            df = fdr.DataReader(code, start_date.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
        if df is None or len(df) < 40:
            return False
            
        # 이평선 계산 (224일선 포함)
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        df['MA120'] = df['Close'].rolling(window=120).mean()
        df['MA224'] = df['Close'].rolling(window=224).mean()
        
        chart_df = df.tail(40).copy()
        
        plt.rcParams['font.family'] = 'Malgun Gothic'
        plt.rcParams['axes.unicode_minus'] = False
        
        fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 6), gridspec_kw={'height_ratios': [3, 1]})
        
        x_indices = range(len(chart_df))
        ax1.plot(x_indices, chart_df['MA5'], label='5일선', color='#FF9900', linewidth=1.2)
        ax1.plot(x_indices, chart_df['MA10'], label='10일선', color='#0099FF', linewidth=1.2)
        ax1.plot(x_indices, chart_df['MA20'], label='20일선', color='#E60073', linewidth=1.2)
        ax1.plot(x_indices, chart_df['MA60'], label='60일선', color='#339900', linewidth=1.5)
        ax1.plot(x_indices, chart_df['MA120'], label='120일선', color='black', linewidth=1.5)
        if not chart_df['MA224'].isna().all():
            ax1.plot(x_indices, chart_df['MA224'], label='224일선', color='#8B4513', linewidth=1.5)
        
        width = 0.6
        for i in range(len(chart_df)):
            open_val = chart_df['Open'].iloc[i]
            close_val = chart_df['Close'].iloc[i]
            high_val = chart_df['High'].iloc[i]
            low_val = chart_df['Low'].iloc[i]
            color = '#FF3333' if close_val >= open_val else '#3333FF'
            
            ax1.vlines(i, low_val, high_val, color=color, linewidth=1.2)
            bottom = min(open_val, close_val)
            height = abs(open_val - close_val)
            if height == 0:
                height = 1
                
            rect = plt.Rectangle((i - width/2, bottom), width, height, facecolor=color, edgecolor=color, zorder=3)
            ax1.add_patch(rect)
            
        ax1.grid(True, linestyle='--', alpha=0.5)
        ax1.legend(loc='upper left', fontsize=11)
        ax1.set_title(f"{name} ({code}) 차트 분석", fontsize=16, fontweight='bold')
        ax1.tick_params(axis='both', labelsize=11)
        
        vol_colors = ['#FF3333' if chart_df['Close'].iloc[i] >= chart_df['Open'].iloc[i] else '#3333FF' for i in range(len(chart_df))]
        ax2.bar(x_indices, chart_df['Volume'], color=vol_colors, width=width, zorder=3)
        ax2.grid(True, linestyle='--', alpha=0.5)
        ax2.tick_params(axis='both', labelsize=11)
        
        step = 5
        tick_indices = list(range(0, len(chart_df), step))
        tick_labels = [chart_df.index[idx].strftime('%m-%d') for idx in tick_indices]
        ax2.set_xticks(tick_indices)
        ax2.set_xticklabels(tick_labels, fontsize=11)
        
        plt.tight_layout()
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            
        save_path = os.path.join(save_dir, f"{code}.png")
        plt.savefig(save_path, dpi=120)
        plt.close()
        return True
    except Exception as e:
        print(f"차트 그리기 에러 ({code}):", e)
        return False

# 4. 정밀 기술적 코멘트 생성기
def generate_stock_comment(s, target_date, stock_dfs=None):
    from ai_commentator import get_ai_commentary
    return get_ai_commentary(s['code'], s['name'], s['pattern'], s['close'], s['rate'], s['match_type'], target_date, stock_dfs=stock_dfs)

# 5. 개별 일자별 PDF 리포트 작성
def build_report_for_date(target_date, technique_name='양음양 기법', json_filename=None, pdf_filename_prefix=None, report_title=None, stock_dfs=None):
    date_str = target_date.strftime('%Y%m%d')
    if not json_filename:
        json_filename = f"scan_results_{date_str}.json"
    if not pdf_filename_prefix:
        pdf_filename_prefix = "김일청의_양음양(feat.60Ma)"
    if not report_title:
        report_title = "김일청의 양음양(feat.60Ma) 분석 리포트"
        
    if not os.path.exists(json_filename):
        print(f"스캔 파일 없음: {json_filename}. 스캔을 먼저 실행해야 합니다.")
        return
        
    with open(json_filename, 'r', encoding='utf-8') as f:
        all_stocks = json.load(f)
        
    for s in all_stocks:
        s['name'] = get_clean_name(s['code'], s['name'])
        
    # Only today's predictive picks (내일 공략 관심 종목)
    stocks = [s for s in all_stocks if s.get('match_type') == 'predictive']
    
    print(f"[{technique_name}] 스캔 결과 종목 수: {len(stocks)}")
        
    pattern_order = {
        'Pattern 1': 1,
        'Pattern 2': 2,
        'Pattern 3': 3,
        '60일선': 4,
        '120일선': 5,
        '60일의': 6
    }
    def get_sort_key(s):
        pattern = s.get('pattern', '')
        is_star = 0 if '★' in pattern else 1
        weight = 99
        for k, w in pattern_order.items():
            if k in pattern:
                weight = w
                break
        return (is_star, weight, s.get('rate', 0.0))
        
    stocks = sorted(stocks, key=get_sort_key)
    if len(stocks) > 12:
        stocks = sorted(stocks, key=lambda x: abs(x['rate']), reverse=True)[:12]
        print(f"[{technique_name}] 너무 많은 종목이 포착되어 상위 12개 종목(오늘 등락폭 기준)만 리포트에 수록합니다.")
        
    # 2부 종목: 전일 포착된 예측형 종목의 오늘 결과 추적
    comp_stocks = []
    prev_date = get_previous_trading_day(target_date, stock_dfs=stock_dfs)
    if prev_date:
        prev_date_str = prev_date.strftime('%Y%m%d')
        # 이전 json 파일 경로 결정 (동일 기법 파일 연동)
        prev_json_path = json_filename.replace(date_str, prev_date_str)
        if not os.path.exists(prev_json_path):
            prev_json_path = f"scan_results_{prev_date_str}.json"
        if os.path.exists(prev_json_path):
            try:
                with open(prev_json_path, 'r', encoding='utf-8') as f:
                    prev_stocks = json.load(f)
                prev_pred_stocks = [s for s in prev_stocks if s.get('match_type') == 'predictive']
                prev_pred_stocks = sorted(prev_pred_stocks, key=lambda x: abs(x.get('rate', 0)), reverse=True)[:12]
                
                for ps in prev_pred_stocks:
                    code = ps['code']
                    name = get_clean_name(code, ps['name'])
                    # Load 220 days to calculate MAs and highs/lows
                    df_hist = None
                    if stock_dfs and code in stock_dfs:
                        df_hist = stock_dfs[code]
                    if df_hist is None or len(df_hist) < 2:
                        continue
                    close_prev = df_hist.iloc[-2]['Close']
                    day_curr = df_hist.iloc[-1]
                    close_curr = day_curr['Close']
                    high_curr = day_curr['High']
                    low_curr = day_curr['Low']
                        
                    rate = ((close_curr - close_prev) / close_prev) * 100
                    max_prof = ((high_curr - close_prev) / close_prev) * 100
                    
                    # Calculate moving averages
                    df_hist['MA5'] = df_hist['Close'].rolling(5).mean()
                    df_hist['MA10'] = df_hist['Close'].rolling(10).mean()
                    df_hist['MA13'] = df_hist['Close'].rolling(13).mean()
                    df_hist['MA20'] = df_hist['Close'].rolling(20).mean()
                    df_hist['MA60'] = df_hist['Close'].rolling(60).mean()
                    df_hist['MA120'] = df_hist['Close'].rolling(120).mean()
                    
                    ma5_val = df_hist['MA5'].iloc[-1]
                    ma10_val = df_hist['MA10'].iloc[-1]
                    ma13_val = df_hist['MA13'].iloc[-1]
                    ma20_val = df_hist['MA20'].iloc[-1]
                    ma60_val = df_hist['MA60'].iloc[-1]
                    ma120_val = df_hist['MA120'].iloc[-1]
                    
                    # Check touch MAs
                    touch_ma = []
                    ma_lines = [
                        (5, ma5_val), (10, ma10_val), (13, ma13_val), 
                        (20, ma20_val), (60, ma60_val), (120, ma120_val)
                    ]
                    for name_ma, val_ma in ma_lines:
                        if not val_ma or val_ma != val_ma: continue
                        if abs(low_curr - val_ma) / val_ma <= 0.015:
                            touch_ma.append(f"{name_ma}일선")
                            
                    # Check 20-day high/low support
                    prev_low_20 = df_hist['Low'].iloc[-21:-1].min()
                    prev_high_20 = df_hist['High'].iloc[-21:-1].max()
                    
                    touch_low_high = []
                    if abs(low_curr - prev_low_20) / prev_low_20 <= 0.018:
                        touch_low_high.append("전저점")
                    if abs(low_curr - prev_high_20) / prev_high_20 <= 0.018:
                        touch_low_high.append("전고점")
                        
                    support_details = []
                    if touch_ma:
                        support_details.append(f"{', '.join(touch_ma)} 지지력 확인")
                    if touch_low_high:
                        support_details.append(f"{'/'.join(touch_low_high)} 부근 지지")
                        
                    support_str = f" ({', '.join(support_details)})" if support_details else ""
                    
                    prev_comment = generate_stock_comment(ps, prev_date, stock_dfs=stock_dfs)
                    
                    from ai_commentator import get_ai_review_commentary
                    ai_review = get_ai_review_commentary(
                        code, name, ps['pattern'], close_prev, close_curr, 
                        low_curr, high_curr, rate, max_prof, prev_comment, target_date, stock_dfs=stock_dfs
                    )
                    
                    comp_stocks.append({
                        'code': code,
                        'name': name,
                        'prev_close': close_prev,
                        'close': close_curr,
                        'rate': rate,
                        'max_profit': max_prof,
                        'pattern': ps['pattern'],
                        'result_desc': ai_review,
                        'prev_comment': prev_comment
                    })
            except Exception as e:
                print(f"[{date_str}] 전일 종목 추적 실패:", e)
                
    # 차트 그리기
    artifact_dir = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34"
    charts_dir = os.path.join(artifact_dir, f"charts_{date_str}")
    
    print(f"[{technique_name}] 1부 차트 및 AI 코멘트 작성 시작...", flush=True)
    for idx, s in enumerate(stocks):
        make_chart_historical(s['code'], s['name'], charts_dir, target_date, stock_dfs=stock_dfs)
        s['comment'] = generate_stock_comment(s, target_date, stock_dfs=stock_dfs)
        print(f"  - ({idx+1}/{len(stocks)}) {s['name']} 완료", flush=True)
        
    print(f"[{technique_name}] 2부 복기 차트 작성 시작...", flush=True)
    for idx, s in enumerate(comp_stocks):
        make_chart_historical(s['code'], s['name'], charts_dir, target_date, stock_dfs=stock_dfs)
        print(f"  - 2부 ({idx+1}/{len(comp_stocks)}) {s['name']} 완료", flush=True)
        
    print(f"[{technique_name}] PDF 컴파일 시작...", flush=True)
        
    # PDF 컴파일
    desktop_dir = r"C:\Users\pc\Desktop\양음양 리포트"
    if not os.path.exists(desktop_dir):
        os.makedirs(desktop_dir)
        
    output_pdf_path = os.path.join(desktop_dir, f"{pdf_filename_prefix}_{date_str}.pdf")
    
    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=A4,
        rightMargin=35, leftMargin=35,
        topMargin=35, bottomMargin=35
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='MalgunBold',
        fontSize=24,
        leading=30,
        alignment=1,
        textColor=colors.HexColor('#1E3A8A'),
        spaceAfter=15
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Malgun',
        fontSize=10,
        leading=14,
        alignment=1,
        textColor=colors.HexColor('#4B5563'),
        spaceAfter=25
    )
    
    section_title_style = ParagraphStyle(
        'SectionTitle',
        parent=styles['Heading2'],
        fontName='MalgunBold',
        fontSize=14,
        leading=18,
        textColor=colors.HexColor('#111827'),
        spaceBefore=12,
        spaceAfter=8
    )
    
    stock_name_style = ParagraphStyle(
        'StockName',
        fontName='MalgunBold',
        fontSize=26,
        leading=30,
        textColor=colors.HexColor('#111827'),
        spaceAfter=4
    )
    
    pattern_subtitle_style = ParagraphStyle(
        'PatternSubtitle',
        fontName='MalgunBold',
        fontSize=17,
        leading=21,
        textColor=colors.HexColor('#DC2626'),
        spaceAfter=5
    )
    
    theme_subtitle_style = ParagraphStyle(
        'ThemeSubtitle',
        fontName='MalgunBold',
        fontSize=13,
        leading=17,
        textColor=colors.HexColor('#4B5563'),
        spaceAfter=10
    )
    
    body_style = ParagraphStyle(
        'BodyText',
        parent=styles['Normal'],
        fontName='Malgun',
        fontSize=13,
        leading=19,
        textColor=colors.HexColor('#1F2937'),
        spaceAfter=8
    )
    
    comment_body_style = ParagraphStyle(
        'CommentBodyText',
        parent=styles['Normal'],
        fontName='MalgunBold',
        fontSize=13.5,
        leading=20,
        textColor=colors.HexColor('#111827'),
        spaceAfter=4
    )
    
    table_cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Malgun',
        fontSize=11,
        leading=14,
        alignment=1
    )
    
    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='MalgunBold',
        fontSize=11,
        leading=14,
        alignment=1,
        textColor=colors.white
    )

    story = []
    
    story.append(Paragraph(report_title, title_style))
    story.append(Paragraph(f"기준일: {target_date.strftime('%Y년 %m월 %d일')} 장 마감 기준 | 프로그램 자동 스캔 및 리포트 발행", subtitle_style))
    
    pred_stocks = list(stocks)

    # 1부 요약
    story.append(Paragraph(f"🔮 1부: 내일 공략 관심 종목 ({technique_name} 예측형)", section_title_style))
    if pred_stocks:
        table_data_pred = [[
            Paragraph("순번", table_header_style),
            Paragraph("종목명", table_header_style),
            Paragraph("종목코드", table_header_style),
            Paragraph("오늘 종가", table_header_style),
            Paragraph("등락률", table_header_style),
            Paragraph("공략 기법", table_header_style),
            Paragraph("소속 테마", table_header_style)
        ]]
        for idx, s in enumerate(pred_stocks, 1):
            table_data_pred.append([
                Paragraph(f"{idx:02d}", table_cell_style),
                Paragraph(s['name'], table_cell_style),
                Paragraph(s['code'], table_cell_style),
                Paragraph(f"{s['close']:,}원", table_cell_style),
                Paragraph(f"{s['rate']:.2f}%", table_cell_style),
                Paragraph(s['pattern'], table_cell_style),
                Paragraph(get_stock_themes(s['code']), table_cell_style)
            ])
        pred_table = Table(table_data_pred, colWidths=[25, 75, 55, 65, 50, 110, 140])
        pred_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F3F4F6')])
        ]))
        story.append(pred_table)
    else:
        story.append(Paragraph("[포착된 예측형 종목이 없습니다]", body_style))
        
    story.append(Spacer(1, 15))
    
    # 2부 요약
    story.append(Paragraph("🎓 2부: 전일 관심종목 실전 결과 및 복기 (어제 포착 종목의 오늘 결과)", section_title_style))
    
    comp_success = [s for s in comp_stocks if s['max_profit'] >= 3.0]
    comp_adjust = [s for s in comp_stocks if s['max_profit'] < 3.0]
    
    if comp_stocks:
        # 2.1 적중 종목 요약
        story.append(Paragraph("📈 [적중] 장중 반등 성공 종목 (장중 고가 +3% 이상 반등)", ParagraphStyle('SubSecTitle', fontName='MalgunBold', fontSize=11, leading=15, textColor=colors.HexColor('#16A34A'), spaceBefore=8, spaceAfter=5)))
        if comp_success:
            table_data_success = [[
                Paragraph("순번", table_header_style),
                Paragraph("종목명", table_header_style),
                Paragraph("어제 종가", table_header_style),
                Paragraph("오늘 종가", table_header_style),
                Paragraph("오늘 등락률", table_header_style),
                Paragraph("장중 최고가", table_header_style),
                Paragraph("결과 분석", table_header_style)
            ]]
            for idx, s in enumerate(comp_success, 1):
                short_desc = f"장중 최고 {s['max_profit']:+.2f}% 급등 반등 성공!"
                table_data_success.append([
                    Paragraph(f"{idx:02d}", table_cell_style),
                    Paragraph(s['name'], table_cell_style),
                    Paragraph(f"{int(s['prev_close']):,}원", table_cell_style),
                    Paragraph(f"{int(s['close']):,}원", table_cell_style),
                    Paragraph(f"{s['rate']:+.2f}%", table_cell_style),
                    Paragraph(f"{s['max_profit']:+.2f}%", table_cell_style),
                    Paragraph(short_desc, table_cell_style)
                ])
            success_table = Table(table_data_success, colWidths=[25, 65, 60, 60, 55, 85, 170])
            success_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#16A34A')),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F0FDF4')])
            ]))
            story.append(success_table)
        else:
            story.append(Paragraph("[오늘 장중 +3% 이상 반등에 성공한 적중 종목이 없습니다]", body_style))
            
        story.append(Spacer(1, 10))
        
        # 2.2 미흡/조정 종목 요약
        story.append(Paragraph("📉 [미흡/조정] 지지력 테스트 및 보합 종목 (장중 고가 +3% 미만)", ParagraphStyle('SubSecTitle2', fontName='MalgunBold', fontSize=11, leading=15, textColor=colors.HexColor('#DC2626'), spaceBefore=8, spaceAfter=5)))
        if comp_adjust:
            table_data_adjust = [[
                Paragraph("순번", table_header_style),
                Paragraph("종목명", table_header_style),
                Paragraph("어제 종가", table_header_style),
                Paragraph("오늘 종가", table_header_style),
                Paragraph("오늘 등락률", table_header_style),
                Paragraph("장중 최고가", table_header_style),
                Paragraph("결과 분석", table_header_style)
            ]]
            for idx, s in enumerate(comp_adjust, 1):
                short_desc = f"오늘 종가 {s['rate']:+.2f}% (지지선 매수 밴드 테스트 중)"
                table_data_adjust.append([
                    Paragraph(f"{idx:02d}", table_cell_style),
                    Paragraph(s['name'], table_cell_style),
                    Paragraph(f"{int(s['prev_close']):,}원", table_cell_style),
                    Paragraph(f"{int(s['close']):,}원", table_cell_style),
                    Paragraph(f"{s['rate']:+.2f}%", table_cell_style),
                    Paragraph(f"{s['max_profit']:+.2f}%", table_cell_style),
                    Paragraph(short_desc, table_cell_style)
                ])
            adjust_table = Table(table_data_adjust, colWidths=[25, 65, 60, 60, 55, 85, 170])
            adjust_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC2626')),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#FEF2F2')])
            ]))
            story.append(adjust_table)
        else:
            story.append(Paragraph("[오늘 조정 또는 보합 상태인 미흡 종목이 없습니다]", body_style))
    else:
        story.append(Paragraph("[전일 포착된 관심 종목이 없거나 복기 결과가 없습니다]", body_style))
        
    story.append(PageBreak())
    
    # 상세 면
    for idx, s in enumerate(stocks, 1):
        story.append(Paragraph(f"{s['name']} ({s['code']})", stock_name_style))
        story.append(Paragraph(f"- {s['pattern']}", pattern_subtitle_style))
        story.append(Paragraph(f"<b>소속 테마:</b> {get_stock_themes(s['code'])}", theme_subtitle_style))
        story.append(Spacer(1, 4))
        
        chart_path = os.path.join(charts_dir, f"{s['code']}.png")
        if os.path.exists(chart_path):
            story.append(Image(chart_path, width=440, height=200))
        else:
            story.append(Paragraph("[차트 파일을 찾을 수 없습니다]", body_style))
            
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<b>실전 대응 및 차트 관전 포인트:</b> {s['comment']}", comment_body_style))
        
        if idx < len(stocks) or comp_stocks:
            story.append(PageBreak())
            
    if comp_stocks:
        story.append(Paragraph(f"🎓 2부 상세 복기 (전일 {technique_name} 관심종목의 오늘 차트 흐름)", title_style))
        story.append(Spacer(1, 15))
        story.append(Paragraph("어제 선정되었던 예측형 관심종목들이 오늘 시장에서 어떤 봉을 완성하고 지지선을 지켰는지 차트를 통해 상세히 복기합니다.", body_style))
        story.append(PageBreak())
        
        for idx, s in enumerate(comp_stocks, 1):
            tag = "📈 [적중]" if s['max_profit'] >= 3.0 else "📉 [미흡/조정]"
            title_color = '#16A34A' if s['max_profit'] >= 3.0 else '#DC2626'
            stock_name_custom = ParagraphStyle(
                f"StockName_{s['code']}",
                parent=stock_name_style,
                textColor=colors.HexColor(title_color)
            )
            story.append(Paragraph(f"{tag} {s['name']} ({s['code']})", stock_name_custom))
            story.append(Paragraph(f"- 어제 공략 기법: {s['pattern']}", pattern_subtitle_style))
            story.append(Paragraph(f"<b>소속 테마:</b> {get_stock_themes(s['code'])}", theme_subtitle_style))
            story.append(Spacer(1, 4))
            
            chart_path = os.path.join(charts_dir, f"{s['code']}.png")
            if os.path.exists(chart_path):
                story.append(Image(chart_path, width=440, height=200))
            else:
                story.append(Paragraph("[차트 파일을 찾을 수 없습니다]", body_style))
                
            story.append(Spacer(1, 6))
            story.append(Paragraph(f"<b>어제 제시한 실전 대응 및 관전 포인트:</b> {s['prev_comment']}", comment_body_style))
            story.append(Spacer(1, 4))
            story.append(Paragraph(f"<b>오늘의 실전 결과 및 복기 포인트:</b> {s['result_desc']}", comment_body_style))
            
            if idx < len(comp_stocks):
                story.append(PageBreak())
            
    try:
        doc.build(list(story))
        print(f"[{date_str}] PDF 생성 완료 -> {output_pdf_path}")
    except PermissionError:
        print(f"[{date_str}] PDF 파일이 열려있거나 잠겨있습니다. 대체 파일명으로 저장을 시도합니다.")
        base, ext = os.path.splitext(output_pdf_path)
        for i in range(2, 100):
            alt_path = f"{base}_v{i}{ext}"
            try:
                alt_doc = SimpleDocTemplate(
                    alt_path,
                    pagesize=A4,
                    rightMargin=35, leftMargin=35,
                    topMargin=35, bottomMargin=35
                )
                alt_doc.build(list(story))
                print(f"[{date_str}] PDF 생성 완료 (대체 파일) -> {alt_path}")
                break
            except PermissionError:
                continue
