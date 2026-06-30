# BTC / 美股大盤 Benchmark 開關 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在投資人儀表淨值圖加上 BTC 與美股大盤（xyz:XYZ100）兩個 benchmark 開關，預設關、可同時/個別開，疊圖時 rebase 到同一 $1,000 起點比相對報酬。

**Architecture:** `data_provider.py` 新增 benchmark 抓取（Hyperliquid `candleSnapshot`，單一網路邊界）並 rebase+日期對齊；`app.py` 加 `GET /api/benchmark`；前端兩個 toggle 採 lazy 載入（第一次開才抓、之後純 show/hide），預設載入零額外成本。

**Tech Stack:** Python 3.9、Flask、requests、numpy、Chart.js、pytest。

**合併相容性：** benchmark 抓取集中在 `data_provider._fetch_candles`（唯一網路邊界）；併入 hl-copytrader 時換成 `src/monitor.py` 的 `_post` 即可。

---

## 檔案結構

```
dashboard/
├── data_provider.py          # 擴充：_fetch_candles / get_benchmarks / BENCHMARKS
├── app.py                    # 擴充：GET /api/benchmark
├── templates/dashboard.html  # 擴充：兩個 toggle + 提示位
├── static/dashboard.css      # 擴充：toggle 樣式
└── static/dashboard.js       # 擴充：lazy 載入 + show/hide
tests/
├── test_data_provider.py     # 擴充：rebase / 對齊 / forward-fill
└── test_app.py               # 擴充：/api/benchmark 結構 + 503
```

既有 import（`data_provider.py` 開頭）已有 `import csv as _csv, dataclasses, os, numpy as np, hl_track_record as htr`，`htr` 提供 `INFO_URL` 與 `requests`。無需新增 import。

---

### Task 1: data_provider — benchmark 抓取、rebase、對齊

**Files:**
- Modify: `dashboard/data_provider.py`
- Test: `tests/test_data_provider.py`

- [ ] **Step 1: 在 `tests/test_data_provider.py` 末尾追加測試**

```python
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/python -m pytest tests/test_data_provider.py -k benchmark -v`
Expected: FAIL（`AttributeError: module 'dashboard.data_provider' has no attribute 'get_benchmarks'`）。

- [ ] **Step 3: 在 `dashboard/data_provider.py` 末尾追加實作**

```python
# --------------------------------------------------------------------------
# Benchmark（BTC / 美股大盤）— 與淨值曲線疊圖比較
# 顯示鍵 -> Hyperliquid candleSnapshot 的 coin 名
# --------------------------------------------------------------------------
BENCHMARKS = {"BTC": "BTC", "XYZ100": "xyz:XYZ100"}


def _fetch_candles(coin: str, t0_ms: int, t1_ms: int):
    """打 candleSnapshot 取日線收盤。唯一碰網路（candle）；回 [(YYYY-MM-DD, close)]。"""
    body = {"type": "candleSnapshot",
            "req": {"coin": coin, "interval": "1d",
                    "startTime": int(t0_ms), "endTime": int(t1_ms)}}
    resp = htr.requests.post(htr.INFO_URL,
                             headers={"Content-Type": "application/json"},
                             json=body, timeout=20)
    resp.raise_for_status()
    out = []
    for c in resp.json():
        day = str(np.datetime64(int(c["t"]), "ms").astype("datetime64[D]"))
        out.append((day, float(c["c"])))
    return out


def _days_to_ms_range(days):
    """由日期字串清單推導 candleSnapshot 的 [t0, t1] ms（首日 00:00 ~ 末日 23:59:59.999）。"""
    d0 = np.datetime64(days[0], "D").astype("datetime64[ms]").astype("int64")
    d1 = (np.datetime64(days[-1], "D") + np.timedelta64(1, "D")
          ).astype("datetime64[ms]").astype("int64") - 1
    return int(d0), int(d1)


def get_benchmarks(days, base):
    """回 {"BTC": [...], "XYZ100": [...]}：各 benchmark 抓 candle、以 days 日期對齊
    （缺日 forward-fill），再 rebase 到 base（首點 == base）。"""
    t0, t1 = _days_to_ms_range(days)
    result = {}
    for key, coin in BENCHMARKS.items():
        by_day = {d: c for d, c in _fetch_candles(coin, t0, t1)}
        aligned, last = [], None
        for day in days:
            if day in by_day:
                last = by_day[day]
            aligned.append(last)
        first_valid = next((v for v in aligned if v is not None), None)
        if first_valid is None:
            raise ValueError(f"benchmark {coin} 無任何收盤資料")
        aligned = [v if v is not None else first_valid for v in aligned]
        c0 = aligned[0]
        result[key] = [round(base * v / c0, 6) for v in aligned]
    return result
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/python -m pytest tests/test_data_provider.py -k benchmark -v`
Expected: 2 passed。

- [ ] **Step 5: 全套件無回歸**

Run: `.venv/bin/python -m pytest -q`
Expected: 12 passed（10 既有 + 2 新）。

