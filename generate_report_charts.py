import os
import sys
import datetime
import socket
socket.setdefaulttimeout(10.0)
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

def make_chart(code, name, save_dir):
    """지정된 주식의 캔들차트와 이평선, 거래량 차트를 생성해 이미지로 저장합니다."""
    today = datetime.datetime.today()
    start_date = today - datetime.timedelta(days=220)  # 120영업일(MA120) 확보를 위해 220일 전부터 가져옴
    
    try:
        df = fdr.DataReader(code, start_date.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'))
        if len(df) < 60:
            return False
            
        # 이평선 계산
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        df['MA120'] = df['Close'].rolling(window=120).mean()
        
        # 최근 40일 데이터로 제한 (차트 가독성을 높이기 위해)
        chart_df = df.tail(40).copy()
        
        # 한글 폰트 설정 (윈도우 기본 폰트인 맑은 고딕 사용)
        plt.rcParams['font.family'] = 'Malgun Gothic'
        plt.rcParams['axes.unicode_minus'] = False
        
        # 스타일 정의
        fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 6), gridspec_kw={'height_ratios': [3, 1]})
        
        # 1. 상단: 이평선 및 캔들 차트
        # X축을 날짜 대신 연속된 인덱스 번호(0, 1, 2...)로 대체하여 주말 공백 제거
        x_indices = range(len(chart_df))
        ax1.plot(x_indices, chart_df['MA5'], label='5일선', color='#FF9900', linewidth=1.2)
        ax1.plot(x_indices, chart_df['MA10'], label='10일선', color='#0099FF', linewidth=1.2)
        ax1.plot(x_indices, chart_df['MA60'], label='60일선', color='#339900', linewidth=1.5)
        ax1.plot(x_indices, chart_df['MA120'], label='120일선', color='#9900CC', linewidth=1.5)
        
        # 수동 캔들 그리기 (Matplotlib 기본 기능 사용)
        width = 0.6  # 봉 너비
        for i in range(len(chart_df)):
            open_val = chart_df['Open'].iloc[i]
            close_val = chart_df['Close'].iloc[i]
            high_val = chart_df['High'].iloc[i]
            low_val = chart_df['Low'].iloc[i]
            
            # 상승(양봉): 빨강 (#FF3333), 하락(음봉): 파랑 (#3333FF)
            color = '#FF3333' if close_val >= open_val else '#3333FF'
            
            # 꼬리 그리기 (고가-저가 세로선)
            ax1.vlines(i, low_val, high_val, color=color, linewidth=1.2)
            
            # 몸통 그리기 (시가-종가 사각형)
            bottom = min(open_val, close_val)
            height = abs(open_val - close_val)
            if height == 0:
                height = 1  # 두께 보정
                
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
        ax1.legend(loc='upper left')
        ax1.set_title(f"{name} ({code}) - 양음양 & 60일선의 법칙 분석", fontsize=14, fontweight='bold')
        ax1.tick_params(axis='y', labelsize=9)
        
        # 2. 하단: 거래량 차트
        vol_colors = ['#FF3333' if chart_df['Close'].iloc[i] >= chart_df['Open'].iloc[i] else '#3333FF' for i in range(len(chart_df))]
        ax2.bar(x_indices, chart_df['Volume'], color=vol_colors, width=width, zorder=3)
        ax2.grid(True, linestyle='--', alpha=0.5)
        ax2.set_ylabel("거래량", fontsize=10)
        ax2.tick_params(axis='both', labelsize=9)
        
        # X축 날짜 포맷 설정 (인덱스 번호 위치에 실제 날짜 라벨 대입)
        step = 5
        tick_indices = list(range(0, len(chart_df), step))
        tick_labels = [chart_df.index[idx].strftime('%m-%d') for idx in tick_indices]
        ax2.set_xticks(tick_indices)
        ax2.set_xticklabels(tick_labels)
        
        plt.tight_layout()
        
        # 이미지 저장 경로 설정
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            
        save_path = os.path.join(save_dir, f"{code}.png")
        plt.savefig(save_path, dpi=120)
        plt.close()
        print(f"차트 생성 완료: {save_path}")
        return True
    except Exception as e:
        print(f"차트 생성 실패 ({code}): {e}")
        return False

if __name__ == "__main__":
    # 금일 포착 종목 코드 리스트
    target_stocks = [
        {'code': '002960', 'name': '한국쉘석유'},
        {'code': '001790', 'name': '대한제당'},
        {'code': '010960', 'name': '삼호개발'},
        {'code': '457600', 'name': '벡트'},
        {'code': '226320', 'name': '잇츠한불'},
        {'code': '005360', 'name': '모나미'},
        {'code': '204620', 'name': '글로벌텍스프리'},
        {'code': '362320', 'name': '청담글로벌'},
        {'code': '092730', 'name': '네오팜'},
        {'code': '052460', 'name': '아이크래프트'},
        {'code': '013360', 'name': '일성건설'},
        {'code': '214450', 'name': '파마리서치'},
        {'code': '144960', 'name': '뉴파워프라즈마'}
    ]
    
    # 아티팩트 디렉터리 경로
    artifact_dir = r"C:\Users\pc\.gemini\antigravity\brain\c6997abd-5ccd-40e2-89a8-b4346393ae34"
    charts_dir = os.path.join(artifact_dir, "charts")
    
    for s in target_stocks:
        make_chart(s['code'], s['name'], charts_dir)
