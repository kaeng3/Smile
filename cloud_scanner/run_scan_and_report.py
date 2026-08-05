# -*- coding: utf-8 -*-
import os
import sys
import datetime
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

from scanner import get_full_market_list, get_prefiltered_market_list, scan_stocks_parallel
from ai_commentator_500m import get_ai_commentary, get_ai_commentary_ma_near
from generate_charts import make_chart
from compile_pdf_report import build_pdf_report

def main():
    parser = argparse.ArgumentParser(description="이동평균선과 500억 봉 및 150억 봉 통합 스캐너")
    parser.add_argument("date", nargs="?", default=None, help="스캔 타겟 날짜 (YYYYMMDD 형식, 예: 20260714)")
    parser.add_argument("-w", "--workers", type=int, default=40, help="병렬 분석용 스레드 개수 (기본 40)")
    
    args = parser.parse_args()
    
    # 1. 대상 날짜 결정
    if args.date:
        try:
            target_date = datetime.datetime.strptime(args.date, '%Y%m%d')
        except ValueError:
            print("올바른 날짜 형식이 아닙니다 (예: 20260714)")
            sys.exit(1)
    else:
        target_date = datetime.datetime.now()
        
    date_str = target_date.strftime('%Y%m%d')
    date_display = target_date.strftime('%Y-%m-%d')
    
    print(f"==========================================")
    print(f" [{date_display}] 500억봉 및 150억봉 통합 자동 분석 스크립트 실행")
    print(f"==========================================")
    
    # 2. 사전 필터링으로 종목 수 대폭 압축 (1단계: 거래대금 + 등락률)
    # 이 전략으로 2,500개 전체 종목을 보통 50~200개로 압축 후 상세 API 호출
    stocks = get_prefiltered_market_list(threshold_billion=150, change_pct_min=3.0)
    if not stocks:
        print("사전 필터링 후 포착 종목이 없습니다. 전체 종목으로 폴백합니다.")
        stocks = get_full_market_list()
    if not stocks:
        print("상장 종목 목록을 불러오지 못했습니다. 분석을 종료합니다.")
        sys.exit(1)
        
    print(f"사전 필터링된 {len(stocks)}개 종목 데이터 로드 성공.")
    
    # 3. 500억봉 스캔 수행
    print("\n--- [1단계] 500억봉 기법 스캔 시작 ---")
    results_500 = scan_stocks_parallel(
        stock_list=stocks,
        target_date=target_date,
        threshold_billion=500,
        max_workers=args.workers
    )
    for s in results_500:
        s['candle_class'] = '500억봉'
        
    # 4. 150억봉 스캔 수행
    print("\n--- [2단계] 150억봉 기법 스캔 시작 ---")
    results_150 = scan_stocks_parallel(
        stock_list=stocks,
        target_date=target_date,
        threshold_billion=150,
        max_workers=args.workers
    )
    
    # 5. 중복 제거 및 통합 리스트 구축
    # 500억봉 조건을 통과한 종목은 150억봉 결과에서 제외 처리
    codes_500 = set(x['code'] for x in results_500)
    results_150_only = []
    for s in results_150:
        if s['code'] not in codes_500:
            s['candle_class'] = '150억봉 (부수)'
            results_150_only.append(s)
            
    print(f"\n[중복 제거 통계] 500억봉: {len(results_500)}개, 순수 150억봉(부수): {len(results_150_only)}개")
    
    # 500억봉이 우선순위가 높으므로 앞에 먼저 다 붙이고, 150억봉을 뒤에 덧붙임
    scan_results = results_500 + results_150_only
    
    if not scan_results:
        print(f"\n[{date_display}] 조건에 만족하는 포착 종목이 없습니다. 리포트 작성을 생략합니다.")
        sys.exit(0)
        
    # 최종 보고서는 사용자 가이드라인에 의거 10~15개 최우수 종목으로 제한
    # 500억봉이 많을 경우 150억봉은 자동 컷오프
    if len(scan_results) > 15:
        print(f"포착 종목 수가 많아 최우수 관심 종목 15개로 필터링합니다 (총 {len(scan_results)}개 포착).")
        scan_results = scan_results[:15]
        
    # 6. 15일선/20일선 근접 종목 스캔 실행 (Subprocess 호출)
    print("\n--- [3단계] 15일선/20일선 근접 종목 스캔 시작 ---")
    import subprocess
    cwd_dir = r"C:/Users/pc/.gemini/antigravity/brain/93b3d6f1-dcf0-4b0a-9628-8dcfbaa39f1a"
    script_path = os.path.join(cwd_dir, "list_near_ma_today.py")
    try:
        subprocess.run([sys.executable, script_path], cwd=cwd_dir, capture_output=True, check=True)
    except Exception as e:
        print(f"이평선 근접 스캔 실행 실패: {e}")
        
    near_path = os.path.join(cwd_dir, "near_500b_report.json")
    ma_stocks = []
    if os.path.exists(near_path):
        try:
            with open(near_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        ma_stocks.append(json.loads(line))
        except Exception as e:
            print(f"이평선 근접 스캔 결과 읽기 실패: {e}")
            
    print(f"이평선 근접 종목 포착 수: {len(ma_stocks)}개")
    
    # 7. 차트 생성 (메인 스레드 순차 처리 - matplotlib 스레드 안전 보장)
    print("\n[차트 이미지 렌더링 시작 - 순차 처리]")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    charts_dir = os.path.join(current_dir, "charts")

    all_stocks = [(s, 'main') for s in scan_results] + [(s, 'ma') for s in ma_stocks]
    for idx, (s, kind) in enumerate(all_stocks, 1):
        code = s['code']
        name_clean = s['name'].lstrip('*')
        try:
            make_chart(code, name_clean, charts_dir, target_date)
            print(f"-> 차트 [{idx:02d}/{len(all_stocks)}] {name_clean} 완료")
        except Exception as e:
            print(f"[WARN] 차트 생성 실패 {name_clean}: {e}")

    # 8. AI 코멘트 수집 (병렬 처리 - 네트워크 I/O 위주라 스레드 안전)
    print("\n[AI 코멘트 수집 시작 - 병렬 처리]")

    def get_commentary(item):
        s, kind = item
        try:
            if kind == 'main':
                s['commentary'] = get_ai_commentary(s, date_display)
            else:
                s['commentary'] = get_ai_commentary_ma_near(s, date_display)
        except Exception as e:
            s['commentary'] = ""
            print(f"[WARN] AI 코멘트 실패 {s['name']}: {e}")
        return s

    max_ai_workers = 4  # Gemini 무료 개인 API 안정적 조정
    with ThreadPoolExecutor(max_workers=max_ai_workers) as executor:
        futures = {executor.submit(get_commentary, item): item for item in all_stocks}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            s = future.result()
            tag = s.get('candle_class', '이평선근접')
            print(f"-> AI [{done_count:02d}/{len(all_stocks)}] {s['name']} [{tag}] 완료")


    # 8. 스캔 결과 데이터 JSON 저장
    result_json_path = os.path.join(current_dir, f"scan_results_integrated_{date_str}.json")
    integrated_data = {
        "scan_results": scan_results,
        "ma_stocks": ma_stocks
    }
    with open(result_json_path, 'w', encoding='utf-8') as f:
        json.dump(integrated_data, f, ensure_ascii=False, indent=2)
    print(f"\n분석 결과 통합 데이터 JSON 저장 완료: {result_json_path}")
    
    # 9. PDF 리포트 컴파일
    report_title = "이동평균선과 500억봉 및 150억봉 분석 리포트"
    pdf_filename = f"이동평균선과_500억봉_및_150억봉_분석보고서_{date_str}.pdf"
    
    desktop_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(desktop_dir, exist_ok=True)
    pdf_path = os.path.join(desktop_dir, pdf_filename)
    
    try:
        build_pdf_report(
            target_stocks=scan_results,
            charts_dir=charts_dir,
            output_pdf_path=pdf_path,
            report_title=report_title,
            ma_stocks=ma_stocks
        )
    except PermissionError:
        timestamp_str = datetime.datetime.now().strftime('%H%M%S')
        pdf_filename_alt = f"이동평균선과_500억봉_및_150억봉_분석보고서_{date_str}_{timestamp_str}.pdf"
        pdf_path = os.path.join(desktop_dir, pdf_filename_alt)
        print(f"\n[알림] 대상 PDF 파일이 현재 열려 있어 덮어쓸 수 없습니다. 대체 파일명으로 저장합니다: {pdf_path}")
        build_pdf_report(
            target_stocks=scan_results,
            charts_dir=charts_dir,
            output_pdf_path=pdf_path,
            report_title=report_title,
            ma_stocks=ma_stocks
        )
    
    print(f"\n==========================================")
    print(f" [{date_display}] 통합 기법 리포트 작성이 완벽하게 끝났습니다!")
    print(f" 생성된 보고서: {pdf_path}")
    print(f"==========================================")

if __name__ == '__main__':
    main()
