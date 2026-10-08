# -*- coding: utf-8 -*-
"""
archive_store.py — 영구 보관 데이터를 'archive' 브랜치에 '이력을 남기며' 쌓는다.

data 브랜치(매번 통째로 덮어씀, 5거래일 보관)와 달리 archive 브랜치는
커밋마다 이전 커밋을 부모로 두어 변경 이력이 남는다. 실수해도 이전 버전으로 되돌릴 수 있다.
현재 보관 대상: event_archive/events-YYYY-MM.jsonl (500억봉 AI 분석 이벤트, 월별)

사용법 (저장소 루트에서):
  python archive_store.py pull    archive 브랜치 내용을 작업 폴더의 event_archive/에 푼다
  python archive_store.py push    event_archive/ 의 변경을 archive 브랜치에 커밋해 올린다
"""
import os
import sys
import time
import tempfile
import subprocess

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
BRANCH = 'archive'
REMOTE_REF = f'refs/remotes/origin/{BRANCH}'
FOLDER = 'event_archive'
PULLED_MARKER = os.path.join(ROOT, '.archive_pulled')
IDENT = {'GIT_AUTHOR_NAME': 'GitHub Action', 'GIT_AUTHOR_EMAIL': 'action@github.com',
         'GIT_COMMITTER_NAME': 'GitHub Action', 'GIT_COMMITTER_EMAIL': 'action@github.com'}


def git(*args, env=None, input=None, check=True):
    r = subprocess.run(['git', *args], cwd=ROOT, env=env, input=input, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} 실패: {r.stderr.strip()}")
    return r


def fetch():
    if not git('ls-remote', '--heads', 'origin', BRANCH).stdout.strip():
        return None
    git('fetch', '-q', '--depth', '1', 'origin', f'+refs/heads/{BRANCH}:{REMOTE_REF}')
    return git('rev-parse', REMOTE_REF).stdout.strip()


def pull():
    sha = fetch()
    os.makedirs(os.path.join(ROOT, FOLDER), exist_ok=True)
    if sha:
        archive = subprocess.Popen(['git', 'archive', sha], cwd=ROOT, stdout=subprocess.PIPE)
        subprocess.run(['tar', '-x', '-C', ROOT], stdin=archive.stdout, check=True)
        archive.stdout.close()
        if archive.wait() != 0:
            raise RuntimeError('git archive 실패')
    with open(PULLED_MARKER, 'w') as f:
        f.write(sha or 'none')
    print(f'[archive] {"받음 " + sha[:7] if sha else "브랜치가 아직 없어 새로 시작"}')


def push(attempts=4):
    if not os.path.exists(PULLED_MARKER):
        raise SystemExit('[archive] 이번 실행에서 pull하지 않아 올리기를 중단합니다(기존 기록 보호).')
    files = []
    for dirpath, _, names in os.walk(os.path.join(ROOT, FOLDER)):
        files += [os.path.relpath(os.path.join(dirpath, n), ROOT).replace(os.sep, '/') for n in names]
    if not files:
        print('[archive] 올릴 파일이 없습니다.')
        return
    for attempt in range(1, attempts + 1):
        base = fetch()
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, 'index'), **IDENT)
            git('read-tree', base, env=env) if base else git('read-tree', '--empty', env=env)
            # 파일은 추가/교체만 한다(지우지 않음). 월별 파일이라 다른 달은 그대로 남는다.
            git('--literal-pathspecs', 'add', '-f', '--pathspec-from-file=-', '--pathspec-file-nul',
                env=env, input='\0'.join(sorted(files)))
            tree = git('write-tree', env=env).stdout.strip()
            if base and tree == git('rev-parse', f'{base}^{{tree}}').stdout.strip():
                print('[archive] 바뀐 내용이 없습니다.')
                return
            parent = ['-p', base] if base else []
            commit = git('commit-tree', tree, *parent, '-m', f'archive: {time.strftime("%Y-%m-%d %H:%M")}',
                         env=env).stdout.strip()
        r = git('push', '-q', 'origin', f'{commit}:refs/heads/{BRANCH}', check=False)
        if r.returncode == 0:
            print(f'[archive] 파일 {len(files)}개 반영 ({commit[:7]})')
            return
        print(f'[archive] 충돌로 다시 시도 ({attempt}/{attempts})')
        time.sleep(3 * attempt)
    raise SystemExit('[archive] 올리지 못했습니다.')


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in ('pull', 'push'):
        raise SystemExit(__doc__)
    pull() if sys.argv[1] == 'pull' else push()
