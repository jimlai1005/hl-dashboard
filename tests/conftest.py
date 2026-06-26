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
