"""Test/demo controls, mounted ONLY when GIGBID_SERVICES=mock and hidden from the OpenAPI contract."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/_mock", include_in_schema=False)


class DegradeRequest(BaseModel):
    degraded: bool = True


@router.post("/degrade")
async def mock_degrade(body: DegradeRequest, request: Request) -> dict:
    request.app.state.services.set_degraded(body.degraded)
    return {"degraded": body.degraded}


@router.post("/reset")
async def mock_reset(request: Request) -> dict:
    request.app.state.services.reset()
    return {"reset": True}
