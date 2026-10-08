# -*- coding: utf-8 -*-
"""
data_store.py — 생성 데이터를 main이 아닌 'data' 브랜치에 커밋 하나로만 보관한다.

main 브랜치에는 코드와 사람이 만드는 입력 데이터(뉴스 원본, 테마 DB)만 두고,
매일/매주 생성되는 데이터(차트, PDF, 스캔 결과 등)는 data 브랜치에 '최신 상태 1벌'만
남긴다. 매번 부모 없는 커밋으로 통째로 덮어쓰므로 git 이력이 쌓이지 않는다.
5거래일 보관은 기존 cleanup_artifacts.py가 작업 폴더에서 처리한다.

사용법 (저장소 루트에서):
  python data_store.py pull               data 브랜치 내용을 작업 폴더에 푼다
  python data_store.py push <담당>        담당 파일만 교체해서 data 브랜치에 올린다
  python data_store.py site <출력폴더>     main 코드 + data를 합쳐 사이트 배포 폴더를 만든다
"""
import os
import sys
import glob
import time
import tempfile
import subprocess

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
BRANCH = 'data'
REMOTE_REF = f'refs/remotes/origin/{BRANCH}'
# pull에 성공했다는 표시. 이게 없는데 data 브랜치가 이미 있으면 push를 거부한다
# (데이터를 못 받은 빈 작업 폴더 기준으로 덮어써서 5일치를 지우는 사고 방지).
PULLED_MARKER = os.path.join(ROOT, '.data_pulled')

# 워크플로우별로 '자기가 만드는' 파일. push 때 이 범위만 교체하므로
# 다른 워크플로우가 올린 파일은 건드리지 않는다. (폴더는 그 안의 파일 전체)
OWNERS = {
    'daily': [
        'charts', '*.pdf', 'cloud_scanner/scan_results_*.json',
        'scan_history.json', 'daily_issues.json', 'featured_stock_news.json',
        'ai_summary_archive.json',  # 종목별 AI 요약 이력: 5일 정리 대상이 아닌 영구 보관 파일
        'latest_prices.json', 'stock_overview.json', 'ma_proximity.json', 'ma_proximity_podosi.json', 'theme_bundles.json',
        'debug_scan_error.txt',
    ],
    'new_scanner': ['new_scanner/results/history.json'],
    'weekly': ['stock_financials.json', 'stock_shareholders.json', 'stock_sector.json'],
}


def git(*args, env=None, input=None, check=True):
    result = subprocess.run(['git', *args], cwd=ROOT, env=env, input=input,
                            capture_output=True, text=isinstance(input, str) or input is None)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} 실패: {result.stderr.strip()}")
    return result


def remote_branch_exists():
    out = git('ls-remote', '--heads', 'origin', BRANCH).stdout.strip()
    return bool(out)


def fetch():
    """data 브랜치 최신 커밋 sha. 브랜치가 아직 없으면 None.
    브랜치가 있는데 받기에 실패하면 예외 — 빈 데이터로 진행해 기존 데이터를 덮어쓰는 걸 막는다."""
    if not remote_branch_exists():
        return None
    git('fetch', '-q', '--depth', '1', 'origin', f'+refs/heads/{BRANCH}:{REMOTE_REF}')
    return git('rev-parse', REMOTE_REF).stdout.strip()


def extract(commit, dest):
    """커밋의 파일들을 dest에 푼다(main의 git 인덱스는 건드리지 않음)."""
    os.makedirs(dest, exist_ok=True)
    archive = subprocess.Popen(['git', 'archive', commit], cwd=ROOT, stdout=subprocess.PIPE)
    subprocess.run(['tar', '-x', '-C', dest], stdin=archive.stdout, check=True)
    archive.stdout.close()
    if archive.wait() != 0:
        raise RuntimeError(f'git archive {commit} 실패')


def pull():
    sha = fetch()
    if not sha:
        with open(PULLED_MARKER, 'w') as f:
            f.write('none')
        print(f'[data] {BRANCH} 브랜치가 아직 없어 받을 데이터가 없습니다.')
        return
    extract(sha, ROOT)
    with open(PULLED_MARKER, 'w') as f:
        f.write(sha)
    print(f'[data] {BRANCH} 브랜치 데이터를 작업 폴더에 풀었습니다 ({sha[:7]}).')


