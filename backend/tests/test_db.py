"""DB の初期化。"""
from __future__ import annotations

import multiprocessing
from pathlib import Path


def _init(path: str) -> None:
    from core import db

    db.init_db(Path(path))


def test_init_db_from_many_processes_at_once(tmp_path: Path):
    # gunicorn の worker が同時に起動したときに "database is locked" で落ちないこと
    path = str(tmp_path / "kazayomi.db")
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_init, args=(path,)) for _ in range(6)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    assert [p.exitcode for p in procs] == [0] * 6
