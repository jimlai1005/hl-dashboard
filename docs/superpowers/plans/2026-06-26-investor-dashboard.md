# 投資人績效儀表 Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把既有的 Hyperliquid 績效報表做成一個輕量 Flask 單頁網頁儀表，給投資人看淨值曲線與機構級指標。

**Architecture:** Flask app 重用 `hl_track_record.py` 的純函數。單一資料來源 `data_provider.get_dashboard_data()`：即時抓 Hyperliquid，失敗則 fallback 讀 `equity_curve.csv`，並在同一處用同一條 equity 陣列產生圖表點與指標（同源同基準）。前端用 Chart.js 畫線、卡片呈現指標、底部誠實揭露樣本數。

**Tech Stack:** Python 3.9、Flask、requests、numpy、Chart.js（CDN）、pytest。

**合併相容性（保留不執行）：** `data_provider.py` 是唯一碰網路處。未來搬進 `hl-copytrader/src/` 時只需把 fetch 換成 `src/monitor.py` 的 `_post` 與 `src/config.py` 慣例。

---

## 檔案結構

```
golden-tea/
├── hl_track_record.py            # 既有；不需改動，純函數直接 import
├── equity_curve.csv              # 既有；當斷線備援快取
├── requirements.txt              # 新增：flask + requests + numpy
├── dashboard/
│   ├── __init__.py               # 空套件標記
│   ├── data_provider.py          # 單一資料來源
│   ├── app.py                    # Flask app factory + 路由
│   ├── __main__.py               # python -m dashboard 啟動
│   ├── templates/dashboard.html
│   └── static/
│       ├── dashboard.css
│       └── dashboard.js
└── tests/
    ├── conftest.py               # autouse：阻擋真實網路
    ├── test_data_provider.py
    └── test_app.py
```

---

### Task 1: 依賴與套件骨架

**Files:**
- Create: `requirements.txt`
- Create: `dashboard/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 寫 `requirements.txt`**

```
flask>=3.0
requests>=2.31.0
numpy>=1.24
```

- [ ] **Step 2: 建空套件標記 `dashboard/__init__.py`**

```python
"""投資人績效儀表 dashboard 套件（self-contained，保留併入 hl-copytrader/src 的相容性）。"""
```

- [ ] **Step 3: 寫 `tests/conftest.py`（autouse 阻擋真實網路，對齊全域原則 #4）**

```python
"""測試全域設定：預設阻擋對外網路，任何測試都不得打到真實 Hyperliquid。"""
import pytest

import hl_track_record as htr


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """預設讓 requests.post 直接爆掉。需要『成功 live』的測試請改 monkeypatch
    htr.fetch_portfolio 餵假資料，而非解開這個保護。"""
    def _boom(*args, **kwargs):
        raise RuntimeError("真實網路在測試中被阻擋；請 mock fetch_portfolio")
    monkeypatch.setattr(htr.requests, "post", _boom)
```

- [ ] **Step 4: 安裝依賴**

Run: `.venv/bin/pip install -r requirements.txt`
Expected: flask 安裝成功（requests/numpy 已在）。

- [ ] **Step 5: Commit**

```bash
git add requirements.txt dashboard/__init__.py tests/conftest.py
git commit -m "chore: dashboard 套件骨架與測試網路保護"
```

---

### Task 2: data_provider — 單一資料來源（live + CSV fallback）

**Files:**
- Create: `dashboard/data_provider.py`
- Test: `tests/test_data_provider.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_data_provider.py`**

```python
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/python -m pytest tests/test_data_provider.py -v`
Expected: FAIL（`ModuleNotFoundError: dashboard.data_provider` 或 `AttributeError`）。

- [ ] **Step 3: 寫 `dashboard/data_provider.py`**

```python
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


