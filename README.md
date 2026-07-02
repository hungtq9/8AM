# Creative Performance Insight Agent

Claw-a-thon 2026 - Data Analysis Track

AI agent phân tích kết quả creative performance thực tế từ CSV/xlsx (campaign/export data), tạo dashboard insight giúp Growth/UA team biết creative nào win/lost, insight đằng sau là gì và next action là gì.

## What It Does

- Upload CSV/XLSX performance data.
- Map raw fields and select Primary Metric(s).
- Analyze by mode: UA, Retargeting, Other; channel groups include SRN/Paid Social, Programmatic/In-app Banner, and Owned/Lifecycle.
- Calculate Quality Score and action-aware metrics.
- Generate Key Learning, Bottleneck, Next Step, Winning -> Why It Wins -> Worst Signal, Creative Detail, and Action Plan.
- Optional Qwen/GreenNode MaaS narrative via environment variables.

## Project Structure

```text
Build Agent/
|-- app.py
|-- analysis/
|-- static/
|   |-- index.html
|   |-- Thumbnail.png
|-- demo/
|   `-- sample_input.csv
|-- Dockerfile
|-- requirements.txt
|-- .env.example
`-- README.md
```

## Local Run

```powershell
cd "C:\Users\LAP15681\OneDrive - VNG Corporation\Build Agent"
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/?v=2026-06-26.34
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

## API

### GET /health

Returns build and LLM configuration status.

### GET /

Serves the dashboard UI from `static/index.html`.

### POST /api/upload-csv

Uploads CSV/XLSX for preview and field mapping.

### POST /api/analyze

Runs the analysis. The dashboard sends multipart form data including the performance file, selected fields, Primary Metric(s), channel/mode, scoring config, and Analysis Brief.

### GET /sample-csv

Downloads demo sample data.

## Deployment

The Docker container listens on port `8080`.

AgentBase runtime must be configured with:

```text
Port: 8080
```

Dockerfile command:

```text
uvicorn app:app --host 0.0.0.0 --port 8080
```

Recommended AgentBase environment variables:

```text
LLM_ENDPOINT=https://maas.greennode.ai/v1
LLM_API_KEY=<set in AgentBase secret/env, do not commit>
LLM_MODEL=Qwen-3-27B
```

Do not commit `.env`, `.greennode.json`, `.agentbase*`, real customer data, logs, cache, or files under `Test data/`.

## Data Notice

`demo/sample_input.csv` is safe demo data. Real campaign exports and internal testing files must stay local and must not be pushed to a public repository.
