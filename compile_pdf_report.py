# -*- coding: utf-8 -*-
import os
import sys
import datetime
import json

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
except ImportError:
    print("reportlab 라이브러리를 설치합니다...")
    os.system("pip install reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

def build_pdf_report(target_stocks, charts_dir, output_pdf_path):
    print("PDF 리포트 생성 시작...")
    
    font_path = "C:\\Windows\\Fonts\\malgun.ttf"
    font_bold_path = "C:\\Windows\\Fonts\\malgunbd.ttf"
    
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('Malgun', font_path))
    else:
        print("맑은 고딕 폰트 없음. 기본 폰트 사용.")
        
    if os.path.exists(font_bold_path):
        pdfmetrics.registerFont(TTFont('MalgunBold', font_bold_path))
    else:
        pdfmetrics.registerFont(TTFont('MalgunBold', font_path))

    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=A4,
        rightMargin=35, leftMargin=35,
        topMargin=35, bottomMargin=35
    )
    
    styles = getSampleStyleSheet()
    
    # === 사용자 요청에 맞춰 대폭 확장한 폰트 스타일 ===
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
    
    # 개별 종목 페이지용 심플 타이틀 스타일
    stock_name_style = ParagraphStyle(
        'StockName',
        fontName='MalgunBold',
        fontSize=22,
        leading=26,
        textColor=colors.HexColor('#111827'),
        spaceAfter=4
    )
    
    pattern_subtitle_style = ParagraphStyle(
        'PatternSubtitle',
        fontName='MalgunBold',
        fontSize=14,
        leading=18,
        textColor=colors.HexColor('#DC2626'), # 강조용 레드
        spaceAfter=5
    )
    
    theme_subtitle_style = ParagraphStyle(
        'ThemeSubtitle',
        fontName='MalgunBold',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#4B5563'), # 어두운 회색
        spaceAfter=15
    )
    
    # 9pt에서 12pt로 키우고 줄간격을 18pt로 확보한 코멘트 스타일
    body_style = ParagraphStyle(
        'BodyText',
        parent=styles['Normal'],
        fontName='Malgun',
        fontSize=12,
        leading=18,
        textColor=colors.HexColor('#1F2937'),
        spaceAfter=10
    )
    
    table_cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Malgun',
        fontSize=9,
        leading=12,
        alignment=1
    )
    
    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='MalgunBold',
        fontSize=9,
        leading=12,
        alignment=1,
        textColor=colors.white
    )

    # 테마 JSON DB 로드 및 보완 정보 정의
    themes_json_path = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34\alphasquare_themes.json"
    themes_db = {}
    if os.path.exists(themes_json_path):
        try:
            with open(themes_json_path, 'r', encoding='utf-8') as f:
                themes_db = json.load(f).get('themes', {})
        except Exception as e:
            print("테마 DB 로딩 실패:", e)

    # 잘려나간 데이터 및 미포함 기입용 수동 매핑 백업
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

    story = []
    
    # 1. 메인 타이틀
    story.append(Paragraph("김일청의 양음양(feat.60Ma)", title_style))
    today_str = datetime.datetime.today().strftime('%Y년 %m월 %d일')
    story.append(Paragraph(f"기준일: {today_str} 장 마감 기준 | 프로그램 자동 스캔 및 리포트 발행", subtitle_style))
    
    # 예측형/완성형 분류
    pred_stocks = [s for s in target_stocks if s['match_type'] == 'predictive']
    comp_stocks = [s for s in target_stocks if s['match_type'] == 'completed']

    # 2. 내일 공략주 요약 테이블
    story.append(Paragraph("🔮 1부: 내일 공략 관심 종목 (오늘 저거래량 음봉/눌림목 예측형)", section_title_style))
    
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
        theme_str = get_stock_themes(s['code'])
        table_data_pred.append([
            Paragraph(f"{idx:02d}", table_cell_style),
            Paragraph(s['name'], table_cell_style),
            Paragraph(s['code'], table_cell_style),
            Paragraph(f"{s['close']:,}원", table_cell_style),
            Paragraph(f"{s['rate']:.2f}%" if 'rate' in s and s['rate'] is not None else '-', table_cell_style),
            Paragraph(s['pattern'], table_cell_style),
            Paragraph(theme_str, table_cell_style)
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
    story.append(Spacer(1, 15))
    
    # 3. 오늘 완성 공부용 테이블
    story.append(Paragraph("🎓 2부: 금일 패턴 완성 종목 (과거 포착 후 오늘 폭등 완료 복기용)", section_title_style))
    
    table_data_comp = [[
        Paragraph("순번", table_header_style),
        Paragraph("종목명", table_header_style),
        Paragraph("종목코드", table_header_style),
        Paragraph("오늘 종가", table_header_style),
        Paragraph("오늘 상승률", table_header_style),
        Paragraph("완성 기법", table_header_style),
        Paragraph("소속 테마", table_header_style)
    ]]
    
    for idx, s in enumerate(comp_stocks, 1):
        theme_str = get_stock_themes(s['code'])
        table_data_comp.append([
            Paragraph(f"{idx:02d}", table_cell_style),
            Paragraph(s['name'], table_cell_style),
            Paragraph(s['code'], table_cell_style),
            Paragraph(f"{s['close']:,}원", table_cell_style),
            Paragraph(f"+{s['rate']:.2f}%" if 'rate' in s and s['rate'] is not None else '-', table_cell_style),
            Paragraph(s['pattern'], table_cell_style),
            Paragraph(theme_str, table_cell_style)
        ])
        
    comp_table = Table(table_data_comp, colWidths=[25, 75, 55, 65, 50, 110, 140])
    comp_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4B5563')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F3F4F6')])
    ]))
    story.append(comp_table)
    
    story.append(PageBreak())
    
    # 4. 상세 페이지 (사용자가 요청한 심플 구조 + 확대 폰트 적용 + 소속 테마 추가)
    for idx, s in enumerate(target_stocks, 1):
        # 타이틀 간소화: [종목명 (코드)]
        story.append(Paragraph(f"{s['name']} ({s['code']})", stock_name_style))
        
        # 기법 간소화: [- 패턴명]
        story.append(Paragraph(f"- {s['pattern']}", pattern_subtitle_style))
        
        # 소속 테마 정보 기입
        theme_str = get_stock_themes(s['code'])
        story.append(Paragraph(f"<b>소속 테마:</b> {theme_str}", theme_subtitle_style))
        story.append(Spacer(1, 5))
        
        # 차트 이미지 삽입
        chart_img_path = os.path.join(charts_dir, f"{s['code']}.png")
        if os.path.exists(chart_img_path):
            story.append(Image(chart_img_path, width=480, height=270))
        else:
            story.append(Paragraph("[차트 이미지를 찾을 수 없습니다]", body_style))
            
        story.append(Spacer(1, 10))
        
        # 실전 대응 코멘트 (12pt로 굵고 크게 출력)
        commentary_html = f"<b>실전 대응 및 차트 관전 포인트:</b> {s['comment']}"
        story.append(Paragraph(commentary_html, body_style))
        
        if idx < len(target_stocks):
            story.append(PageBreak())
            
    try:
        doc.build(list(story))
        print(f"PDF 리포트 생성 완료: {output_pdf_path}")
    except PermissionError:
        print("PDF 파일이 열려 있어 덮어쓰기에 실패했습니다. 대체 이름으로 저장합니다.")
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
                print(f"PDF 리포트 생성 완료 (대체 파일): {alt_path}")
                break
            except PermissionError:
                continue

