# PDF Vision Extraction Agent

A small Python agent for extracting structured JSON from PDF pages with an Azure OpenAI vision-enabled deployment.

The agent:

1. Takes a PDF as input.
2. Renders each selected page to a PNG image with PyMuPDF.
3. Sends each page image to Azure OpenAI with the extraction prompt.
4. Saves one parsed JSON file per page, plus optional raw model responses for debugging.

The extraction prompt lives in [prompts/extraction_prompt.md](prompts/extraction_prompt.md), so you can tune the prompt and JSON shape without changing code.

## Requirements

- Python 3.10 or newer.
- An Azure OpenAI resource with a deployed model that supports image input.
- Azure CLI authentication, or an Azure OpenAI API key if you choose `api_key` mode.

## Setup

```bash
cd content-extraction-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Authenticate with Azure CLI and confirm the account you want to use:

```bash
az login
az account show --output table
```

Your signed-in identity must have a data-plane role such as `Cognitive Services User` on the Azure OpenAI resource.

Edit `.env` and set:

```bash
AZURE_OPENAI_AUTH_MODE=azure_cli
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE-NAME.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=YOUR_VISION_MODEL_DEPLOYMENT_NAME
AZURE_OPENAI_API_VERSION=v1
```

If you are working across tenants, also set `AZURE_TENANT_ID` in `.env`. If API keys are enabled in a different environment, set `azure_openai.auth_mode: api_key` in [config.yaml](config.yaml) and provide `AZURE_OPENAI_API_KEY`.

`AZURE_OPENAI_API_VERSION=v1` uses the current Azure OpenAI v1 API and avoids dated preview API-version churn. If your resource or deployment needs the older Azure OpenAI API path, set `AZURE_OPENAI_API_VERSION` to a dated version such as `2024-12-01-preview`.

## Run

```bash
source .venv/bin/activate
python -m docs_agent --pdf /path/to/document.pdf
```

Process only a range of pages:

```bash
python -m docs_agent --pdf /path/to/document.pdf --pages 1-5
```

Render pages without calling Azure OpenAI:

```bash
python -m docs_agent --pdf /path/to/document.pdf --dry-run
```

Use a custom run id for the document output directory:

```bash
python -m docs_agent --pdf /path/to/document.pdf --run-id invoice-test-001
```

Run from a custom configuration file:

```bash
python -m docs_agent --pdf /path/to/document.pdf --config config.yaml
```

## Output Layout

Each run creates a new directory under `outputs/`:

```text
outputs/
  document-name_20260526_153000/
    pages/
      page_0001.png
      page_0002.png
    json/
      page_0001.json
      page_0002.json
    raw_responses/
      page_0001.response.json
      page_0002.response.json
    errors/
      page_0003.error.json
    manifest.json
```

The page JSON files in `json/` contain the parsed model response. Raw Azure OpenAI responses are saved separately for debugging when `save_raw_responses: true` in [config.yaml](config.yaml).

Generated outputs are written under `outputs/`, which is ignored by git. Keep PDFs and other local test documents under `examples/`; that directory is also ignored.

## Configuration

Most runtime settings are in [config.yaml](config.yaml):

- `azure_openai.auth_mode`: defaults to `azure_cli`, which reuses your `az login` session.
- `azure_openai.default_api_version`: defaults to `v1`, which uses `/openai/v1/` and does not send a dated `api-version` query parameter.
- `azure_openai.token_scope`: defaults to `auto`; v1 uses `https://ai.azure.com/.default`, dated APIs use `https://cognitiveservices.azure.com/.default`.
- `azure_openai.azure_cli_process_timeout_seconds`: timeout for the internal `az account get-access-token` call.
- `pdf.dpi`: controls page render quality. Higher DPI costs more tokens because images are larger.
- `extraction.prompt_path`: prompt template file.
- `extraction.output_root`: parent directory for per-document run folders.
- `extraction.image_detail`: Azure OpenAI image detail mode: `low`, `high`, or `auto`.
- `extraction.response_format`: defaults to `json_object`; set to `none` if your deployment does not support JSON mode.
- `extraction.token_parameter`: set to `max_completion_tokens` for your `gpt-5.4` deployment; older chat models may use `max_tokens`.
- `extraction.continue_on_error`: when true, failed pages are written to `errors/` and the run continues.

## Prompt Tuning

Edit [prompts/extraction_prompt.md](prompts/extraction_prompt.md). The agent substitutes these variables:

- `$document_name`
- `$page_number`
- `$total_pages`
- `$image_file`

Keep the prompt strict about returning JSON only. The agent validates the response and retries invalid JSON according to `max_retries`.
