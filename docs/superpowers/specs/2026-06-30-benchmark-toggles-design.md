# BTC / 美股大盤 Benchmark 開關 — 設計文件

- 日期：2026-06-30
- 專案：golden-tea（獨立專案，保留併入 hl-copytrader 相容性）
- 狀態：已核准，待寫實作計畫

## 目標

在投資人儀表的淨值圖上，加入兩個 benchmark 開關（BTC、美股大盤），開啟時把
對應 benchmark 疊到圖中當對照。可同時開、可個別開，**預設都關**；關掉時畫面
與現狀完全一致。

## 資料來源（實證決定）

- **BTC**：Hyperliquid `info` API 的 `candleSnapshot`（`coin="BTC"`, `interval="1d"`）。
- **美股大盤**：Hyperliquid `xyz:XYZ100`（自家百檔美股大型股指數）。S&P 500 不在
  Hyperliquid 上、外部來源（Stooq）404 且與錢包 2026 時間線對不齊，故採 XYZ100 為
  可用代理，圖例誠實標示「美股大盤（xyz:XYZ100，S&P 500 近似）」。
- 兩者都走我們既有的同一支 Hyperliquid API，無新外部依賴；抓取集中在
  `data_provider.py`（單一網路邊界，全域原則 #5）。

## 正規化（公平比較）

三條線都 rebase 到同一個起點 base（＝淨值起始本金 $1,000）：
`benchmark[i] = base × close[i] / close[0]`。
語意為「同一天各投入 $1,000，各自成長到多少」，純比相對報酬，與 $ 軸相容。

## 對齊

benchmark 日線以**日期為鍵**對齊到淨值曲線的每一天；某天缺 benchmark 收盤時
forward-fill（沿用前一日收盤）。第一天必為 base。

## 行為

- 圖表上方兩個 toggle：`BTC`、`美股大盤`，預設皆關。
- **Lazy 載入**：第一次開啟任一 toggle 才打 `/api/benchmark`（一次抓回兩條、前端
  快取），之後 toggle 純 show/hide 對應 Chart.js dataset。預設載入零額外網路成本。
- benchmark 線為虛線、各自顏色（BTC 橘 #f7931a、美股大盤藍 #58a6ff）；淨值維持
  實線綠 #2ea043。

## 元件

### `dashboard/data_provider.py`（擴充）
- `BENCHMARKS = {"BTC": "BTC", "XYZ100": "xyz:XYZ100"}`（顯示鍵 → Hyperliquid coin）
- `_fetch_candles(coin, t0_ms, t1_ms) -> list[(date_str, close_float)]`：唯一碰網路，
  打 `candleSnapshot`。
- `get_benchmarks(days, base) -> dict`：對每個 benchmark 抓 candle、rebase 到 base、
  以 `days` 日期對齊（缺日 forward-fill），回 `{"BTC": [...], "XYZ100": [...]}`。
  `days` 為淨值曲線日期字串清單；t0/t1 ms 由首/末日推導。

### `dashboard/app.py`（擴充）
- `GET /api/benchmark` → 內部呼叫 `get_dashboard_data` 取得 `days` 與
  `base = start_equity`，再呼叫 `get_benchmarks`，回
  `{"days": [...], "series": {"BTC": [...], "XYZ100": [...]}, "base": base}`。
  上游（資料不可用）回 503 `{"error": ...}`。

### 前端
- `dashboard.html`：圖表標題列加兩個 toggle（`id="toggleBTC"`、`id="toggleXYZ100"`）。
- `dashboard.css`：toggle 樣式 + benchmark 載入失敗的小字提示樣式。
- `dashboard.js`：toggle change 時，若快取為空則 lazy fetch `/api/benchmark` 一次；
  建立兩條 benchmark dataset（初始 hidden）；toggle 翻轉對應 dataset 的 hidden 後
  `chart.update()`。

## 錯誤處理

- benchmark 抓取失敗 → 該 toggle 自動彈回未勾選狀態 + 旁邊顯示小字
  「benchmark 暫時無法載入」；**淨值主圖完全不受影響**（已先載入）。
- `/api/benchmark` 在淨值資料本身不可用時回 503。

## 測試（pytest，網路全 mock，全域原則 #4）

- `data_provider`：
  - rebase 數學：對齊後首點 == base
  - 日期對齊：輸出長度 == len(days)，且按日期對應
  - 缺日 forward-fill：benchmark 缺某日時沿用前一日收盤
  - `_fetch_candles` 失敗時 `get_benchmarks` 不崩（拋明確例外或回空，由 app 轉 503）
- `app`：`/api/benchmark` 結構正確（mock candle）；上游淨值不可用回 503
- 前端 smoke：`GET /` 內含 `id="toggleBTC"` 與 `id="toggleXYZ100"`

## 非目標（YAGNI）

- 不做 benchmark 的指標卡（Sharpe 等只算基金本身）
- 不做任意自選 benchmark / 第三條以上
- 不接外部（非 Hyperliquid）行情源
- 不做 benchmark 歷史快取持久化（lazy 抓即可）

## 合併相容性

benchmark 抓取（`_fetch_candles`）位於 `data_provider.py` 這個唯一網路邊界。併入
`hl-copytrader/src/` 時，只需把該處 `candleSnapshot` 呼叫換成 `src/monitor.py` 的
`_post` 慣例。
