"""單一資料來源：即時抓 Hyperliquid，失敗 fallback 讀 CSV，並在同一處用同一條
equity 陣列產生圖表點與指標（同源同基準，對齊全域原則 #1）。
唯一碰網路的地方（對齊全域原則 #5）；併入 hl-copytrader 時只需換掉這裡的 fetch。"""
from __future__ import annotations

import csv as _csv
import dataclasses
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

import hl_track_record as htr

CSV_PATH = "equity_curve.csv"

# 起始本金：鏈上 deposit 驗證為 $1000（tx 0x2302a8fc…610a1）。鏈上首筆快照
# $1007.26 已含首日獲利，故把曲線起點錨回真實本金，投資人才看得到從 $1,000
# 起算的完整報酬。env HL_DASHBOARD_PRINCIPAL 可覆寫；設為空字串可關閉錨定。
_principal_env = os.getenv("HL_DASHBOARD_PRINCIPAL", "1000")
PRINCIPAL = float(_principal_env) if _principal_env else None


class DashboardDataUnavailable(Exception):
    """既無即時資料、也無 CSV 快取，或資料點不足以計算指標。"""


@dataclass
class DashboardData:
    days: list      # list[str]  "YYYY-MM-DD"
    equity: list    # list[float]
    metrics: dict   # dataclasses.asdict(Metrics)
    source: str     # "live" | "cached"
    as_of: str      # ISO8601 UTC


def _read_csv_curve(path: str):
    days, equity = [], []
    with open(path, newline="") as f:
        for row in _csv.DictReader(f):
            days.append(row["date"])
            equity.append(float(row["account_value_usd"]))
    return (np.array(days, dtype="datetime64[D]"),
            np.array(equity, dtype=float))


def _live_curve(address: str):
    portfolio = htr.fetch_portfolio(address)
    for window in ("allTime", "month", "week", "day"):
        try:
            ts, vals = htr.extract_equity_curve(portfolio, window)
            return htr.to_daily(ts, vals)
        except (KeyError, ValueError):
            continue
    raise ValueError("portfolio 中找不到可用的 accountValueHistory")


def get_dashboard_data(address: str, csv_path: str = CSV_PATH,
                       principal: float | None = PRINCIPAL) -> DashboardData:
    source = "live"
    try:
        days, equity = _live_curve(address)
        htr.save_csv(days, equity, csv_path)   # 順手刷新快取（保留真實鏈上值）
    except Exception:
        source = "cached"
        if not os.path.exists(csv_path):
            raise DashboardDataUnavailable("無即時資料且無 CSV 快取")
        days, equity = _read_csv_curve(csv_path)

    # 本金錨定：把曲線起點對齊到真實入金本金（同源同基準，全域原則 #1）。
    # 只動「顯示用」的回傳值，不汙染上面剛存的快取（快取維持真實鏈上序列）。
    if principal is not None and len(equity) > 0:
        equity = equity.copy()
        equity[0] = principal

    if len(days) < 2:
        raise DashboardDataUnavailable("資料點不足，無法計算報酬指標")

    metrics = dataclasses.asdict(htr.compute_metrics(days, equity))
    return DashboardData(
        days=[str(d) for d in days],
        equity=[float(v) for v in equity],
        metrics=metrics,
        source=source,
        as_of=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