def pathspecs(patterns):
    """git rm/add용 경로 지정. 폴더는 그 아래 전체, 와일드카드는 해당 위치에서만."""
    return [f':(glob){p}/**' if '*' not in p and os.path.splitext(p)[1] == '' else f':(glob){p}' for p in patterns]


def owned_files(patterns):
    files = []
    for p in patterns:
        full = os.path.join(ROOT, p)
        if '*' not in p and os.path.isdir(full):
            for dirpath, _, names in os.walk(full):
                files += [os.path.relpath(os.path.join(dirpath, n), ROOT) for n in names]
        else:
            files += [os.path.relpath(f, ROOT) for f in glob.glob(full) if os.path.isfile(f)]
    return sorted(set(f.replace(os.sep, '/') for f in files))


def push(owner, attempts=4):
    if owner not in OWNERS:
        raise SystemExit(f'알 수 없는 담당: {owner} (가능: {", ".join(OWNERS)})')
    if not os.path.exists(PULLED_MARKER) and remote_branch_exists():
        raise SystemExit(f'[data] {owner}: 이번 실행에서 데이터를 받지(pull) 않아 올리기를 중단합니다. '
                         '(빈 상태로 덮어써 기존 데이터를 지우는 것을 막기 위함)')
    patterns = OWNERS[owner]
    files = owned_files(patterns)
    ident = {'GIT_AUTHOR_NAME': 'GitHub Action', 'GIT_AUTHOR_EMAIL': 'action@github.com',
             'GIT_COMMITTER_NAME': 'GitHub Action', 'GIT_COMMITTER_EMAIL': 'action@github.com'}
    for attempt in range(1, attempts + 1):
        base = fetch()
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, 'index'), **ident)
            if base:
                git('read-tree', base, env=env)
            else:
                git('read-tree', '--empty', env=env)
            git('rm', '-r', '-q', '-f', '--cached', '--ignore-unmatch', '--', *pathspecs(patterns), env=env)
            if files:
                git('--literal-pathspecs', 'add', '-f', '--pathspec-from-file=-', '--pathspec-file-nul', env=env,
                    input='\0'.join(files))
            tree = git('write-tree', env=env).stdout.strip()
            if base and tree == git('rev-parse', f'{base}^{{tree}}').stdout.strip():
                print(f'[data] {owner}: 바뀐 내용이 없어 올리지 않습니다.')
                return
            message = f'data({owner}): {time.strftime("%Y-%m-%d %H:%M")}'
            commit = git('commit-tree', tree, '-m', message, env=env).stdout.strip()  # 부모 없음 = 이력 안 쌓임
        lease = f'--force-with-lease=refs/heads/{BRANCH}:{base or ""}'
        result = git('push', '-q', lease, 'origin', f'{commit}:refs/heads/{BRANCH}', check=False)
        if result.returncode == 0:
            print(f'[data] {owner}: 파일 {len(files)}개 반영해서 {BRANCH} 브랜치에 올렸습니다 ({commit[:7]}).')
            return
        print(f'[data] {owner}: 다른 작업이 먼저 올려서 다시 합칩니다 ({attempt}/{attempts}).')
        time.sleep(3 * attempt)
    raise SystemExit(f'[data] {owner}: {attempts}번 시도했지만 올리지 못했습니다.')


def site(outdir):
    """main 코드(HEAD) + data 브랜치를 합치고, 뉴스 원본을 종목별 파일로 나눈 배포 폴더."""
    extract('HEAD', outdir)
    sha = fetch()
    if sha:
        extract(sha, outdir)
    else:
        print(f'[data] 경고: {BRANCH} 브랜치가 없어 생성 데이터 없이 배포합니다.')
    source = os.path.join(outdir, 'stock_news_history.json')
    if os.path.exists(source):
        import json
        from split_news_history import write_split
        with open(source, encoding='utf-8') as f:
            written, _ = write_split(json.load(f), os.path.join(outdir, 'news'))
        os.remove(source)  # 사이트는 news/{코드}.json만 쓴다
        print(f'[data] 종목별 뉴스 파일 {written}개 생성')
    print(f'[data] 배포 폴더 준비 완료: {outdir}')


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in ('pull', 'push', 'site'):
        raise SystemExit(__doc__)
    if sys.argv[1] == 'pull':
        pull()
    elif sys.argv[1] == 'push':
        push(sys.argv[2] if len(sys.argv) > 2 else '')
    else:
        site(sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, '_site'))
