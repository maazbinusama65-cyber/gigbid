from __future__ import annotations

import pytest

from mcp_servers.portfolio import build_server
from mcp_servers.portfolio.service import PortfolioConfig

from .data import make_portfolio


@pytest.fixture()
def portfolio_dir(tmp_path):
    return make_portfolio(tmp_path / "personas")


@pytest.fixture()
def server(portfolio_dir):
    return build_server(PortfolioConfig(data_dir=str(portfolio_dir), default_portfolio_id="ai_ml",
                                        backend="local"))
