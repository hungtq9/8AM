"""
Creative Performance Insight Agent
Claw-a-thon 2026 — Data Analysis Track

Flow:
  Upload CSV → Parse campaigns → Calculate metrics → LLM insight → Return report
"""

import os
import io
import httpx
import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from analysis.parser import parse_campaign
from analysis.metrics import aggregate_metrics
from analysis.report import build_llm_prompt, format_markdown_report

app = FastAPI(
    title="Creative Performance Insight Agent",
    description="Phân tích creative performance từ UA campaign data. Claw-a-thon 2026.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REQUIRED_COLUMNS = {"campaign_name", "cost_usd", "impressions", "clicks", "installs", "logins", "npu"}
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen-3-27B")


@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <html><body style="font-family:sans-serif;padding:40px;background:#f5f5f5">
    <h1>🎯 Creative Performance Insight Agent</h1>
    <p>Upload campaign CSV → Get creative insight report</p>
    <h3>Endpoints:</h3>
    <ul>
      <li><code>POST /analyze</code> — Upload CSV, get Markdown report</li>
      <li><code>GET /sample-csv</code> — Download sample input CSV</li>
      <li><code>GET /health</code> — Health check</li>
      <li><a href="/docs">📄 API Docs (Swagger)</a></li>
    </ul>
    <h3>Required CSV columns:</h3>
    <code>campaign_name, ad_name (optional), date, cost_usd, impressions, clicks, installs, logins, npu</code>
    </body></html>
    """


@app.get("/health")
async def health():
    return {"status": "ok", "model": LLM_MODEL, "llm_configured": bool(LLM_ENDPOINT and LLM_API_KEY)}


@app.get("/sample-csv")
async def sample_csv():
    """Return sample CSV content for testing."""
    import pathlib
    sample_path = pathlib.Path(__file__).parent / "demo" / "sample_input.csv"
    if sample_path.exists():
        return HTMLResponse(
            content=sample_path.read_text(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=sample_input.csv"}
        )
    raise HTTPException(404, "Sample file not found")


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """
    Upload a CSV file with UA campaign data.
    Returns a creative performance insight report.
    """
    # 1. Read & validate CSV
    content = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(400, f"Cannot parse CSV: {e}")

    df.columns = [c.strip().lower() for c in df.columns]
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise HTTPException(400, {
            "error": "Missing required columns",
            "missing": sorted(missing),
            "required": sorted(REQUIRED_COLUMNS),
            "tip": "Download /sample-csv for the correct format."
        })

    # Fill optional columns
    if "ad_name" not in df.columns:
        df["ad_name"] = None
    if "date" not in df.columns:
        df["date"] = "2026-06-01"

    # 2. Parse entities
    parsed_rows = []
    skipped = 0
    for _, row in df.iterrows():
        entity = parse_campaign(
            str(row["campaign_name"]),
            str(row["ad_name"]) if pd.notna(row.get("ad_name")) else None
        )
        if not entity.is_valid_zpi:
            skipped += 1
            continue
        parsed_rows.append({
            **row.to_dict(),
            "analysis_entity_name": entity.analysis_entity_name,
            "channel": entity.channel,
            "os": entity.os,
            "creative_source": entity.creative_source,
            "use_case": entity.use_case,
            "scheme": entity.scheme,
        })

    if not parsed_rows:
        raise HTTPException(422, {
            "error": "No valid ZPI_ + AEO- campaigns found",
            "skipped_rows": skipped,
            "tip": "Campaign name must start with ZPI_ and field 4 must begin with AEO-"
        })

    parsed_df = pd.DataFrame(parsed_rows)

    # 3. Calculate metrics
    metrics = aggregate_metrics(parsed_df)

    # 4. Build LLM prompt
    prompt = build_llm_prompt(metrics)

    # 5. Call LLM (Qwen via AgentBase/MaaS)
    narrative = await _call_llm(prompt)

    # 6. Format final report
    report_md = format_markdown_report(metrics, narrative)

    return JSONResponse({
        "status": "ok",
        "rows_processed": len(parsed_rows),
        "rows_skipped": skipped,
        "entities_analyzed": len(metrics),
        "report_markdown": report_md,
        "metrics_summary": [
            {
                "entity": m.entity_name[:60],
                "channel": m.channel,
                "os": m.os,
                "source": m.creative_source,
                "ctr_pct": m.ctr,
                "login_rate_pct": m.login_rate,
                "cp_login_vnd": m.cp_login_vnd,
                "vs_plan_pct": m.vs_plan_pct,
                "quality_score": m.quality_score,
                "decision": m.decision,
            }
            for m in metrics
        ],
    })


async def _call_llm(prompt: str) -> str:
    """Call Qwen model via OpenAI-compatible endpoint."""
    if not LLM_ENDPOINT or not LLM_API_KEY:
        return _fallback_narrative()

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{LLM_ENDPOINT}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1500,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"*LLM unavailable ({e}). Showing rule-based analysis only.*\n\n{_fallback_narrative()}"


def _fallback_narrative() -> str:
    return """## TL;DR
Creative analysis complete. LLM endpoint not configured — showing rule-based output.
Set LLM_ENDPOINT and LLM_API_KEY environment variables to enable AI narrative.

## Creative Signals
- Quality Score computed from CTR, login rate, and CP Login vs plan benchmark
- TTO vs Freelance split applied for TikTok campaigns
- Moloco creative clusters identified from ad name parsing

## Next Action
1. Configure LLM_ENDPOINT and LLM_API_KEY in .env
2. Re-run analysis for full AI narrative insight
"""
