from __future__ import annotations

import base64
import json
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

from azure.identity import AzureCliCredential, DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI, OpenAI

from .config import AppConfig


class ExtractionError(RuntimeError):
    """Raised when a page cannot be extracted as valid JSON."""


@dataclass(frozen=True)
class ExtractionResult:
    json_payload: Any
    raw_text: str
    raw_response: dict[str, Any] | None


class PageExtractor:
    def __init__(self, config: AppConfig):
        missing_fields = config.azure_openai.missing_fields()
        if missing_fields:
            joined_fields = ", ".join(missing_fields)
            raise ValueError(f"Missing Azure OpenAI settings: {joined_fields}")

        self.config = config
        self.client = _create_azure_openai_client(config)
        self.prompt_template = Template(config.extraction.prompt_path.read_text(encoding="utf-8"))

    def extract_page(
        self,
        document_name: str,
        page_number: int,
        total_pages: int,
        image_path: Path,
    ) -> ExtractionResult:
        prompt = self.prompt_template.safe_substitute(
            document_name=document_name,
            page_number=page_number,
            total_pages=total_pages,
            image_file=image_path.name,
        )
        data_url = local_image_to_data_url(image_path)
        messages = [
            {
                "role": "system",
                "content": "You extract structured data from document page images and respond with valid JSON only.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": _image_payload(data_url, self.config.extraction.image_detail),
                    },
                ],
            },
        ]

        last_error: Exception | None = None
        for attempt in range(1, self.config.extraction.max_retries + 1):
            try:
                response = self.client.chat.completions.create(**self._request_payload(messages))
                raw_text = _message_text(response.choices[0].message.content)
                return ExtractionResult(
                    json_payload=parse_json_response(raw_text),
                    raw_text=raw_text,
                    raw_response=response.model_dump() if self.config.extraction.save_raw_responses else None,
                )
            except Exception as error:
                last_error = error
                if attempt < self.config.extraction.max_retries:
                    time.sleep(self.config.extraction.retry_base_delay_seconds * attempt)

        raise ExtractionError(f"Failed to extract page {page_number}: {last_error}")

    def _request_payload(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.azure_openai.deployment,
            "messages": messages,
        }

        token_parameter = self.config.extraction.token_parameter
        if token_parameter:
            payload[token_parameter] = self.config.extraction.max_tokens

        if self.config.extraction.temperature is not None:
            payload["temperature"] = self.config.extraction.temperature

        if self.config.extraction.response_format:
            payload["response_format"] = {"type": self.config.extraction.response_format}

        return payload


def local_image_to_data_url(image_path: str | Path) -> str:
    resolved_path = Path(image_path).expanduser().resolve()
    mime_type, _ = mimetypes.guess_type(resolved_path)
    if mime_type is None:
        mime_type = "image/png"

    encoded_data = base64.b64encode(resolved_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded_data}"


def _create_azure_openai_client(config: AppConfig) -> Any:
    if _uses_v1_api(config):
        client_options: dict[str, Any] = {
            "base_url": _v1_base_url(config.azure_openai.endpoint),
        }
    else:
        client_options = {
            "api_version": config.azure_openai.api_version,
            "azure_endpoint": config.azure_openai.endpoint,
        }

    if config.azure_openai.auth_mode == "api_key":
        client_options["api_key"] = config.azure_openai.api_key
    elif config.azure_openai.auth_mode == "azure_cli":
        credential = _azure_cli_credential(config)
        token_provider = get_bearer_token_provider(credential, _token_scope(config))
        if _uses_v1_api(config):
            client_options["api_key"] = token_provider
        else:
            client_options["azure_ad_token_provider"] = token_provider
    elif config.azure_openai.auth_mode == "default_credential":
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(credential, _token_scope(config))
        if _uses_v1_api(config):
            client_options["api_key"] = token_provider
        else:
            client_options["azure_ad_token_provider"] = token_provider
    else:
        raise ValueError(
            "Unsupported Azure OpenAI auth_mode "
            f"'{config.azure_openai.auth_mode}'. Use azure_cli, default_credential, or api_key."
        )

    if _uses_v1_api(config):
        return OpenAI(**client_options)
    return AzureOpenAI(**client_options)


def _uses_v1_api(config: AppConfig) -> bool:
    return config.azure_openai.api_version.strip().lower() == "v1"


def _v1_base_url(endpoint: str | None) -> str:
    if not endpoint:
        raise ValueError("AZURE_OPENAI_ENDPOINT is required.")
    return f"{endpoint.rstrip('/')}/openai/v1/"


def _azure_cli_credential(config: AppConfig) -> AzureCliCredential:
    credential_kwargs: dict[str, Any] = {
        "process_timeout": config.azure_openai.azure_cli_process_timeout_seconds,
    }
    if config.azure_openai.tenant_id:
        credential_kwargs["tenant_id"] = config.azure_openai.tenant_id
    return AzureCliCredential(**credential_kwargs)


def _token_scope(config: AppConfig) -> str:
    configured_scope = config.azure_openai.token_scope.strip()
    if configured_scope and configured_scope.lower() != "auto":
        return configured_scope
    if _uses_v1_api(config):
        return "https://ai.azure.com/.default"
    return "https://cognitiveservices.azure.com/.default"


def parse_json_response(raw_text: str) -> Any:
    cleaned_text = _strip_markdown_fence(raw_text.strip())
    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError:
        pass

    json_start = min(
        [position for position in (cleaned_text.find("{"), cleaned_text.find("[")) if position >= 0],
        default=-1,
    )
    json_end = max(cleaned_text.rfind("}"), cleaned_text.rfind("]"))
    if json_start >= 0 and json_end > json_start:
        try:
            return json.loads(cleaned_text[json_start:json_end + 1])
        except json.JSONDecodeError as error:
            raise ExtractionError(f"Model response was not valid JSON: {error}") from error

    raise ExtractionError("Model response did not contain a JSON object or array.")


def _image_payload(data_url: str, detail: str | None) -> dict[str, str]:
    payload = {"url": data_url}
    if detail:
        payload["detail"] = detail
    return payload


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(str(part.get("text", "")))
            else:
                text_parts.append(str(part))
        return "\n".join(text_parts)
    return str(content)


def _strip_markdown_fence(text: str) -> str:
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text
