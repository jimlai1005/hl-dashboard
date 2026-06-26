#!/usr/bin/env python3
"""
hl_track_record.py
------------------
Pull a Hyperliquid wallet's account-value history straight from the public
`info` API and compute an institution-grade performance report
(Sharpe / Sortino / Calmar / MaxDD), including the STANDARD ERROR on Sharpe
so you never oversell a small sample to a CFA/FRM audience.

Usage:
    python hl_track_record.py                 # uses WALLET below
    python hl_track_record.py 0xYOURADDRESS   # or pass an address

No API key, no auth — this is all public on-chain data.
Requires:  pip install requests numpy

Design note (decoupled by layer, so each piece is unit-testable):
    fetch_portfolio()      -> the ONLY function that touches the network
    extract_equity_curve() -> pure parsing
    to_daily()             -> pure transform
    compute_metrics()      -> pure math (feed it any equity array in tests)
    print_report/save_csv  -> presentation
"""

from __future__ import annotations

import sys
import json
import csv
from dataclasses import dataclass

import requests
import numpy as np

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
INFO_URL = "https://api.hyperliquid.xyz/info"
WALLET = "0x1A1d5eF3256e1A7de2db2082D7A1eEb976c90111"
RISK_FREE_ANNUAL = 0.0      # crypto convention; set e.g. 0.04 for a T-bill RF
PERIODS_PER_YEAR = 365      # crypto trades every day, not 252
CSV_OUT = "equity_curve.csv"


# --------------------------------------------------------------------------
# 1. Data layer  (only this talks to the network)
# --------------------------------------------------------------------------
def fetch_portfolio(address: str) -> list:
    """POST {'type': 'portfolio'} to the Hyperliquid info endpoint.

    Returns a raw list of [label, data] pairs, e.g.
        [["day", {...}], ["week", {...}], ["month", {...}], ["allTime", {...}]]
    where each data block carries an `accountValueHistory` of [ts_ms, value_str].
    """
    resp = requests.post(
        INFO_URL,
        headers={"Content-Type": "application/json"},
        json={"type": "portfolio", "user": address},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


# --------------------------------------------------------------------------
# 2. Parsing + transform  (pure)
# --------------------------------------------------------------------------
def extract_equity_curve(portfolio: list, window: str = "allTime"):
    """Pull accountValueHistory for `window`. Returns (timestamps, values)."""
    by_label = {label: data for label, data in portfolio}
    if window not in by_label:
        raise KeyError(f"window '{window}' not found. available: {list(by_label)}")
    avh = by_label[window].get("accountValueHistory", [])
    if not avh:
        raise ValueError(f"no accountValueHistory in window '{window}'")
    ts = np.array([int(t) for t, _ in avh], dtype="datetime64[ms]")
    vals = np.array([float(v) for _, v in avh], dtype=float)
    return ts, vals


def to_daily(ts, vals):
    """Collapse to one end-of-day (last) account value per UTC day."""
    days = ts.astype("datetime64[D]")
    daily = {}
    for d, v in zip(days, vals):
        daily[d] = v  # last write per day wins -> end-of-day value
    ordered = sorted(daily.items())
    d_arr = np.array([d for d, _ in ordered], dtype="datetime64[D]")
    v_arr = np.array([v for _, v in ordered], dtype=float)
    return d_arr, v_arr


# --------------------------------------------------------------------------
# 3. Metrics  (pure math — hand it any equity array in a test)
# --------------------------------------------------------------------------
@dataclass
class Metrics:
    n_days: int
    start: str
    end: str
    start_equity: float
    end_equity: float
    total_return: float
    cagr: float
    ann_vol: float
    sharpe: float
    sharpe_se: float
    sortino: float
    max_drawdown: float
    calmar: float
    daily_win_rate: float
    best_day: float
    worst_day: float
    suspected_cashflows: int


def compute_metrics(days, equity) -> Metrics:
    rets = np.diff(equity) / equity[:-1]
    n = len(rets)

    # Flag >50% single-day jumps as possible deposit/withdraw (distorts returns)
    suspected = int(np.sum(np.abs(rets) > 0.5))

    rf_daily = RISK_FREE_ANNUAL / PERIODS_PER_YEAR
    excess = rets - rf_daily
    mean_d = excess.mean()
    std_d = rets.std(ddof=1) if n > 1 else float("nan")

    downside = rets[rets < rf_daily]
    dstd_d = downside.std(ddof=1) if len(downside) > 1 else float("nan")

    # Daily Sharpe, then annualise by sqrt(periods) — the correct iid scaling
    sr_daily = mean_d / std_d if std_d else float("nan")
    sharpe = sr_daily * np.sqrt(PERIODS_PER_YEAR)
    sortino = (mean_d / dstd_d) * np.sqrt(PERIODS_PER_YEAR) if dstd_d else float("nan")

    # Standard error of Sharpe (Lo 2002, iid approx): SE_daily then annualise
    if n > 1 and np.isfinite(sr_daily):
        se_daily = np.sqrt((1 + 0.5 * sr_daily ** 2) / n)
        sharpe_se = se_daily * np.sqrt(PERIODS_PER_YEAR)
    else:
        sharpe_se = float("nan")

    peak = np.maximum.accumulate(equity)
    max_dd = (equity / peak - 1.0).min()

    total_return = equity[-1] / equity[0] - 1.0
    years = n / PERIODS_PER_YEAR
    cagr = (equity[-1] / equity[0]) ** (1 / years) - 1 if years > 0 else float("nan")
    ann_vol = std_d * np.sqrt(PERIODS_PER_YEAR) if np.isfinite(std_d) else float("nan")
    calmar = cagr / abs(max_dd) if max_dd < 0 else float("nan")

    return Metrics(
        n_days=n, start=str(days[0]), end=str(days[-1]),
        start_equity=float(equity[0]), end_equity=float(equity[-1]),
        total_return=total_return, cagr=cagr, ann_vol=ann_vol,
        sharpe=sharpe, sharpe_se=sharpe_se, sortino=sortino,
        max_drawdown=max_dd, calmar=calmar,
        daily_win_rate=float(np.mean(rets > 0)),
        best_day=float(rets.max()), worst_day=float(rets.min()),
        suspected_cashflows=suspected,
    )


# --------------------------------------------------------------------------
# 4. Presentation
# --------------------------------------------------------------------------
def save_csv(days, equity, path=CSV_OUT):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "account_value_usd"])
        for d, v in zip(days, equity):
            w.writerow([str(d), f"{v:.6f}"])


