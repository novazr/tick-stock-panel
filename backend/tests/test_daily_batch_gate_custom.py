"""日K 补数/扩展历史接口: 自定义日K源 (如 yahoo_us) 也应放行, 不要求 TickFlow Pro+。"""
from app.api import kline


class _Cap:
    def __init__(self, ok: bool):
        self.ok = ok

    def has(self, _cap) -> bool:
        return self.ok


def test_tickflow_capability_allows(monkeypatch):
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "tickflow")
    assert kline._daily_batch_allowed(_Cap(True)) is True
    assert kline._daily_batch_allowed(_Cap(False)) is False


def test_custom_daily_provider_allows_without_tickflow(monkeypatch):
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "yahoo_us")
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, ds: name == "yahoo_us" and ds == "daily",
    )
    assert kline._daily_batch_allowed(_Cap(False)) is True


def test_custom_provider_without_daily_dataset_denied(monkeypatch):
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "foo")
    monkeypatch.setattr("app.data_providers.custom.provider_has_dataset", lambda name, ds: False)
    assert kline._daily_batch_allowed(_Cap(False)) is False
