import csv as _csv

import pytest

import hl_track_record as htr
from dashboard import data_provider as dp


# 3 天的假 portfolio（ms 時戳，每天一筆即可被 to_daily 收成 3 點 → metrics n_days=2）
FAKE_PORTFOLIO = [
    ["allTime", {"accountValueHistory": [
        [0,           "1000.0"],
        [86400000,    "1010.0"],
        [172800000,   "1025.0"],
    ]}],
]


def _write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["date", "account_value_usd"])
        for d, v in rows:
            w.writerow([d, f"{v:.6f}"])


def test_live_success_sets_source_live_and_refreshes_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(htr, "fetch_portfolio", lambda addr: FAKE_PORTFOLIO)
    csv_path = tmp_path / "equity_curve.csv"

    data = dp.get_dashboard_data("0xabc", csv_path=str(csv_path))

    assert data.source == "live"
    assert csv_path.exists()                      # 快取被刷新
    assert data.equity[-1] == pytest.approx(1025.0)
    assert len(data.days) == 3


def test_live_failure_falls_back_to_csv(monkeypatch, tmp_path):
    def _raise(addr):
        raise ConnectionError("boom")
    monkeypatch.setattr(htr, "fetch_portfolio", _raise)
    csv_path = tmp_path / "equity_curve.csv"
    _write_csv(csv_path, [("2026-06-16", 1000.0), ("2026-06-17", 1010.0), ("2026-06-18", 1025.0)])

    data = dp.get_dashboard_data("0xabc", csv_path=str(csv_path))

    assert data.source == "cached"
    assert data.equity[-1] == pytest.approx(1025.0)


def test_no_live_and_no_csv_raises(monkeypatch, tmp_path):
    def _raise(addr):
        raise ConnectionError("boom")
    monkeypatch.setattr(htr, "fetch_portfolio", _raise)
    missing = tmp_path / "nope.csv"

    with pytest.raises(dp.DashboardDataUnavailable):
        dp.get_dashboard_data("0xabc", csv_path=str(missing))


def test_metrics_and_equity_share_one_source(monkeypatch, tmp_path):
    """同源同基準：指標卡的數字必須與圖表 equity 陣列一致（全域原則 #1）。"""
    monkeypatch.setattr(htr, "fetch_portfolio", lambda addr: FAKE_PORTFOLIO)
    csv_path = tmp_path / "equity_curve.csv"

    data = dp.get_dashboard_data("0xabc", csv_path=str(csv_path))

    assert data.metrics["start_equity"] == pytest.approx(data.equity[0])
    assert data.metrics["end_equity"] == pytest.approx(data.equity[-1])
    assert data.metrics["n_days"] == len(data.equity) - 1