def print_report(m: Metrics):
    pct = lambda x: f"{x * 100:,.2f}%"
    print("=" * 58)
    print(f"  Hyperliquid Track Record  |  {WALLET[:6]}…{WALLET[-4:]}")
    print("=" * 58)
    print(f"  Window            {m.start}  ->  {m.end}")
    print(f"  Trading days (N)  {m.n_days}")
    print(f"  Equity            ${m.start_equity:,.2f}  ->  ${m.end_equity:,.2f}")
    print("-" * 58)
    print(f"  Total return      {pct(m.total_return)}")
    print(f"  CAGR (annual)     {pct(m.cagr)}")
    print(f"  Ann. volatility   {pct(m.ann_vol)}")
    print(f"  Max drawdown      {pct(m.max_drawdown)}")
    print("-" * 58)
    print(f"  Sharpe (annual)   {m.sharpe:,.2f}   +/- {m.sharpe_se:,.2f}  (1 s.e.)")
    print(f"  Sortino (annual)  {m.sortino:,.2f}")
    print(f"  Calmar            {m.calmar:,.2f}")
    print(f"  Daily win rate    {pct(m.daily_win_rate)}")
    print(f"  Best / worst day  {pct(m.best_day)} / {pct(m.worst_day)}")
    print("=" * 58)
    if m.n_days < 60:
        print(f"  [!] N={m.n_days} is small. The +/-{m.sharpe_se:,.2f} band on Sharpe is")
        print( "      wide — present this as an EARLY live record, not a")
        print( "      headline number. Let it compound.")
    if m.suspected_cashflows:
        print(f"  [!] {m.suspected_cashflows} day(s) with >50% equity jump = possible")
        print( "      deposit/withdraw. If so, tell me — we switch to a")
        print( "      deposit-adjusted (time-weighted) return.")
    print()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    addr = sys.argv[1] if len(sys.argv) > 1 else WALLET
    print(f"Fetching portfolio for {addr} ...")
    portfolio = fetch_portfolio(addr)

    for window in ("allTime", "month", "week", "day"):
        try:
            ts, vals = extract_equity_curve(portfolio, window)
            print(f"Using window: {window}  ({len(vals)} raw points)")
            break
        except (KeyError, ValueError):
            continue
    else:
        print("Could not find account-value history. Raw payload (first 2k chars):")
        print(json.dumps(portfolio, indent=2)[:2000])
        return

    days, equity = to_daily(ts, vals)
    if len(days) < 2:
        print("Not enough daily points yet to compute returns.")
        return

    print_report(compute_metrics(days, equity))
    save_csv(days, equity)
    print(f"Equity curve written to {CSV_OUT}  (hand this file to Claude).")


if __name__ == "__main__":
    main()
