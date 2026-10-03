from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", path],
        cwd=REPO,
        check=False,
    )
    return result.returncode == 0


def test_runtime_secrets_cache_and_generated_history_are_ignored() -> None:
    private_paths = [
        ".env",
        "new_scanner/.env",
        "new_scanner/data/cache/daily/005930.csv.gz",
        "new_scanner/data/cache/.kis_token.json",
        "new_scanner/state/sent.json",
    ]

    assert all(_is_ignored(path) for path in private_paths)
    # 결과 이력은 생성 데이터라 main이 아닌 data 브랜치에 보관(data_store.py)
    assert _is_ignored("new_scanner/results/history.json")
