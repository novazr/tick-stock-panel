"""向前扩展历史: 美股实例的基准 ETF (指数存储) 也要一并向前补。"""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.services import extend_history as eh


def _repo(tmp_path, index_days: list[str]):
    for day in index_days:
        (tmp_path / "kline_index_daily" / f"date={day}").mkdir(parents=True)
    return SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))


@pytest.fixture
def calls(monkeypatch):
    seen: list[dict] = []

    def fake_sync(repo, capset, start_date=None, end_date=None, **kwargs):
        seen.append({"start": start_date, "end": end_date})
        return 123

    from app.services import index_sync
    monkeypatch.setattr(index_sync, "sync_and_persist_index_daily", fake_sync)
    return seen


def _market(monkeypatch, value: str) -> None:
    import app.market
    monkeypatch.setattr(app.market, "active_market", lambda: value)


def test_us_instance_backfills_benchmarks_up_to_their_own_earliest_day(tmp_path, monkeypatch, calls):
    _market(monkeypatch, "us")
    repo = _repo(tmp_path, ["2025-11-21", "2025-11-24", "2026-11-20"])
    written = eh.extend_benchmark_history(repo, object(), date(1996, 11, 28))
    assert written == 123
    # 右端是指数自己的最早日期, 与个股已扩展到哪里无关
    assert calls == [{"start": datetime(1996, 11, 28), "end": datetime(2025, 11, 21)}]


def test_cn_instance_keeps_previous_behaviour(tmp_path, monkeypatch, calls):
    _market(monkeypatch, "cn")
    repo = _repo(tmp_path, ["2025-11-21"])
    assert eh.extend_benchmark_history(repo, object(), date(1996, 11, 28)) == 0
    assert calls == []


def test_nothing_to_do_when_benchmarks_already_reach_the_target(tmp_path, monkeypatch, calls):
    _market(monkeypatch, "us")
    repo = _repo(tmp_path, ["1996-01-02", "2026-11-20"])
    assert eh.extend_benchmark_history(repo, object(), date(1996, 11, 28)) == 0
    assert calls == []


def test_nothing_to_do_without_local_index_data(tmp_path, monkeypatch, calls):
    _market(monkeypatch, "us")
    assert eh.extend_benchmark_history(_repo(tmp_path, []), object(), date(1996, 11, 28)) == 0
    assert calls == []