- [ ] **Step 6: Commit**

```bash
git add dashboard/data_provider.py tests/test_data_provider.py
git commit -m "feat: data_provider benchmark 抓取（candleSnapshot）+ rebase + 日期對齊"
```

---

### Task 2: app — `GET /api/benchmark`

**Files:**
- Modify: `dashboard/app.py`
- Test: `tests/test_app.py`

- [ ] **Step 1: 在 `tests/test_app.py` 末尾追加測試**

```python
def test_api_benchmark_shape(client, monkeypatch):
    # client fixture 的 FAKE_PORTFOLIO 產生的 days 為 1970-01-01..03（ms 0/86400000/172800000）
    candles = [("1970-01-01", 100.0), ("1970-01-02", 110.0), ("1970-01-03", 90.0)]
    monkeypatch.setattr(dp, "_fetch_candles", lambda coin, t0, t1: candles)

    r = client.get("/api/benchmark")
    assert r.status_code == 200
    body = r.get_json()
    assert set(["days", "series", "base"]).issubset(body)
    assert set(body["series"]) == {"BTC", "XYZ100"}
    assert body["series"]["BTC"][0] == body["base"]   # 首點 == base


def test_api_benchmark_upstream_failure_returns_503(client, monkeypatch):
    def _boom(coin, t0, t1):
        raise ConnectionError("boom")
    monkeypatch.setattr(dp, "_fetch_candles", _boom)

    r = client.get("/api/benchmark")
    assert r.status_code == 503
    assert "error" in r.get_json()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/python -m pytest tests/test_app.py -k benchmark -v`
Expected: FAIL（404，路由尚未存在）。

- [ ] **Step 3: 在 `dashboard/app.py` 的 `create_app` 內、`return app` 之前加入路由**

```python
    @app.route("/api/benchmark")
    def api_benchmark():
        try:
            d = _load()
        except dp.DashboardDataUnavailable as e:
            return jsonify({"error": str(e)}), 503
        try:
            series = dp.get_benchmarks(d.days, d.metrics["start_equity"])
        except Exception as e:  # 上游 candle 抓取/解析失敗 → 大聲回 503（全域原則 #3）
            return jsonify({"error": f"benchmark 取得失敗: {e}"}), 503
        return jsonify({"days": d.days, "series": series,
                        "base": d.metrics["start_equity"]})
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/python -m pytest tests/test_app.py -k benchmark -v`
Expected: 2 passed。

- [ ] **Step 5: 全套件無回歸**

Run: `.venv/bin/python -m pytest -q`
Expected: 14 passed。

- [ ] **Step 6: Commit**

```bash
git add dashboard/app.py tests/test_app.py
git commit -m "feat: GET /api/benchmark（rebase 後的 BTC / 美股大盤，含 503 錯誤態）"
```

---

### Task 3: 前端 — 兩個 toggle（lazy 載入 + show/hide）

**Files:**
- Modify: `dashboard/templates/dashboard.html`
- Modify: `dashboard/static/dashboard.css`
- Modify: `dashboard/static/dashboard.js`
- Test: `tests/test_app.py`（smoke：頁面含 toggle 元素）

- [ ] **Step 1: 在 `tests/test_app.py` 末尾追加 smoke 測試**

```python
def test_index_has_benchmark_toggles(client):
    r = client.get("/")
    assert b'id="toggleBTC"' in r.data
    assert b'id="toggleXYZ100"' in r.data
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/python -m pytest tests/test_app.py -k toggles -v`
Expected: FAIL（模板尚無 toggle）。

- [ ] **Step 3: 修改 `dashboard/templates/dashboard.html`，把 chart-card 區塊替換為含 toggle 的版本**

找到現有區塊：

```html
    <section class="chart-card">
      <h2>帳戶淨值曲線（USD）</h2>
      <canvas id="equityChart" height="120"></canvas>
    </section>
```

替換成：

```html
    <section class="chart-card">
      <h2>帳戶淨值曲線（USD）</h2>
      <div class="bench-controls">
        <span class="bench-label">疊加對照：</span>
        <label class="toggle"><input type="checkbox" id="toggleBTC"> BTC</label>
        <label class="toggle"><input type="checkbox" id="toggleXYZ100"> 美股大盤</label>
        <span id="benchNotice" class="bench-notice"></span>
      </div>
      <canvas id="equityChart" height="120"></canvas>
    </section>
```

- [ ] **Step 4: 在 `dashboard/static/dashboard.css` 末尾追加樣式**

```css
.bench-controls { display:flex; gap:16px; align-items:center; margin:-4px 0 14px; flex-wrap:wrap; }
.bench-label { color:var(--muted); font-size:13px; }
.toggle { color:var(--txt); font-size:13px; display:inline-flex; align-items:center; gap:6px; cursor:pointer; user-select:none; }
.toggle input { accent-color:var(--accent); cursor:pointer; }
.bench-notice { color:#f85149; font-size:12px; }
```

