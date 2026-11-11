"""Onboarding (persona or own profile, rates, budget) and portfolio upload."""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth.deps import CurrentUser, get_config, get_current_user, get_db, get_services
from apps.api.config import AppConfig
from apps.api.db import PortfolioFileRow, ProfileRow, UserRow
from apps.api.errors import ApiError
from apps.api.schemas.settings import (
    OnboardingRequest,
    OnboardingState,
    PortfolioFile,
)
from apps.api.services import Services

router = APIRouter(prefix="/onboarding", tags=["onboarding"])
log = logging.getLogger("apps.api.onboarding")

ALLOWED_SUFFIXES = {".pdf", ".md", ".txt", ".json", ".zip", ".csv", ".docx"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\- ]+")


class BadUpload(ApiError):
    status_code = 422
    error = "bad_upload"


def clean_filename(raw: str) -> str:
    base = PureWindowsPath(PurePosixPath(raw or "").name).name  # drop any directory components
    base = _SAFE_NAME.sub("_", base).strip(" .")
    return base[:200] or "upload"


def _file_out(row: PortfolioFileRow) -> PortfolioFile:
    return PortfolioFile(
        file_id=row.id, filename=row.filename, size_bytes=row.size_bytes,
        status=row.status,  # type: ignore[arg-type]
        created_at=row.created_at.isoformat(),
    )


def _files(db: Session, user_id: str) -> list[PortfolioFile]:
    rows = db.execute(
        select(PortfolioFileRow)
        .where(PortfolioFileRow.user_id == user_id)
        .order_by(PortfolioFileRow.created_at.desc())
    ).scalars()
    return [_file_out(r) for r in rows]


async def _state(user: CurrentUser, db: Session, services: Services) -> OnboardingState:
    state = await services.get_onboarding(user)
    profile = db.execute(select(ProfileRow).where(ProfileRow.user_id == user.id)).scalar_one_or_none()
    urow = db.execute(select(UserRow).where(UserRow.id == user.id)).scalar_one()
    return state.model_copy(
        update={
            "completed": urow.onboarded,
            "persona_id": urow.persona_id or state.persona_id,
            "marketplace": profile.marketplace if profile else state.marketplace,  # type: ignore[arg-type]
            "hourly_rate_usd": profile.hourly_rate_usd if profile else state.hourly_rate_usd,
            "min_budget_usd": profile.min_budget_usd if profile else state.min_budget_usd,
            "weekly_connects_budget": (
                profile.weekly_connects_budget if profile else state.weekly_connects_budget
            ),
            "portfolio_files": _files(db, user.id),
        }
    )


@router.get("", response_model=OnboardingState)
async def get_onboarding(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    services: Services = Depends(get_services),
) -> OnboardingState:
    return await _state(user, db, services)


@router.put("", response_model=OnboardingState)
async def complete_onboarding(
    body: OnboardingRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    services: Services = Depends(get_services),
) -> OnboardingState:
    if not body.persona_id and not body.own_profile:
        raise BadUpload("Choose a persona or describe your own profile")
    await services.complete_onboarding(user, body)
    profile = db.execute(select(ProfileRow).where(ProfileRow.user_id == user.id)).scalar_one_or_none()
    if profile is None:
        profile = ProfileRow(user_id=user.id)
    profile.persona_id = body.persona_id
    profile.own_profile_json = body.own_profile.model_dump_json() if body.own_profile else None
    profile.hourly_rate_usd = body.hourly_rate_usd
    profile.min_budget_usd = body.min_budget_usd
    profile.weekly_connects_budget = body.weekly_connects_budget
    profile.marketplace = body.marketplace
    db.add(profile)
    urow = db.execute(select(UserRow).where(UserRow.id == user.id)).scalar_one()
    urow.persona_id = body.persona_id or "own_profile"
    urow.onboarded = True
    db.add(urow)
    db.commit()
    return await _state(user, db, services)


@router.get("/portfolio", response_model=list[PortfolioFile])
def list_portfolio(
    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[PortfolioFile]:
    return _files(db, user.id)


@router.post("/portfolio", response_model=PortfolioFile, status_code=201)
async def upload_portfolio(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    cfg: AppConfig = Depends(get_config),
    services: Services = Depends(get_services),
) -> PortfolioFile:
    name = clean_filename(file.filename or "")
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise BadUpload(f"Unsupported file type {suffix or '(none)'}; allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}")
    data = await file.read(cfg.max_upload_bytes + 1)
    if len(data) > cfg.max_upload_bytes:
        raise BadUpload(f"File too large (limit {cfg.max_upload_bytes // (1024 * 1024)} MB)")
    if not data:
        raise BadUpload("File is empty")
    result = await services.upload_portfolio(user, name, file.content_type or "", data)
    row = PortfolioFileRow(
        user_id=user.id,
        filename=name,
        content_type=(file.content_type or "")[:120],
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        status=result.status,
    )
    db.add(row)
    db.commit()
    log.info("portfolio upload user=%s file=%s bytes=%d", user.id, row.id, len(data))
    return _file_out(row)

