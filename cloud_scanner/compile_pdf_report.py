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

def build_pdf_report(target_stocks, charts_dir, output_pdf_path, report_title="이동평균선과 500억 봉의 비밀 분석 리포트", ma_stocks=None):
    print("PDF 리포트 생성 중...")
    
    font_path = "NanumGothic.ttf"
    font_bold_path = "NanumGothicBold.ttf"
    
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('Malgun', font_path))
    else:
        print("맑은 고딕 폰트가 시스템에 존재하지 않아 기본 폰트를 시도합니다.")
        
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
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='MalgunBold',
        fontSize=22,
        leading=28,
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
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#111827'),
        spaceAfter=4
    )
    
    pattern_subtitle_style = ParagraphStyle(
        'PatternSubtitle',
        fontName='MalgunBold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#DC2626'),
        spaceAfter=5
    )
    
    body_style = ParagraphStyle(
        'BodyText',
        parent=styles['Normal'],
        fontName='Malgun',
        fontSize=11,
        leading=17,
        textColor=colors.HexColor('#1F2937'),
        spaceAfter=10
    )
    
    table_cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Malgun',
        fontSize=8,
        leading=10,
        alignment=1
    )
    
    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='MalgunBold',
        fontSize=8,
        leading=10,
        alignment=1,
        textColor=colors.white
    )

    story = []
    
    # 1. 문서 제목
    story.append(Paragraph(report_title, title_style))
    today_str = datetime.datetime.today().strftime('%Y년 %m월 %d일')
    story.append(Paragraph(f"분석 기준일: {today_str} 장 마감 기준 | 프로그램 자동 스캔 및 AI 코멘트", subtitle_style))
    
    # 2. 요약 테이블
    story.append(Paragraph("📊 포착 종목 총괄 요약", section_title_style))
    
    table_data = [[
        Paragraph("종목명", table_header_style),
        Paragraph("종목코드", table_header_style),
        Paragraph("오늘 종가", table_header_style),
        Paragraph("등락률", table_header_style),
        Paragraph("상태 구분", table_header_style),
        Paragraph("기법 구분", table_header_style),
        Paragraph("기준일", table_header_style)
    ]]
    
    day_type_names = {0: "0일차 (당일출현)", 1: "1일차 (익일조정)", 2: "2일차 (이틀후조정)"}
    
    for s in target_stocks:
        day_str = day_type_names.get(s['day_type'], f"{s['day_type']}일차")
        candle_class = s.get('candle_class', '500억봉')
        table_data.append([
            Paragraph(s['name'], table_cell_style),
            Paragraph(s['code'], table_cell_style),
            Paragraph(f"{s['close']:,}원", table_cell_style),
            Paragraph(f"{s['rate']:+.2f}%", table_cell_style),
            Paragraph(day_str, table_cell_style),
            Paragraph(candle_class, table_cell_style),
            Paragraph(s['ref_date'], table_cell_style)
        ])
        
    if ma_stocks:
        for s in ma_stocks:
            table_data.append([
                Paragraph(s['name'], table_cell_style),
                Paragraph(s['code'], table_cell_style),
                Paragraph(f"{int(s['close']):,}원", table_cell_style),
                Paragraph(f"{s.get('rate', 0.0):+.2f}%", table_cell_style),
                Paragraph("이평선 근접", table_cell_style),
                Paragraph("15/20일선 근접", table_cell_style),
                Paragraph(s.get('ref_date', 'N/A'), table_cell_style)
            ])
        
    summary_table = Table(table_data, colWidths=[80, 60, 75, 55, 95, 80, 75])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F3F4F6')])
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 20))
    story.append(PageBreak())  # 첫 페이지는 깔끔하게 요약만 표기하고 페이지 넘김
    
    # 3. 개별 종목 분석 상세 카드
    for idx, s in enumerate(target_stocks, 1):
        day_str = day_type_names.get(s['day_type'], f"{s['day_type']}일차")
        
        # 타이틀 섹션
        story.append(Paragraph(f"#{idx:02d} {s['name']} ({s['code']})", stock_name_style))
        story.append(Paragraph(f"적용 상태: {day_str} | 기법 구분: {s.get('candle_class', '500억봉')} | 기준일: {s['ref_date']}", pattern_subtitle_style))
        story.append(Spacer(1, 5))
        
        # 팩트 데이터 테이블
        # 2열 구조 테이블로 정보 가독성 증대
        exp_ma = s['expected_ma']
        detail_data = [
            [
                Paragraph("<b>오늘 종가</b>", table_cell_style), Paragraph(f"{s['close']:,}원 ({s['rate']:+.2f}%)", table_cell_style),
                Paragraph("<b>오늘 저점</b>", table_cell_style), Paragraph(f"{s['low']:,}원", table_cell_style)
            ],
            [
                Paragraph("<b>거래량 비율</b>", table_cell_style), Paragraph(f"20일 평균 대비 {s['vol_ratio']:.1f}%", table_cell_style),
                Paragraph("<b>직전 전고점</b>", table_cell_style), Paragraph(f"{s['former_peak']:,}원", table_cell_style)
            ],
            [
                Paragraph("<b>예상 3일선</b>", table_cell_style), Paragraph(f"{exp_ma['ma3']:.0f}원 ({exp_ma['ma3_trend']})", table_cell_style),
                Paragraph("<b>예상 5일선</b>", table_cell_style), Paragraph(f"{exp_ma['ma5']:.0f}원 ({exp_ma['ma5_trend']})", table_cell_style)
            ],
            [
                Paragraph("<b>예상 8일선</b>", table_cell_style), Paragraph(f"{exp_ma['ma8']:.0f}원 ({exp_ma['ma8_trend']})", table_cell_style),
                Paragraph("<b>예상 20일선</b>", table_cell_style), Paragraph(f"{exp_ma['ma20']:.0f}원 ({exp_ma['ma20_trend']})", table_cell_style)
            ]
        ]
        
        detail_table = Table(detail_data, colWidths=[100, 160, 100, 160])
        detail_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F3F4F6')),
            ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#F3F4F6')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(detail_table)
        story.append(Spacer(1, 10))
        
        # 차트 이미지 삽입
        chart_path = os.path.join(charts_dir, f"{s['code']}.png")
        if os.path.exists(chart_path):
            img = Image(chart_path, width=480, height=288)
            img.hAlign = 'CENTER'
            story.append(img)
            story.append(Spacer(1, 10))
        else:
            story.append(Paragraph("[차트 이미지 누락]", table_cell_style))
            story.append(Spacer(1, 10))
            
        # AI 코멘트 섹션
        story.append(Paragraph("<b>💡 김일청의 실전 차트해설</b>", ParagraphStyle('CommentHeader', fontName='MalgunBold', fontSize=10, textColor=colors.HexColor('#1E3A8A'), spaceAfter=4)))
        
        comment_text = s.get('commentary', '분석 데이터를 계산하는 도중 오류가 발생했거나 AI의 분석을 불러오지 못했습니다.')
        story.append(Paragraph(comment_text, body_style))
        
        # 종목 구분선 추가 (마지막 종목이 아니거나 뒤이어 이평선 근접 종목이 있으면 페이지 넘김)
        if idx < len(target_stocks) or (ma_stocks and len(ma_stocks) > 0):
            story.append(PageBreak())
            
    # 4. 15일선/20일선 근접 종목 상세 카드
    if ma_stocks:
        for idx, s in enumerate(ma_stocks, len(target_stocks) + 1):
            # 타이틀 섹션
            story.append(Paragraph(f"#{idx:02d} {s['name']} ({s['code']})", stock_name_style))
            story.append(Paragraph(f"기법 구분: 15/20일선 근접 | 500억봉 기준일: {s.get('ref_date', 'N/A')}", pattern_subtitle_style))
            story.append(Spacer(1, 5))
            
            # 팩트 데이터 테이블 (이평선 근접 종목 전용 포맷)
            detail_data = [
                [
                    Paragraph("<b>오늘 종가</b>", table_cell_style), Paragraph(f"{int(s['close']):,}원 ({s.get('rate', 0.0):+.2f}%)", table_cell_style),
                    Paragraph("<b>오늘 저점</b>", table_cell_style), Paragraph(f"{int(s.get('low', 0)):,}원" if s.get('low') else "-", table_cell_style)
                ],
                [
                    Paragraph("<b>15일 이평선</b>", table_cell_style), Paragraph(f"{s['ma15']:.1f}원", table_cell_style),
                    Paragraph("<b>20일 이평선</b>", table_cell_style), Paragraph(f"{s['ma20']:.1f}원", table_cell_style)
                ],
                [
                    Paragraph("<b>15일선 근접</b>", table_cell_style), Paragraph("예" if s['near15'] else "아니오", table_cell_style),
                    Paragraph("<b>20일선 근접</b>", table_cell_style), Paragraph("예" if s['near20'] else "아니오", table_cell_style)
                ],
                [
                    Paragraph("<b>15일선 추세</b>", table_cell_style), Paragraph("우상향↑" if s['trend15_up'] else "우하향↓", table_cell_style),
                    Paragraph("<b>20일선 추세</b>", table_cell_style), Paragraph("우상향↑" if s['trend20_up'] else "우하향↓", table_cell_style)
                ]
            ]
            
            detail_table = Table(detail_data, colWidths=[100, 160, 100, 160])
            detail_table.setStyle(TableStyle([
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F3F4F6')),
                ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#F3F4F6')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(detail_table)
            story.append(Spacer(1, 10))
            
            # 차트 이미지 삽입
            chart_path = os.path.join(charts_dir, f"{s['code']}.png")
            if os.path.exists(chart_path):
                img = Image(chart_path, width=480, height=288)
                img.hAlign = 'CENTER'
                story.append(img)
                story.append(Spacer(1, 10))
            else:
                story.append(Paragraph("[차트 이미지 누락]", table_cell_style))
                story.append(Spacer(1, 10))
                
            # AI 코멘트 섹션
            story.append(Paragraph("<b>💡 김일청의 실전 차트해설</b>", ParagraphStyle('CommentHeader', fontName='MalgunBold', fontSize=10, textColor=colors.HexColor('#1E3A8A'), spaceAfter=4)))
            
            comment_text = s.get('commentary', '분석 데이터를 계산하는 도중 오류가 발생했거나 AI의 분석을 불러오지 못했습니다.')
            story.append(Paragraph(comment_text, body_style))
            
            # 종목 구분선 추가 (마지막 종목이 아니면 페이지 넘김)
            if idx < len(target_stocks) + len(ma_stocks):
                story.append(PageBreak())
            
    # PDF 빌드 실행
    doc.build(story)
    print(f"PDF 리포트 저장 성공: {output_pdf_path}")
    return True

if __name__ == "__main__":
    # 간단 테스트 데이터
    dummy_stocks = [
        {
            'code': '005930',
            'name': '삼성전자',
            'day_type': 1,
            'close': 85000,
            'rate': -1.2,
            'low': 84200,
            'vol_ratio': 45.2,
            'expected_ma': {
                'ma3': 85200.0, 'ma3_trend': '우하향',
                'ma5': 84800.0, 'ma5_trend': '우상향',
                'ma8': 84200.0, 'ma8_trend': '우상향',
                'ma20': 83500.0, 'ma20_trend': '우상향'
            },
            'former_peak': 88000,
            'ref_date': '2026-07-13',
            'commentary': "삼성전자는 어제 강력한 거래대금을 동반한 기준봉을 출현시킨 후, 오늘 5일선 위에서 숨고르기 조정을 하고 있습니다. 거래량이 20일 평균 대비 절반 이하로 안정되고 있으므로, 내일 예상 3일선 부근인 85,200원 내외를 지점 매집 맥점으로 노려보기 좋은 양음양 대형주 패턴입니다."
        }
    ]
    build_pdf_report(dummy_stocks, "./test_charts", "./test_report.pdf")
