from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class AzureOpenAIConfig:
    auth_mode: str
    endpoint: str | None
    api_key: str | None
    deployment: str | None
    api_version: str
    token_scope: str
    tenant_id: str | None
    azure_cli_process_timeout_seconds: int

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.endpoint:
            missing.append("AZURE_OPENAI_ENDPOINT")
        if self.auth_mode == "api_key" and not self.api_key:
            missing.append("AZURE_OPENAI_API_KEY")
        if not self.deployment:
            missing.append("AZURE_OPENAI_DEPLOYMENT")
        return missing


@dataclass(frozen=True)
class PdfConfig:
    dpi: int
    image_format: str


@dataclass(frozen=True)
class ExtractionConfig:
    prompt_path: Path
    output_root: Path
    image_detail: str | None
    max_tokens: int
    token_parameter: str
    temperature: float | None
    response_format: str | None
    max_retries: int
    retry_base_delay_seconds: float
    request_delay_seconds: float
    save_raw_responses: bool
    continue_on_error: bool


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    azure_openai: AzureOpenAIConfig
    pdf: PdfConfig
    extraction: ExtractionConfig


def load_config(config_path: str | Path) -> AppConfig:
    resolved_config_path = Path(config_path).expanduser().resolve()
    project_root = resolved_config_path.parent
    load_dotenv(project_root / ".env")

    with resolved_config_path.open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}

    azure_data = data.get("azure_openai", {}) or {}
    pdf_data = data.get("pdf", {}) or {}
    extraction_data = data.get("extraction", {}) or {}

    auth_mode_env = azure_data.get("auth_mode_env", "AZURE_OPENAI_AUTH_MODE")
    endpoint_env = azure_data.get("endpoint_env", "AZURE_OPENAI_ENDPOINT")
    api_key_env = azure_data.get("api_key_env", "AZURE_OPENAI_API_KEY")
    deployment_env = azure_data.get("deployment_env", "AZURE_OPENAI_DEPLOYMENT")
    api_version_env = azure_data.get("api_version_env", "AZURE_OPENAI_API_VERSION")
    tenant_id_env = azure_data.get("tenant_id_env", "AZURE_TENANT_ID")

    response_format = extraction_data.get("response_format", "json_object")
    if isinstance(response_format, str) and response_format.lower() in {"", "none", "null"}:
        response_format = None

    prompt_path = _resolve_path(project_root, extraction_data.get("prompt_path", "prompts/extraction_prompt.md"))
    output_root = _resolve_path(project_root, extraction_data.get("output_root", "outputs"))

    return AppConfig(
        project_root=project_root,
        azure_openai=AzureOpenAIConfig(
            auth_mode=_normalize_auth_mode(os.getenv(auth_mode_env) or azure_data.get("auth_mode") or "azure_cli"),
            endpoint=_optional_secret(os.getenv(endpoint_env) or azure_data.get("endpoint")),
            api_key=_optional_secret(os.getenv(api_key_env) or azure_data.get("api_key")),
            deployment=_optional_secret(os.getenv(deployment_env) or azure_data.get("deployment")),
            api_version=(
                os.getenv(api_version_env)
                or azure_data.get("api_version")
                or azure_data.get("default_api_version")
                or "v1"
            ),
            token_scope=str(azure_data.get("token_scope", "auto")),
            tenant_id=_optional_secret(os.getenv(tenant_id_env) or azure_data.get("tenant_id")),
            azure_cli_process_timeout_seconds=int(azure_data.get("azure_cli_process_timeout_seconds", 60)),
        ),
        pdf=PdfConfig(
            dpi=int(pdf_data.get("dpi", 150)),
            image_format=str(pdf_data.get("image_format", "png")).lower(),
        ),
        extraction=ExtractionConfig(
            prompt_path=prompt_path,
            output_root=output_root,
            image_detail=extraction_data.get("image_detail", "high"),
            max_tokens=int(extraction_data.get("max_tokens", 4096)),
            token_parameter=str(extraction_data.get("token_parameter", "max_tokens")),
            temperature=_optional_float(extraction_data.get("temperature", 0)),
            response_format=response_format,
            max_retries=int(extraction_data.get("max_retries", 3)),
            retry_base_delay_seconds=float(extraction_data.get("retry_base_delay_seconds", 2)),
            request_delay_seconds=float(extraction_data.get("request_delay_seconds", 0)),
            save_raw_responses=_optional_bool(extraction_data.get("save_raw_responses", True)),
            continue_on_error=_optional_bool(extraction_data.get("continue_on_error", True)),
        ),
    )


def _resolve_path(project_root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return project_root / path


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and value.lower() in {"", "none", "null"}:
        return None
    return float(value)


def _optional_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _optional_secret(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "none", "null", "undefined", "your_api_key_here"}:
        return None
    return text


def _normalize_auth_mode(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "key": "api_key",
        "apikey": "api_key",
        "aad": "default_credential",
        "entra": "default_credential",
        "default": "default_credential",
        "cli": "azure_cli",
    }
    return aliases.get(normalized, normalized)
