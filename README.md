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
