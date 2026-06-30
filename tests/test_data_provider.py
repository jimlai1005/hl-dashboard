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


# 鏈上首筆已含首日獲利（1007.26）的情境：真實入金本金較低
FAKE_PORTFOLIO_GAINED = [
    ["allTime", {"accountValueHistory": [
        [0,           "1007.26"],   # 06-16 EOD，已含首日獲利
        [86400000,    "1017.31"],
        [172800000,   "1042.91"],
    ]}],
]


def test_principal_anchors_first_point_and_keeps_cache_truthful(monkeypatch, tmp_path):
    """本金錨定：曲線起點對齊真實入金本金，末點不動，且快取保留真實鏈上值。"""
    monkeypatch.setattr(htr, "fetch_portfolio", lambda addr: FAKE_PORTFOLIO_GAINED)
    csv_path = tmp_path / "equity_curve.csv"

    data = dp.get_dashboard_data("0xabc", csv_path=str(csv_path), principal=1000.0)

    assert data.equity[0] == 1000.0                      # 起點錨回本金
    assert data.metrics["start_equity"] == 1000.0
    assert data.equity[-1] == pytest.approx(1042.91)     # 末點不受影響
    assert data.metrics["total_return"] == pytest.approx(1042.91 / 1000.0 - 1)

    # 快取檔保留真實鏈上首筆（未被本金錨定汙染）
    rows = list(_csv.DictReader(open(csv_path)))
    assert float(rows[0]["account_value_usd"]) == pytest.approx(1007.26)


def test_default_principal_is_1000(monkeypatch, tmp_path):
    """預設本金即 $1000（不傳 principal 也會錨定）。"""
    assert dp.PRINCIPAL == 1000.0
    monkeypatch.setattr(htr, "fetch_portfolio", lambda addr: FAKE_PORTFOLIO_GAINED)
    csv_path = tmp_path / "equity_curve.csv"

    data = dp.get_dashboard_data("0xabc", csv_path=str(csv_path))

    assert data.equity[0] == 1000.0


def test_get_benchmarks_rebases_and_aligns(monkeypatch):
    days = ["2026-06-16", "2026-06-17", "2026-06-18"]
    fake = {
        "BTC": [("2026-06-16", 100.0), ("2026-06-17", 110.0), ("2026-06-18", 90.0)],
        "xyz:XYZ100": [("2026-06-16", 50.0), ("2026-06-17", 55.0), ("2026-06-18", 60.0)],
    }
    monkeypatch.setattr(dp, "_fetch_candles", lambda coin, t0, t1: fake[coin])

    out = dp.get_benchmarks(days, base=1000.0)

    assert len(out["BTC"]) == len(days)
    assert out["BTC"][0] == 1000.0                    # 首點 == base
    assert out["BTC"][1] == pytest.approx(1100.0)     # 110/100 * 1000
    assert out["BTC"][2] == pytest.approx(900.0)      # 90/100 * 1000
    assert out["XYZ100"][0] == 1000.0
    assert out["XYZ100"][2] == pytest.approx(1200.0)  # 60/50 * 1000


def test_get_benchmarks_forward_fills_missing_day(monkeypatch):
    days = ["2026-06-16", "2026-06-17", "2026-06-18"]
    fake = {  # BTC 缺 06-17
        "BTC": [("2026-06-16", 100.0), ("2026-06-18", 120.0)],
        "xyz:XYZ100": [("2026-06-16", 50.0), ("2026-06-17", 55.0), ("2026-06-18", 60.0)],
    }
    monkeypatch.setattr(dp, "_fetch_candles", lambda coin, t0, t1: fake[coin])

    out = dp.get_benchmarks(days, base=1000.0)

    assert out["BTC"][1] == out["BTC"][0]             # 缺日沿用前一日收盤
    assert out["BTC"][2] == pytest.approx(1200.0)     # 120/100 * 1000
