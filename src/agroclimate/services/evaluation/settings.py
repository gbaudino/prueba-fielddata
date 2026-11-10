from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvaluationSettings(BaseSettings):
    interval_seconds: float = Field(gt=0)
    timeout_seconds: float = Field(gt=0)

    model_config = SettingsConfigDict(
        env_prefix="EVALUATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_evaluation_settings() -> EvaluationSettings:
    return EvaluationSettings()  # type: ignore[call-arg]
