# Creative Performance Insight Agent

**Claw-a-thon 2026 — Data Analysis Track**

AI agent phân tích creative performance cho UA campaigns — tự động từ raw campaign CSV đến insight report.

## Problem

UA/Growth teams mất 30–60 phút mỗi ngày đọc campaign data thủ công để tìm creative nào nên scale, maintain, hay pause. Quy trình này không nhất quán và không accessible cho non-OM members.

## Solution

Agent nhận CSV campaign data → tự động:
1. Parse campaign name theo naming convention (ZPI_ + AEO-)
2. Tách creative source: TTO vs Freelance (TikTok), Scheme clusters (Moloco)
3. Tính Quality Score = f(CTR, login rate, CP Login vs plan)
4. Gọi Qwen model để sinh narrative insight
5. Trả về report với SCALE / MAINTAIN / PAUSE decision

## Quick Start

```bash
# 1. Clone và setup
git clone <repo>
cd clawathon-creative-agent
cp .env.example .env
# Điền LLM_ENDPOINT và LLM_API_KEY vào .env

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run local
uvicorn app:app --reload --port 8000

# 4. Test với sample data
curl -X POST http://localhost:8000/analyze \
  -F "file=@demo/sample_input.csv"
```

Mở http://localhost:8000 để xem UI và docs.

## CSV Input Format

| Column | Required | Description |
|---|---|---|
| `campaign_name` | ✅ | Full campaign name (ZPI_ format) |
| `ad_name` | ❌ | Ad/creative name (Moloco only) |
| `date` | ❌ | Date (YYYY-MM-DD) |
| `cost_usd` | ✅ | Spend in USD |
| `impressions` | ✅ | Total impressions |
| `clicks` | ✅ | Total clicks |
| `installs` | ✅ | Total installs |
| `logins` | ✅ | New logins (login_success) |
| `npu` | ✅ | New payment users |

Download sample: `GET /sample-csv`

## Architecture

```
CSV Upload
    ↓
Campaign Parser (ZPI_ + AEO- filter, entity extraction)
    ↓
Metrics Calculator (Quality Score, CP Login, CTR, login rate)
    ↓
Qwen LLM (narrative insight via GreenNode MaaS)
    ↓
Insight Report (Markdown + JSON)
```

## Deployment

Deployed on GreenNode AgentBase. See `.env.example` for configuration.

## Data

Uses **synthetic mock data only**. No production data, no PII, no internal campaign data.