def get_dashboard_data(address: str, csv_path: str = CSV_PATH) -> DashboardData:
    source = "live"
    try:
        days, equity = _live_curve(address)
        htr.save_csv(days, equity, csv_path)   # 順手刷新快取
    except Exception:
        source = "cached"
        if not os.path.exists(csv_path):
            raise DashboardDataUnavailable("無即時資料且無 CSV 快取")
        days, equity = _read_csv_curve(csv_path)

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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/python -m pytest tests/test_data_provider.py -v`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add dashboard/data_provider.py tests/test_data_provider.py
git commit -m "feat: data_provider 單一資料來源（live + CSV fallback，同源指標）"
```

---

### Task 3: Flask app 與路由

**Files:**
- Create: `dashboard/app.py`
- Test: `tests/test_app.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_app.py`**

```python
import pytest

import hl_track_record as htr
from dashboard.app import create_app
from dashboard import data_provider as dp

FAKE_PORTFOLIO = [
    ["allTime", {"accountValueHistory": [
        [0, "1000.0"], [86400000, "1010.0"], [172800000, "1025.0"],
    ]}],
]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(htr, "fetch_portfolio", lambda addr: FAKE_PORTFOLIO)
    csv_path = tmp_path / "equity_curve.csv"
    app = create_app(address="0xabc", csv_path=str(csv_path))
    app.config.update(TESTING=True)
    return app.test_client()


def test_index_returns_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"<canvas" in r.data        # 圖表畫布存在

def test_api_dashboard_shape(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.get_json()
    assert set(["equity", "days", "metrics", "source", "as_of"]).issubset(body)
    assert body["metrics"]["end_equity"] == pytest.approx(body["equity"][-1])

def test_api_equity_and_metrics_slices(client):
    eq = client.get("/api/equity").get_json()
    assert eq[0]["date"] and "value" in eq[0]
    m = client.get("/api/metrics").get_json()
    assert "sharpe" in m["metrics"] and m["source"] in ("live", "cached")

def test_unavailable_returns_503(monkeypatch, tmp_path):
    def _raise(addr):
        raise ConnectionError("boom")
    monkeypatch.setattr(htr, "fetch_portfolio", _raise)
    missing = tmp_path / "nope.csv"
    app = create_app(address="0xabc", csv_path=str(missing))
    app.config.update(TESTING=True)
    r = app.test_client().get("/api/dashboard")
    assert r.status_code == 503
    assert "error" in r.get_json()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: FAIL（`ModuleNotFoundError: dashboard.app`）。

- [ ] **Step 3: 寫 `dashboard/app.py`**

```python
"""Flask app factory：單頁儀表 + JSON API。
頁面用 /api/dashboard 一次取得完整快照（同源同基準）；/api/equity 與
/api/metrics 為方便嵌入而保留的切片。"""
from __future__ import annotations

import os

from flask import Flask, jsonify, render_template

import hl_track_record as htr
from dashboard import data_provider as dp


def create_app(address: str | None = None, csv_path: str | None = None) -> Flask:
    address = address or os.getenv("HL_DASHBOARD_WALLET", htr.WALLET)
    csv_path = csv_path or dp.CSV_PATH

    app = Flask(__name__)

    def _load():
        return dp.get_dashboard_data(address, csv_path=csv_path)

    @app.route("/")
    def index():
        return render_template("dashboard.html", wallet=address)

    @app.route("/api/dashboard")
    def api_dashboard():
        try:
            d = _load()
        except dp.DashboardDataUnavailable as e:
            return jsonify({"error": str(e)}), 503
        return jsonify({
            "days": d.days, "equity": d.equity,
            "metrics": d.metrics, "source": d.source, "as_of": d.as_of,
        })

    @app.route("/api/equity")
    def api_equity():
        try:
            d = _load()
        except dp.DashboardDataUnavailable as e:
            return jsonify({"error": str(e)}), 503
        return jsonify([{"date": day, "value": v}
                        for day, v in zip(d.days, d.equity)])

    @app.route("/api/metrics")
    def api_metrics():
        try:
            d = _load()
        except dp.DashboardDataUnavailable as e:
            return jsonify({"error": str(e)}), 503
        return jsonify({"metrics": d.metrics, "source": d.source, "as_of": d.as_of})

    return app
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: 4 passed。（`<canvas` 由 Task 4 的模板提供；本步驟需先建好模板，見下方備註。）

