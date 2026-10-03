# -*- coding: utf-8 -*-
"""
split_news_history.py
stock_news_history.json(종목코드 -> 뉴스 목록, 약 81MB)을 news/{종목코드}.json으로 나눈다.

사이트가 81MB 전체를 매번 받는 대신, 종목 상세 창을 열 때 그 종목 파일(평균 수십 KB)만
받도록 하기 위함. 원본 파일은 그대로 두므로 parse_all_evening_news.py로 원본을 갱신해
올리는 기존 방식은 바뀌지 않는다. 원본 내용이 지난번과 같으면(MD5 비교) 아무것도 하지 않는다.
"""
import os
import sys
import json
import hashlib

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(BASE_DIR, 'stock_news_history.json')
OUT_DIR = os.path.join(BASE_DIR, 'news')
HASH_FILE = os.path.join(OUT_DIR, '_source_md5.txt')


def file_md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def write_split(news_db, out_dir):
    """news_db(dict: code -> list)를 out_dir/{code}.json으로 쓰고, 원본에 없는 종목 파일은 지운다."""
    os.makedirs(out_dir, exist_ok=True)
    keep = set()
    for code, items in news_db.items():
        name = f'{code}.json'
        keep.add(name)
        with open(os.path.join(out_dir, name), 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, separators=(',', ':'))
    removed = 0
    for name in os.listdir(out_dir):
        if name.endswith('.json') and name not in keep:
            os.remove(os.path.join(out_dir, name))
            removed += 1
    return len(keep), removed


def main():
    if not os.path.exists(SOURCE):
        print('[뉴스 분할] stock_news_history.json이 없어 건너뜁니다.')
        return
    md5 = file_md5(SOURCE)
    if os.path.exists(HASH_FILE) and open(HASH_FILE, encoding='utf-8').read().strip() == md5:
        print('[뉴스 분할] 원본이 바뀌지 않아 건너뜁니다.')
        return
    with open(SOURCE, 'r', encoding='utf-8') as f:
        news_db = json.load(f)
    written, removed = write_split(news_db, OUT_DIR)
    with open(HASH_FILE, 'w', encoding='utf-8') as f:
        f.write(md5)
    print(f'[뉴스 분할] {written}개 종목 파일 작성, {removed}개 삭제 -> news/')


if __name__ == '__main__':
    main()