- [ ] **Step 5: 修改 `dashboard/static/dashboard.js`**

5a. 把檔案最上面新增模組層狀態與 benchmark 中繼資料（放在 `const pct = ...` 之前）：

```javascript
let chart = null;
let benchmarkLoaded = false;
const BENCH_META = {
  BTC:    { label: "BTC（rebased $1,000）",                          color: "#f7931a" },
  XYZ100: { label: "美股大盤 xyz:XYZ100（rebased $1,000，S&P 500 近似）", color: "#58a6ff" },
};
```

5b. 把 `renderChart` 改成把 chart 存進模組變數——將開頭：

```javascript
function renderChart(d) {
  new Chart(document.getElementById("equityChart"), {
```

改為：

```javascript
function renderChart(d) {
  chart = new Chart(document.getElementById("equityChart"), {
```

5c. 在 `load()` 函式的 `renderMethodology(data.metrics);` 之後、函式結束的 `}` 之前，加上 toggle 接線：

```javascript
  document.getElementById("toggleBTC").addEventListener("change",
    (e) => onToggle("BTC", e.target.checked, e.target));
  document.getElementById("toggleXYZ100").addEventListener("change",
    (e) => onToggle("XYZ100", e.target.checked, e.target));
```

5d. 在 `renderMethodology` 函式之後、`load();` 呼叫之前，新增 benchmark 邏輯：

```javascript
async function ensureBenchmarks() {
  if (benchmarkLoaded) return;
  const r = await fetch("/api/benchmark");
  if (!r.ok) throw new Error("benchmark unavailable");
  const b = await r.json();
  for (const key of ["BTC", "XYZ100"]) {
    chart.data.datasets.push({
      label: BENCH_META[key].label,
      data: b.series[key],
      borderColor: BENCH_META[key].color,
      borderDash: [6, 4], borderWidth: 2, pointRadius: 0,
      fill: false, tension: 0.25, hidden: true, _benchKey: key,
    });
  }
  benchmarkLoaded = true;
  chart.update();
}

async function onToggle(key, checked, el) {
  const notice = document.getElementById("benchNotice");
  if (checked) {
    el.disabled = true;
    try {
      await ensureBenchmarks();
    } catch (e) {
      el.checked = false;
      notice.textContent = "benchmark 暫時無法載入";
      el.disabled = false;
      return;
    }
    el.disabled = false;
  }
  notice.textContent = "";
  const ds = chart.data.datasets.find((d) => d._benchKey === key);
  if (ds) { ds.hidden = !checked; chart.update(); }
}
```

- [ ] **Step 6: 跑 smoke 測試確認通過 + 全套件**

Run: `.venv/bin/python -m pytest -q`
Expected: 15 passed。

- [ ] **Step 7: 真實啟動驗證（背景）**

Run: `.venv/bin/python -m dashboard > /tmp/dash3.log 2>&1 &`，`sleep 3`
然後：
- `curl -s http://127.0.0.1:8000/api/benchmark | python3 -c "import sys,json; b=json.load(sys.stdin); print('keys', list(b)); print('series', list(b['series'])); print('BTC[0]==base?', b['series']['BTC'][0]==b['base']); print('len', len(b['series']['BTC']), len(b['days']))"`
  Expected: keys 含 days/series/base；series 為 BTC/XYZ100；BTC[0]==base 為 True；長度與 days 相同。
- `curl -s http://127.0.0.1:8000/ | grep -o 'id="toggle[A-Za-z0-9]*"'`
  Expected: `id="toggleBTC"` 與 `id="toggleXYZ100"`。
驗證後關閉背景行程（`pkill -f "python -m dashboard"`），並列出 /tmp/dash3.log 末 5 行確認無錯誤。

- [ ] **Step 8: Commit**

```bash
git add dashboard/templates/dashboard.html dashboard/static/dashboard.css dashboard/static/dashboard.js tests/test_app.py
git commit -m "feat: 前端 BTC/美股大盤 benchmark 開關（lazy 載入、虛線疊圖、預設關）"
```

---

## 自我檢查結果

- **Spec 覆蓋：** 資料來源（Task 1 `_fetch_candles` BTC/xyz:XYZ100）、rebase（Task 1 get_benchmarks）、日期對齊+forward-fill（Task 1 測試）、`/api/benchmark`+503（Task 2）、toggle/lazy/虛線/預設關（Task 3）、錯誤彈回提示（Task 3 onToggle）、測試（各 Task）皆對應。
- **Placeholder：** 無；每個程式步驟都有完整程式碼或精確 grep/replace 指示。
- **型別一致：** `get_benchmarks(days, base)` 回 `{"BTC":[...], "XYZ100":[...]}`；`_fetch_candles(coin, t0, t1)` 回 `[(day, close)]`；`/api/benchmark` 回 `{days, series, base}`；前端 `_benchKey` 與 `BENCH_META` 鍵（BTC/XYZ100）一致；toggle id（toggleBTC/toggleXYZ100）跨 HTML/JS/測試一致。
