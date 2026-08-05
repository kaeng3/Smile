import json

with open('scan_history.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

print('=== 양음양 코멘트 오타 확인 ===')
for s in d['20260805']['yey']:
    comment = s.get('comment', '')
    name = s.get('name','')
    issues = []
    if '0원' in comment:
        issues.append('0원 데이터 오류')
    if '100%' in comment and '거래량은 평균 대비 100%' in comment:
        issues.append('거래량 100% 오류')
    if issues:
        print(f'[{name}] 이슈: {issues}')
        print(f'  {comment[:200]}')
        print()

print('=== 500억봉 코멘트 샘플 ===')
for s in d['20260805']['b500m'][:3]:
    name = s.get('name','')
    comment = s.get('comment','')
    print(f'[{name}] comment 길이: {len(comment)}자')
    print(f'  {comment[:200]}')
    print()
