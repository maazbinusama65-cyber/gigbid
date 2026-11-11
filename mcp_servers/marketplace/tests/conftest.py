from __future__ import annotations

import pytest

from mcp_servers.marketplace import build_server
from mcp_servers.marketplace.service import MarketplaceConfig

from .fakes import FakeMarketplace


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def fake():
    return FakeMarketplace()


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def cfg(tmp_path, fake, clock):
    return MarketplaceConfig(adapter=fake, state_dir=tmp_path / "state", default_user="alice",
                             rate_limit_rpm=600, rate_burst=100, clock=clock)


@pytest.fixture()
def server(cfg):
    return build_server(cfg)
