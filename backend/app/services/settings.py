"""Validated settings models, defaults, and persistence helpers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from ..models import Setting, utcnow


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExactRepetitionConfig(StrictModel):
    enabled: bool = True
    min_occurrences: int = Field(3, ge=2, le=25)
    window: int = Field(25, ge=5, le=200)
    require_no_progress: bool = True


class SemanticRepetitionConfig(StrictModel):
    enabled: bool = True
    min_occurrences: int = Field(4, ge=3, le=25)
    window: int = Field(25, ge=5, le=200)
    similarity_threshold: float = Field(0.9, ge=0.5, le=1.0)


class OscillationConfig(StrictModel):
    enabled: bool = True
    min_cycles: int = Field(2, ge=2, le=12)
    window: int = Field(25, ge=6, le=200)


class RepeatedFailureConfig(StrictModel):
    enabled: bool = True
    min_failures: int = Field(3, ge=2, le=25)
    window: int = Field(30, ge=5, le=200)


class NoProgressConfig(StrictModel):
    enabled: bool = True
    min_events: int = Field(8, ge=4, le=100)
    window: int = Field(30, ge=5, le=200)


class BudgetConfig(StrictModel):
    enabled: bool = True
    max_tool_calls: int = Field(60, ge=5, le=10000)
    max_duration_seconds: int = Field(3600, ge=60, le=86400)
    max_consecutive_failures: int = Field(5, ge=2, le=100)
    max_tokens: int | None = Field(None, ge=1000)
    max_cost_usd: float | None = Field(None, ge=0.01)


class DetectionSettings(StrictModel):
    exact_repetition: ExactRepetitionConfig = Field(default_factory=ExactRepetitionConfig)
    semantic_repetition: SemanticRepetitionConfig = Field(default_factory=SemanticRepetitionConfig)
    oscillation: OscillationConfig = Field(default_factory=OscillationConfig)
    repeated_failure: RepeatedFailureConfig = Field(default_factory=RepeatedFailureConfig)
    no_progress: NoProgressConfig = Field(default_factory=NoProgressConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)

    def merged_with(self, override: dict[str, Any] | None) -> "DetectionSettings":
        if not override:
            return self
        base = self.model_dump()
        for section, values in override.items():
            if section in base and isinstance(values, dict):
                base[section].update({k: v for k, v in values.items() if k in base[section]})
        return DetectionSettings.model_validate(base)


INTERVENTION_MODES = ("observe", "notify", "approval_required", "automatic")
DEFAULT_INTERVENTION_MODE = "approval_required"
DEFAULT_RETENTION_DAYS = 30


class GeneralSettings(StrictModel):
    retention_days: int = Field(DEFAULT_RETENTION_DAYS, ge=1, le=365)
    redaction_enabled: bool = True
    redaction_keys: list[str] = Field(default_factory=list)
    intervention_mode: str = DEFAULT_INTERVENTION_MODE
    ai_enabled: bool = False
    ai_base_url: str = ""
    ai_model: str = ""

    @field_validator("intervention_mode")
    @classmethod
    def _validate_mode(cls, value: str) -> str:
        if value not in INTERVENTION_MODES:
            raise ValueError(f"intervention_mode must be one of {', '.join(INTERVENTION_MODES)}")
        return value

    @field_validator("ai_base_url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        value = value.strip()
        if value and not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("ai_base_url must start with http:// or https://")
        return value.rstrip("/")

    @field_validator("redaction_keys")
    @classmethod
    def _clean_keys(cls, values: list[str]) -> list[str]:
        return sorted({v.strip().lower() for v in values if v.strip()})[:100]


DETECTION_SETTINGS_KEY = "detection"
GENERAL_SETTINGS_KEY = "general"


def get_detection_settings(db: Session, agent_configuration: dict[str, Any] | None = None) -> DetectionSettings:
    row = db.get(Setting, DETECTION_SETTINGS_KEY)
    base = DetectionSettings.model_validate(row.value) if row else DetectionSettings()
    if agent_configuration:
        override = agent_configuration.get("detection") if isinstance(agent_configuration, dict) else None
        if isinstance(override, dict):
            return base.merged_with(override)
    return base


def save_detection_settings(db: Session, settings: DetectionSettings) -> DetectionSettings:
    row = db.get(Setting, DETECTION_SETTINGS_KEY)
    if row is None:
        row = Setting(key=DETECTION_SETTINGS_KEY, value=settings.model_dump())
        db.add(row)
    else:
        row.value = settings.model_dump()
        row.updated_at = utcnow()
    db.flush()
    return settings


def get_general_settings(db: Session) -> GeneralSettings:
    row = db.get(Setting, GENERAL_SETTINGS_KEY)
    if row is None:
        return GeneralSettings()
    try:
        return GeneralSettings.model_validate(row.value)
    except Exception:
        # Corrupt/unknown stored settings must never take the app down.
        return GeneralSettings()


def save_general_settings(db: Session, settings: GeneralSettings) -> GeneralSettings:
    row = db.get(Setting, GENERAL_SETTINGS_KEY)
    if row is None:
        row = Setting(key=GENERAL_SETTINGS_KEY, value=settings.model_dump())
        db.add(row)
    else:
        row.value = settings.model_dump()
        row.updated_at = utcnow()
    db.flush()
    return settings


__all__ = [
    "DEFAULT_INTERVENTION_MODE",
    "DEFAULT_RETENTION_DAYS",
    "DETECTION_SETTINGS_KEY",
    "GENERAL_SETTINGS_KEY",
    "INTERVENTION_MODES",
    "DetectionSettings",
    "GeneralSettings",
    "get_detection_settings",
    "get_general_settings",
    "save_detection_settings",
    "save_general_settings",
]
