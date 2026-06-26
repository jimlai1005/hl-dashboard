# 投資人績效儀表 Dashboard — 設計文件

- 日期：2026-06-26
- 專案：golden-tea（獨立專案）
- 狀態：已核准，待寫實作計畫

## 目標

把既有的 Hyperliquid 帳戶績效報表，做成一個可跑成網頁、給投資人看的單頁儀表，
證明這檔基金的實盤表現。儀表需根據 `equity_curve.csv` / 即時資料畫出淨值曲線，
並呈現機構級指標（Sharpe / Sortino / Calmar / MaxDD / 日勝率）。

## 範圍與邊界

- **本專案維持獨立**，不實際併入 `hl-copytrader`。
- 唯一的跨專案約束是：**保留未來合併進 `hl-copytrader/src/` 的相容性**——
  結構自包含、網路存取集中在單一處，未來可低成本搬遷。
- 不做使用者登入、不做多錢包、不做歷史快照資料庫。YAGNI。

## 架構

輕量 Flask app，重用既有 `hl_track_record.py` 的純函數。

```
golden-tea/
├── hl_track_record.py        # 既有，微調：讓 web 層能 import 純函數
├── equity_curve.csv          # 既有，當作斷線備援快取
├── dashboard/
│   ├── __init__.py
│   ├── data_provider.py      # 單一資料來源：live 抓→失敗 fallback CSV→算指標
│   ├── app.py                # Flask：GET / , /api/metrics , /api/equity
│   ├── templates/
│   │   └── dashboard.html
│   └── static/
│       ├── dashboard.css
│       └── dashboard.js
├── tests/
│   └── test_dashboard.py
└── requirements.txt          # flask + 既有 requests / numpy
```

### 合併相容性策略（保留，不執行）

- `data_provider.py` 是**唯一碰網路的地方**（對齊全域原則 #5：單一 IO 邊界）。
- 未來搬進 `hl-copytrader` 時，只需把該處的 fetch 函數換成 `src/monitor.py` 的
  `_post(api_url, payload)` 模式與 `src/config.py` 的設定慣例；其餘 module 不動。
- 命名與註解採繁體中文，與 `hl-copytrader` 既有風格一致。

## 元件

### 1. `hl_track_record.py`（微調）

維持既有四層解耦設計。確認下列純函數可被 import 重用：
`fetch_portfolio`、`extract_equity_curve`、`to_daily`、`compute_metrics`。
新增一個把 `Metrics` dataclass 轉成 dict 的輔助（或直接用 `dataclasses.asdict`）供 JSON 序列化。
不改變既有 CLI 行為。

### 2. `dashboard/data_provider.py`

`get_dashboard_data(address) -> DashboardData`：

- 嘗試 live：`fetch_portfolio → extract_equity_curve → to_daily`
- live 成功 → 順手把最新曲線寫回 `equity_curve.csv`（刷新快取），`source="live"`
- live 失敗（網路/解析）→ 讀 `equity_curve.csv`，`source="cached"`
- CSV 也不存在 → 拋出明確的 `DashboardDataUnavailable`
- **在同一處、用同一條 equity 陣列**同時產生圖表點與指標，回傳
  `(days, equity, metrics, source, as_of)`（對齊全域原則 #1：呈現的值同源同基準）。

### 3. `dashboard/app.py`（Flask）

- `GET /` → 回 `dashboard.html`
- `GET /api/equity` → `[{ "date": "YYYY-MM-DD", "value": float }, …]`
- `GET /api/metrics` → 指標 dict + `source` + `as_of`
- 兩個 API 端點都呼叫同一個 `get_dashboard_data`，**共用同一份輸出**，
  確保圖表與指標卡同源。

### 4. 前端 `dashboard.html` + `dashboard.js` + `dashboard.css`

單頁，機構級風格：

- 頂部：基金名稱、截至日期、資料來源 badge（即時 / 快取＋上次更新時間）
- 中間：大張淨值折線圖（Chart.js，CDN 載入）
- 下方：指標卡格狀排列——總報酬、CAGR、年化波動、MaxDD、Sharpe（±SE）、
  Sortino、Calmar、日勝率、最佳/最差日
- 底部：「方法論與樣本揭露」callout——把 `N=10`、`Sharpe ±6.12` 包裝為
  「誠實揭露 = 可信度」，面對 FRM/CFA 受眾加分，並避免誤導投資人的法務風險。

## 資料流

```
瀏覽器 → GET /            → 回 HTML
       → GET /api/equity  → data_provider.get_dashboard_data() → JSON 曲線
       → GET /api/metrics → （同一份資料）                      → JSON 指標
前端 JS 拿到後渲染折線圖與指標卡。
```

## 錯誤處理

- live 抓成功 → 刷新 CSV 快取，badge =「即時」
- live 失敗 → 讀 CSV，badge =「快取／上次更新時間」
- CSV 也不在 → API 回 503 + 清楚訊息；頁面顯示友善錯誤態（非白畫面）

## 測試（pytest，網路全 mock，對齊全域原則 #4）

- `data_provider` 在 live 失敗時正確 fallback 到 CSV
- `data_provider` 在 live 與 CSV 都不可用時拋出明確錯誤
- `/api/metrics`、`/api/equity` 以 Flask test client 驗證回傳結構
- **一致性測試**：兩端點的數據確實來自同一份 equity（同源同基準）
- 全程不打真實網路（autouse fixture mute 對外請求）

## 非目標（YAGNI）

- 不做登入 / 權限
- 不做多錢包切換
- 不做歷史快照資料庫或時間機器
- 不做即時 websocket 串流（載入時抓一次即可）
