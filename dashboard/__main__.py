"""啟動：.venv/bin/python -m dashboard
環境變數：HL_DASHBOARD_WALLET 可覆寫錢包；預設用 hl_track_record.WALLET。"""
from dashboard.app import create_app

if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=8000, debug=True)
