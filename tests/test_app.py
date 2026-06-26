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
