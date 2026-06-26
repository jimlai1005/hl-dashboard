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