> 備註：`test_index_returns_html` 需要 `templates/dashboard.html` 存在才會過。
> 若先跑會因模板缺失失敗——這是預期的，Task 4 會補上模板後一起轉綠。
> 也可先建一個只含 `<canvas id="equityChart"></canvas>` 的最小模板讓本 Task 綠，
> Task 4 再擴充。建議採後者：先放最小模板。

- [ ] **Step 4b: 先放最小模板讓本 Task 可獨立轉綠**

Create `dashboard/templates/dashboard.html`（最小版，Task 4 擴充）：

```html
<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><title>績效儀表</title></head>
<body><canvas id="equityChart"></canvas></body></html>
```

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add dashboard/app.py dashboard/templates/dashboard.html tests/test_app.py
git commit -m "feat: Flask app factory 與 JSON API（含 503 錯誤態）"
```

---

### Task 4: 前端頁面（Chart.js 折線圖 + 指標卡 + 誠實揭露）

**Files:**
- Modify: `dashboard/templates/dashboard.html`（從最小版擴充為完整頁）
- Create: `dashboard/static/dashboard.css`
- Create: `dashboard/static/dashboard.js`

- [ ] **Step 1: 完整 `dashboard/templates/dashboard.html`**

```html
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>績效儀表 · Hyperliquid 實盤</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='dashboard.css') }}">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
</head>
<body>
  <header class="topbar">
    <div>
      <h1>Hyperliquid 實盤績效</h1>
      <div class="wallet">錢包 {{ wallet[:6] }}…{{ wallet[-4:] }}</div>
    </div>
    <div class="asof">
      <span id="sourceBadge" class="badge">載入中…</span>
      <div id="asOf" class="asof-time"></div>
    </div>
  </header>

  <main>
    <section class="chart-card">
      <h2>帳戶淨值曲線（USD）</h2>
      <canvas id="equityChart" height="120"></canvas>
    </section>

    <section id="cards" class="cards"></section>

    <section id="methodology" class="methodology">
      <h3>方法論與樣本揭露</h3>
      <p id="methodologyText"></p>
    </section>
  </main>

  <div id="errorState" class="error hidden">
    <p>目前無法取得績效資料（即時與快取皆不可用）。請稍後再試。</p>
  </div>

  <script src="{{ url_for('static', filename='dashboard.js') }}"></script>
</body>
</html>
```

- [ ] **Step 2: `dashboard/static/dashboard.css`**

```css
:root { --bg:#0e1116; --card:#161b22; --line:#2ea043; --txt:#e6edf3; --muted:#8b949e; --accent:#58a6ff; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--txt);
  font-family:-apple-system,"Segoe UI",Roboto,"Noto Sans TC",sans-serif; }
