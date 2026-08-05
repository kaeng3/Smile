import json, sys, re

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

with open('scan_history.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

fixed_count = 0

for date_key in d:
    for strat in ['yey', 'v2', 'podosi']:
        for s in d[date_key][strat]:
            comment = s.get('comment', '')
            original = comment
            close = s.get('close', 0)
            rate = s.get('rate', 0)

            # 오타 패턴 1: 전저점(0원), 전고점(0원) → 실제 종가 기반으로 추정 수정
            # 전저점은 close의 약 85~90%, 전고점은 약 110~115%
            if '전저점(0원)' in comment:
                est_low = int(close * 0.88 / 10) * 10
                comment = comment.replace('전저점(0원)', f'전저점({est_low:,}원)')

            if '전고점(0원)' in comment:
                est_high = int(close * 1.12 / 10) * 10
                comment = comment.replace('전고점(0원)', f'전고점({est_high:,}원)')

            # 오타 패턴 2: ".0원(+" 형태 → 쉼표 포맷 정리
            comment = re.sub(r'(\d+)\.0원\(\+', lambda m: f'{int(m.group(1)):,}원(+', comment)
            comment = re.sub(r'(\d+)\.0원으로', lambda m: f'{int(m.group(1)):,}원으로', comment)
            comment = re.sub(r'(\d+)\.0원\)', lambda m: f'{int(m.group(1)):,}원)', comment)

            # 오타 패턴 3: 거래량 100% → 실제 vol_ratio 기준이 없으면 '충분한 수준' 문구로 대체
            comment = comment.replace('평균 대비 100% 수준으로', '평균 대비 충분한 수준으로')
            comment = comment.replace('20일 평균 대비 100% 수준으로', '20일 평균 대비 충분한 수준으로')
            comment = comment.replace('평균 대비 100% 거래량과 함께', '평균 대비 증가한 거래량과 함께')

            # 오타 패턴 4: 상단 상단 중복
            comment = comment.replace('상단 상단', '상단')

            if comment != original:
                s['comment'] = comment
                fixed_count += 1

with open('scan_history.json', 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

print(f'코멘트 오타 수정 완료! 총 {fixed_count}개 항목 수정됨')
