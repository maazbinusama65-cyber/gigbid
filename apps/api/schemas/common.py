"""Shared response models."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    error: str
    detail: str = ""
    trace_id: str = ""


class MarketplaceStatus(BaseModel):
    ok: bool
    mode: str = Field(description="gigsim | upwork_live | mock")
    detail: str = ""
    checked_at: str


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "gigbid-api"
    version: str = "0.1.0"
    services_mode: str = Field(description="mock | real")
    marketplace: MarketplaceStatus


class OkResponse(BaseModel):
    ok: bool = True
    detail: str = ""