.topbar { display:flex; justify-content:space-between; align-items:flex-start;
  padding:24px 32px; border-bottom:1px solid #21262d; }
.topbar h1 { margin:0; font-size:22px; }
.wallet { color:var(--muted); font-size:13px; margin-top:4px; font-family:monospace; }
.asof { text-align:right; }
.badge { padding:4px 10px; border-radius:999px; font-size:12px; font-weight:600;
  background:#1f6feb33; color:var(--accent); }
.badge.cached { background:#9e6a0333; color:#e3b341; }
.asof-time { color:var(--muted); font-size:12px; margin-top:6px; }
main { max-width:1080px; margin:0 auto; padding:24px 32px 48px; }
.chart-card, .methodology { background:var(--card); border:1px solid #21262d;
  border-radius:12px; padding:20px 24px; margin-bottom:24px; }
.chart-card h2 { margin:0 0 16px; font-size:15px; color:var(--muted); font-weight:600; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:16px; margin-bottom:24px; }
.metric { background:var(--card); border:1px solid #21262d; border-radius:12px; padding:16px 18px; }
.metric .label { color:var(--muted); font-size:12px; margin-bottom:8px; }
.metric .value { font-size:24px; font-weight:700; }
.metric .sub { color:var(--muted); font-size:12px; margin-top:4px; }
.value.pos { color:var(--line); } .value.neg { color:#f85149; }
.methodology h3 { margin:0 0 8px; font-size:14px; color:var(--accent); }
.methodology p { margin:0; color:var(--muted); font-size:13px; line-height:1.7; }
.error { max-width:1080px; margin:24px auto; padding:24px; text-align:center; color:#f85149; }
.hidden { display:none; }
```

- [ ] **Step 3: `dashboard/static/dashboard.js`**

```javascript
const pct = (x) => (x * 100).toFixed(2) + "%";
const usd = (x) => "$" + x.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
const sign = (x) => (x >= 0 ? "pos" : "neg");

async function load() {
  let data;
  try {
    const r = await fetch("/api/dashboard");
    if (!r.ok) throw new Error("unavailable");
    data = await r.json();
  } catch (e) {
    document.getElementById("errorState").classList.remove("hidden");
    document.querySelector("main").classList.add("hidden");
    return;
  }
  renderBadge(data);
  renderChart(data);
  renderCards(data.metrics);
  renderMethodology(data.metrics);
}

function renderBadge(d) {
  const b = document.getElementById("sourceBadge");
  if (d.source === "live") { b.textContent = "即時"; }
  else { b.textContent = "快取"; b.classList.add("cached"); }
  document.getElementById("asOf").textContent = "截至 " + d.as_of.replace("T", " ") + " UTC";
}

function renderChart(d) {
  new Chart(document.getElementById("equityChart"), {
    type: "line",
    data: {
      labels: d.days,
      datasets: [{
        label: "帳戶淨值 (USD)", data: d.equity,
        borderColor: "#2ea043", backgroundColor: "rgba(46,160,67,0.12)",
        fill: true, tension: 0.25, pointRadius: 2, borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#8b949e" }, grid: { color: "#21262d" } },
        y: { ticks: { color: "#8b949e", callback: (v) => "$" + v }, grid: { color: "#21262d" } },
      },
    },
  });
}

function card(label, value, cls, sub) {
  return `<div class="metric"><div class="label">${label}</div>` +
         `<div class="value ${cls || ""}">${value}</div>` +
         (sub ? `<div class="sub">${sub}</div>` : "") + `</div>`;
}

function renderCards(m) {
  const html = [
    card("總報酬", pct(m.total_return), sign(m.total_return)),
    card("CAGR（年化）", pct(m.cagr), sign(m.cagr)),
    card("年化波動", pct(m.ann_vol)),
    card("最大回撤", pct(m.max_drawdown), "neg"),
    card("Sharpe（年化）", m.sharpe.toFixed(2), "", "± " + m.sharpe_se.toFixed(2) + " (1 s.e.)"),
    card("Sortino（年化）", m.sortino.toFixed(2)),
    card("Calmar", m.calmar.toFixed(2)),
    card("日勝率", pct(m.daily_win_rate)),
    card("最佳 / 最差日", pct(m.best_day) + " / " + pct(m.worst_day)),
    card("起訖淨值", usd(m.start_equity) + " → " + usd(m.end_equity), "", m.start + " → " + m.end),
  ].join("");
  document.getElementById("cards").innerHTML = html;
}

function renderMethodology(m) {
  let txt = `本記錄涵蓋 ${m.n_days} 個交易日（${m.start} → ${m.end}）。` +
    `Sharpe 為 ${m.sharpe.toFixed(2)}，標準誤 ±${m.sharpe_se.toFixed(2)}（Lo 2002, iid 近似）。` +
    `指標以 365 日/年、無風險利率 0% 之加密慣例年化。`;
  if (m.n_days < 60) {
    txt += ` 樣本數偏小（N=${m.n_days}），故標準誤帶寬較寬——此為「早期實盤記錄」，` +
      `非定型化的招牌數字；我們選擇誠實揭露而非藏起，讓它隨時間複利累積。`;
  }
  if (m.suspected_cashflows) {
    txt += ` 偵測到 ${m.suspected_cashflows} 日出現 >50% 淨值跳動，可能為出入金；` +
      `若屬實將改用資金加權（時間加權）報酬重算。`;
  }
  document.getElementById("methodologyText").textContent = txt;
}

load();
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/templates/dashboard.html dashboard/static/dashboard.css dashboard/static/dashboard.js
git commit -m "feat: 前端儀表頁（Chart.js 淨值曲線 + 指標卡 + 誠實揭露）"
```

---

### Task 5: 啟動入口、手動驗證、README

**Files:**
- Create: `dashboard/__main__.py`
- Create: `README.md`

- [ ] **Step 1: 寫 `dashboard/__main__.py`**

```python
"""啟動：.venv/bin/python -m dashboard
環境變數：HL_DASHBOARD_WALLET 可覆寫錢包；預設用 hl_track_record.WALLET。"""
from dashboard.app import create_app

if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=8000, debug=True)
```

- [ ] **Step 2: 全測試綠燈**

Run: `.venv/bin/python -m pytest -v`
Expected: 全部 passed（data_provider 4 + app 4）。

- [ ] **Step 3: 手動驗證（真實啟動，背景執行）**

Run（背景）: `.venv/bin/python -m dashboard`
然後另開：`curl -s http://127.0.0.1:8000/api/dashboard | head -c 300`
Expected: 回傳含 `"source"`、`"equity"`、`"metrics"` 的 JSON（即時或快取皆可）。
再 `curl -s http://127.0.0.1:8000/ | grep -o '<canvas[^>]*>'`
Expected: 看到 `<canvas id="equityChart" ...>`。
驗證後關閉背景行程。

- [ ] **Step 4: 寫 `README.md`**

```markdown
# golden-tea · 投資人績效儀表

把 Hyperliquid 錢包的實盤績效做成單頁網頁儀表（淨值曲線 + 機構級指標）。

## 跑起來

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m dashboard          # 開 http://127.0.0.1:8000
```

可用 `HL_DASHBOARD_WALLET=0x...` 覆寫錢包；斷線時自動讀 `equity_curve.csv` 快取。

## 測試

```bash
.venv/bin/python -m pytest -v
```

## 與 hl-copytrader 的合併相容性

`dashboard/data_provider.py` 是唯一碰網路處。併入 `hl-copytrader/src/` 時，
只需把該檔的 fetch 換成 `src/monitor.py` 的 `_post` 與 `src/config.py` 慣例。
```

- [ ] **Step 5: Commit**

```bash
git add dashboard/__main__.py README.md
git commit -m "feat: 啟動入口與 README；完成投資人儀表 MVP"
```

---

## 自我檢查結果

- **Spec 覆蓋：** 架構/資料流/錯誤處理/測試/誠實揭露皆對應到 Task 2–5；合併相容性以「單一 fetch 邊界 + README 說明」滿足（保留不執行）。
- **Placeholder：** 無 TBD/TODO；每個程式步驟都有完整程式碼。
- **型別一致：** `DashboardData(days, equity, metrics, source, as_of)`、`get_dashboard_data(address, csv_path)`、`create_app(address, csv_path)`、`DashboardDataUnavailable` 全程一致；前端讀的 metrics 欄位與 `Metrics` dataclass 欄位名一致。
```
