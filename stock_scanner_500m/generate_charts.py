# -*- coding: utf-8 -*-
import os
import sys
import datetime
import matplotlib
matplotlib.use('Agg')  # 비메인 스레드(병렬처리) 환경에서 GUI 없이 파일 저장 가능하도록 설정
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

try:
    import FinanceDataReader as fdr
except ImportError:
    print("FinanceDataReader 라이브러리를 설치합니다...")
    os.system("pip install finance-datareader")
    import FinanceDataReader as fdr

def make_chart(code, name, save_dir, target_date):
    """
    지정된 주식의 캔들차트와 이평선(3, 5, 8, 20, 120, 224일선), 거래량 차트를 생성해 이미지로 저장합니다.
    """
    # 224일 이평선 연산을 위해 약 400일 전 데이터 로드
    start_date = target_date - datetime.timedelta(days=450)
    
    try:
        df = fdr.DataReader(code, start_date.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
        if len(df) < 224:
            # 224일선 계산을 위한 데이터 부족 시, 최대한 120일선이라도 확보하기 위해 최소 조건 변경
            df['MA224'] = df['Close'].rolling(window=len(df)).mean() # 임시 대체
        else:
            df['MA224'] = df['Close'].rolling(window=224).mean()
            
        # 이평선 연산
        df['MA3'] = df['Close'].rolling(window=3).mean()
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA8'] = df['Close'].rolling(window=8).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        df['MA120'] = df['Close'].rolling(window=120).mean()
        
        # 최근 40거래일 데이터만 추출하여 가독성 높은 차트 렌더링
        chart_df = df.tail(40).copy()
        if len(chart_df) < 5:
            return False
            
        # 한글 폰트 설정 (윈도우 기본 폰트인 맑은 고딕 사용)
        plt.rcParams['font.family'] = 'Malgun Gothic'
        plt.rcParams['axes.unicode_minus'] = False
        
        # 스타일 및 서브플롯 정의 (상단: 캔들 + 이평선, 하단: 거래량)
        fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 6), gridspec_kw={'height_ratios': [3, 1]})
        
        # X축을 날짜 대신 0부터 시작하는 연속 인덱스로 설정 (주말/공휴일 공백 제거)
        x_indices = range(len(chart_df))
        
        # 주요 이평선 플로팅
        ax1.plot(x_indices, chart_df['MA3'], label='3일선', color='#FF5555', linewidth=1.0, linestyle='--')
        ax1.plot(x_indices, chart_df['MA5'], label='5일선', color='#FF9900', linewidth=1.2)
        ax1.plot(x_indices, chart_df['MA8'], label='8일선', color='#00CC99', linewidth=1.2, linestyle='--')
        ax1.plot(x_indices, chart_df['MA20'], label='20일선 (생명선)', color='#0099FF', linewidth=1.5)
        ax1.plot(x_indices, chart_df['MA60'], label='60일선', color='#FF6600', linewidth=1.5)
        ax1.plot(x_indices, chart_df['MA120'], label='120일선', color='#9900CC', linewidth=1.5)
        if 'MA224' in chart_df:
            ax1.plot(x_indices, chart_df['MA224'], label='224일선 (장기저항)', color='#4B5563', linewidth=1.8, linestyle='-.')
            
        # 캔들차트 수동 드로잉
        width = 0.6
        for i in range(len(chart_df)):
            open_val = chart_df['Open'].iloc[i]
            close_val = chart_df['Close'].iloc[i]
            high_val = chart_df['High'].iloc[i]
            low_val = chart_df['Low'].iloc[i]
            
            # 상승 양봉: 빨강 (#FF3333), 하락 음봉: 파랑 (#3333FF)
            color = '#FF3333' if close_val >= open_val else '#3333FF'
            
            # 고점-저점 꼬리선
            ax1.vlines(i, low_val, high_val, color=color, linewidth=1.2)
            
            # 시가-종가 몸통 사각형
            bottom = min(open_val, close_val)
            height = abs(open_val - close_val)
            if height == 0:
                height = 1
                
            rect = plt.Rectangle(
                (i - width/2, bottom), 
                width, 
                height, 
                facecolor=color, 
                edgecolor=color,
                zorder=3
            )
            ax1.add_patch(rect)
            
        ax1.grid(True, linestyle='--', alpha=0.5)
        ax1.legend(loc='upper left', fontsize=8)
        ax1.set_title(f"{name} ({code}) - 이동평균선 & 500억봉 기법 차트", fontsize=13, fontweight='bold')
        ax1.tick_params(axis='y', labelsize=9)
        
        # 2. 하단: 거래량 바차트
        vol_colors = ['#FF3333' if chart_df['Close'].iloc[i] >= chart_df['Open'].iloc[i] else '#3333FF' for i in range(len(chart_df))]
        ax2.bar(x_indices, chart_df['Volume'], color=vol_colors, width=width, zorder=3)
        ax2.grid(True, linestyle='--', alpha=0.5)
        ax2.set_ylabel("거래량", fontsize=10)
        ax2.tick_params(axis='both', labelsize=9)
        
        # X축 날짜 포맷팅 (5일 단위 틱)
        step = 5
        tick_indices = list(range(0, len(chart_df), step))
        tick_labels = [chart_df.index[idx].strftime('%m-%d') for idx in tick_indices]
        ax2.set_xticks(tick_indices)
        ax2.set_xticklabels(tick_labels)
        
        plt.tight_layout()
        
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            
        save_path = os.path.join(save_dir, f"{code}.png")
        plt.savefig(save_path, dpi=120, facecolor='white', bbox_inches='tight')
        plt.close('all')
        
        # RGBA → RGB 변환 (ReportLab은 RGBA PNG를 빈칸으로 렌더링함)
        try:
            from PIL import Image as PILImage
            img_pil = PILImage.open(save_path)
            if img_pil.mode == 'RGBA':
                background = PILImage.new('RGB', img_pil.size, (255, 255, 255))
                background.paste(img_pil, mask=img_pil.split()[3])
                background.save(save_path, 'PNG')
        except Exception:
            pass
        
        return True
    except Exception as e:
        # print(f"차트 이미지 생성 실패 ({code}): {e}")
        pass
    return False

if __name__ == "__main__":
    # 로컬 간단 테스트
    target_dt = datetime.datetime(2026, 7, 14)
    make_chart("005930", "삼성전자", "./test_charts", target_dt)