if __name__ == "__main__":
    target_stocks = [
        # === 1부 예측형 (내일 매수 공략용) ===
        {
            'code': '002960', 'name': '한국쉘석유', 'close': 497500, 'rate': -3.77, 'match_type': 'predictive',
            'pattern': 'Pattern 1',
            'comment': '최근 수급 유입 후 오늘 -3.77% 조정을 보였으나, 60일선과 120일선 수렴 밴드 내에서 거래량이 바짝 마른 전형적인 지지 캔들을 형성했습니다. 내일 눌림목 분할 진입에 최적의 위치입니다.'
        },
        {
            'code': '001790', 'name': '대한제당', 'close': 2795, 'rate': -3.79, 'match_type': 'predictive',
            'pattern': 'Pattern 1',
            'comment': '최근 대량 거래량 양봉 이후 오늘 거래량이 전일 대비 17.4% 수준으로 바짝 마르며 60일선 바로 위에서 음봉 조정을 마쳤습니다. 60일선(2,740원)을 손절 기준으로 삼고 종가 부근 또는 내일 분할 진입하기에 아주 안전한 매수 타점입니다.'
        },
        {
            'code': '010960', 'name': '삼호개발', 'close': 3970, 'rate': -10.99, 'match_type': 'predictive',
            'pattern': 'Pattern 1',
            'comment': '오늘 종가(3,970원)는 5일선(4,148원)을 하향 이탈하며 저항선으로 바뀌었습니다. 대신 아래에 강하게 형성된 60일선(3,640원) 및 120일선(3,780원) 수렴 지지 밴드 영역까지 깊은 조정을 준 상태로, 장기 이평선을 신뢰하고 밴드 하단 분할 매집으로 대응하는 구간입니다.'
        },
        {
            'code': '457600', 'name': '벡트', 'close': 2410, 'rate': -7.31, 'match_type': 'predictive',
            'pattern': 'Pattern 1',
            'comment': '60일선 이동평균선 돌파 후 출현한 첫 저거래량 음봉 조정 캔들입니다. 5일선 및 60일선 위에서의 지지력이 탄탄하므로 내일 장중 반등을 노린 종가/시초가 진입이 유리합니다.'
        },
        {
            'code': '226320', 'name': '잇츠한불', 'close': 10380, 'rate': -5.64, 'match_type': 'predictive',
            'pattern': 'Pattern 2',
            'comment': '윗꼬리가 긴 대량거래 양봉 이후 오늘 거래량이 마른 음봉 눌림을 주었습니다. 내일 장 초반 5일선(10,150원) 부근으로 하락 조정을 줄 때 분할 진입하여 윗꼬리 매물대를 향한 단기 차익을 노리기 좋은 구간입니다.'
        },
        {
            'code': '204620', 'name': '글로벌텍스프리', 'close': 5140, 'rate': 0.19, 'match_type': 'predictive',
            'pattern': 'Pattern 2',
            'comment': '게임조아 실제 추천주로, 어제 돌파 대량 양봉 이후 오늘 거래량이 45%로 마르며 5일선 지지를 받았습니다. 종가 기준 십자 도지 캔들로 지지를 지켰으므로, 내일 장 초반 5일선 부근 눌림 시 매입 전략이 매우 유효합니다.'
        },
        {
            'code': '362320', 'name': '청담글로벌', 'close': 4700, 'rate': -0.63, 'match_type': 'predictive',
            'pattern': 'Pattern 2',
            'comment': '어제 돌파 흐름 이후 5일선 위에서 거래량을 숨기며 횡보 조정을 거치고 있는 급소 영역입니다. 내일 장 초반 5일선 부근 지지력을 확인하며 분할 진입하기 좋습니다.'
        },
        {
            'code': '092730', 'name': '네오팜', 'close': 18920, 'rate': -3.12, 'match_type': 'predictive',
            'pattern': 'Pattern 3',
            'comment': '거래량이 추가로 마르며 기간 조정 횡보를 지속하고 있습니다. 120일선 부근인 18,500원 ~ 19,000원 밴드 구간에서 다분할 매수로 물량을 모아간 뒤 양봉 반출을 기다리는 전략이 적합합니다.'
        },
        {
            'code': '052460', 'name': '아이크래프트', 'close': 3200, 'rate': 0.00, 'match_type': 'predictive',
            'pattern': 'Pattern 3',
            'comment': '기준봉 형성 이후 4영업일 연속으로 거래량이 계단식 하락하여 매도세가 완전히 소멸되었음을 보여줍니다. 5일선 부근에서 가격이 견조하게 지지되고 있어 매집 진입하기 아주 매력적인 기회입니다.'
        },
        {
            'code': '013360', 'name': '일성건설', 'close': 1636, 'rate': -2.97, 'match_type': 'predictive',
            'pattern': '60일의 법칙',
            'comment': '5일선(1,823원)이 깨지며 단기 저항으로 작용하고 있으나, 60일 지지선(1,631원) 바로 1% 직전 위에서 오늘 종가(1,636원)가 극적으로 멈춰 섰습니다. 60일선 손절 기준을 타이트하게 잡고 진입하기에 가장 좋은 손익비 타점입니다.'
        },
        {
            'code': '214450', 'name': '파마리서치', 'close': 309000, 'rate': -1.28, 'match_type': 'predictive',
            'pattern': '60일의 법칙',
            'comment': '오늘 종가 기준 60일선(311,633원)을 살짝 이탈하는 휩소(속임수) 캔들을 형성했습니다. 5일선(326,300원) 아래에 있으므로 저항을 염두에 두고, 전저점 바닥(255,000원) 지지를 신뢰하며 넓은 밴드에서 물량을 천천히 모아가는 전략이 유효합니다.'
        },
        
        # === 2부 완성형 (공부 복기용) ===
        {
            'code': '005360', 'name': '모나미', 'close': 1707, 'rate': 24.69, 'match_type': 'completed',
            'pattern': 'Pattern 2',
            'comment': '어제 윗꼬리 대량거래 이후 오늘 오전 장 시작 후 5일선 눌림목(최저 1,281원)을 터치하고 오후에 그대로 24.69% 폭등하여 마감했습니다. 윗꼬리 매물을 완벽히 지지받아 당일 폭발한 정석적인 수급 상승 캔들로 차트 눈을 키우기 위한 훌륭한 공부용 팩트 자료입니다.'
        }
    ]
    
    artifact_dir = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34"
    charts_dir = os.path.join(artifact_dir, "charts")
    
    desktop_dir = r"C:\Users\pc\Desktop\양음양 리포트"
    output_pdf_path = os.path.join(desktop_dir, "김일청의_양음양(feat.60Ma)_20260709.pdf")
    
    from ai_commentator import get_ai_commentary
    for s in target_stocks:
        s['comment'] = get_ai_commentary(s['code'], s['name'], s['pattern'], s['close'], s['rate'], s['match_type'], datetime.datetime(2026, 7, 9))
        
    build_pdf_report(target_stocks, charts_dir, output_pdf_path)
