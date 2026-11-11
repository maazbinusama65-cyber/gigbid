"""Settings, memory viewer, connected accounts and onboarding models."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AutonomyLevel = Literal["manual", "assist", "scout"]
MarketplaceName = Literal["gigsim", "upwork"]


class SavedSearch(BaseModel):
    search_id: str
    name: str = Field(max_length=120)
    query: str = Field(max_length=300)
    category: str | None = None
    interval_minutes: int = Field(default=60, ge=15, le=1440)
    enabled: bool = True


class UserSettings(BaseModel):
    autonomy_level: AutonomyLevel = "assist"
    weekly_connects_budget: int = Field(default=60, ge=0, le=1000)
    max_connects_per_proposal: int = Field(default=16, ge=0, le=100)
    min_fit_score: float = Field(default=0.55, ge=0, le=1)
    min_budget_usd: int = Field(default=300, ge=0)
    hourly_rate_usd: int = Field(default=65, ge=0)
    saved_searches: list[SavedSearch] = Field(default_factory=list)


class UserSettingsUpdate(BaseModel):
    autonomy_level: AutonomyLevel | None = None
    weekly_connects_budget: int | None = Field(default=None, ge=0, le=1000)
    max_connects_per_proposal: int | None = Field(default=None, ge=0, le=100)
    min_fit_score: float | None = Field(default=None, ge=0, le=1)
    min_budget_usd: int | None = Field(default=None, ge=0)
    hourly_rate_usd: int | None = Field(default=None, ge=0)
    saved_searches: list[SavedSearch] | None = None


class MemoryItem(BaseModel):
    memory_id: str
    kind: Literal["preference", "style", "fact", "outcome"]
    text: str
    source: str = Field(description="what produced it, e.g. 'edit on proposal p_204' or 'hire outcome'")
    created_at: str
    promoted: bool = Field(default=True, description="false = candidate waiting on the promotion rule")
    confidence: float = Field(default=0.8, ge=0, le=1)


class MemoryList(BaseModel):
    items: list[MemoryItem]


class Connection(BaseModel):
    provider: MarketplaceName
    connected: bool
    connected_at: str | None = None
    scopes: str = ""


class ConnectionList(BaseModel):
    connections: list[Connection]


class ConnectRequest(BaseModel):
    """Result of the OAuth dance. For GigSim this is the dev token; stored encrypted, never echoed."""

    access_token: str = Field(min_length=4, max_length=4000)
    refresh_token: str | None = Field(default=None, max_length=4000)
    scopes: str = Field(default="", max_length=300)


class PersonaOption(BaseModel):
    persona_id: str
    display_name: str
    headline: str
    skills: list[str] = Field(default_factory=list)
    hourly_rate_usd: int = 0


class OwnProfile(BaseModel):
    display_name: str = Field(max_length=120)
    headline: str = Field(default="", max_length=200)
    skills: list[str] = Field(default_factory=list, max_length=40)


class OnboardingState(BaseModel):
    completed: bool
    persona_id: str | None = None
    marketplace: MarketplaceName = "gigsim"
    hourly_rate_usd: int | None = None
    min_budget_usd: int | None = None
    weekly_connects_budget: int | None = None
    personas: list[PersonaOption] = Field(default_factory=list)
    portfolio_files: list[PortfolioFile] = Field(default_factory=list)


class OnboardingRequest(BaseModel):
    persona_id: str | None = Field(default=None, description="one of the sample personas")
    own_profile: OwnProfile | None = Field(default=None, description="used instead of a persona")
    marketplace: MarketplaceName = "gigsim"
    hourly_rate_usd: int = Field(default=65, ge=0, le=1000)
    min_budget_usd: int = Field(default=300, ge=0)
    weekly_connects_budget: int = Field(default=60, ge=0, le=1000)


class PortfolioFile(BaseModel):
    file_id: str
    filename: str
    size_bytes: int
    status: Literal["queued", "indexed", "failed"] = "queued"
    created_at: str


OnboardingState.model_rebuild()
