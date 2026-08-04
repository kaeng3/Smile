import FinanceDataReader as fdr
import datetime

codes = {
    '001000': '신라섬유',
    '004540': '깨끗한나라',
    '014990': '인디에프',
    '024940': 'PN풍년',
    '030960': '양지사',
    '047770': '코데즈컴바인',
    '066910': '손오공',
    '241590': '화승엔터프라이즈',
    '270520': '케이뱅크',
    '408900': '뷰티스킨',
    '460930': '현대힘스'
}

target_date = datetime.datetime(2026, 7, 16)
long_start = target_date - datetime.timedelta(days=220)

for code, name in codes.items():
    df = fdr.DataReader(code, long_start.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
    if len(df) < 5: continue
    
    row0 = df.iloc[-1]
    row1 = df.iloc[-2]
    
    rate = ((row0['Close'] - row1['Close']) / row1['Close']) * 100
    amt = (row0['Close'] * row0['Volume']) / 1e9
    is_yang = row0['Close'] > row0['Open']
    
    if is_yang and 5.0 <= rate <= 30.0:
        print(f"MATCH: {name} ({code}) -> Rate: +{rate:.2f}%, Amt: {amt:.2f}B, Close: {row0['Close']}")
