# HANDOVER — Creative Performance Insight Agent
**Claw-a-thon 2026 · Data Analysis Track**
**Cập nhật:** 2026-06-10 · **Đọc file này TRƯỚC khi làm bất cứ điều gì**

---

## 1. Project là gì

AI agent phân tích **creative performance** cho UA campaigns của Zalopay.

- Input: CSV campaign data (ZPI_ naming convention)
- Engine: parse campaign → tính Quality Score → call Qwen LLM → sinh insight report
- Output: Markdown report với SCALE / MAINTAIN / PAUSE decision per creative
- Deploy: GreenNode AgentBase (Claw-a-thon requirement)

**Use case mở rộng:** Không chỉ OM team — Growth starters không phải OM cũng dùng được vì agent tự parse và giải thích, không cần biết campaign naming convention.

---

## 2. Current State — ĐÃ XONG

| Hạng mục | Status |
|---|---|
| Campaign parser (ZPI_+AEO- filter, TTO/Freelance/Moloco) | ✅ Done |
| Metrics engine (Quality Score, CP Login, vs plan) | ✅ Done |
| Report builder (LLM prompt + Markdown formatter) | ✅ Done |
| FastAPI app (`/analyze` endpoint) | ✅ Done |
| Mock data (`demo/sample_input.csv`) | ✅ Done |
| Dockerfile | ✅ Done |
| Test local pass | ✅ 10 entities parsed, TTO/Freelance/Moloco đúng |
| AgentBase skills imported | ✅ `.claude/skills/` |
| **Deploy lên AgentBase** | ⏳ **VIỆC CẦN LÀM TIẾP THEO** |

---

## 3. File Structure

```
Build Agent/
├── CLAUDE.md                  ← file này
├── app.py                     ← FastAPI main, /analyze endpoint
├── analysis/
│   ├── parser.py              ← campaign name parser, TTO/Freelance/Moloco
│   ├── metrics.py             ← Quality Score, CP Login, vs plan benchmark
│   └── report.py              ← LLM prompt builder + Markdown formatter
├── demo/
│   └── sample_input.csv       ← mock data 26 rows, 4 channels
├── Dockerfile                 ← python:3.11-slim, port 8000
├── requirements.txt
├── .env.example               ← LLM_ENDPOINT, LLM_API_KEY, LLM_MODEL
├── README.md
└── .claude/skills/            ← agentbase-wizard, agentbase-deploy etc
    ├── agentbase-wizard/
    ├── agentbase-deploy/
    └── ...
```

---

## 4. VIỆC CẦN LÀM NGAY — Deploy lên AgentBase

**Bước 1:** Đảm bảo Docker Desktop đang chạy

**Bước 2:** Chạy agentbase-wizard skill:
```
Dùng skill trong folder này để deploy agent lên AgentBase
```

**Bước 3:** Khi skill hỏi, điền:
- **Client ID**: lấy từ GreenNode AI Portal → IAM
- **Client Secret**: lấy từ GreenNode AI Portal → IAM
- **API Key (MaaS)**: lấy từ GreenNode AI Portal → MaaS
- **Model**: `Qwen-3-27B`
- **Runtime**: `2x4` (2 vCPU / 4GB RAM)
- **Port**: `8000`

**Bước 4:** Sau khi deploy xong:
- Vào Portal → AgentBase → kiểm tra status **ACTIVE**
- Copy endpoint URL
- Test: `POST <endpoint>/analyze` với `demo/sample_input.csv`

---

## 5. API Reference

### POST /analyze
Upload CSV → nhận insight report

**Request:** `multipart/form-data`, field `file` = CSV

**Required CSV columns:**
```
campaign_name, cost_usd, impressions, clicks, installs, logins, npu
```

**Optional:** `ad_name` (Moloco), `date`

**Response:**
```json
{
  "status": "ok",
  "rows_processed": 26,
  "entities_analyzed": 10,
  "report_markdown": "# Creative Performance Insight Report...",
  "metrics_summary": [
    {
      "entity": "ZPI_...",
      "channel": "TikTok",
      "os": "Android",
      "source": "TTO",
      "ctr_pct": 2.1,
      "login_rate_pct": 46.8,
      "cp_login_vnd": 53094,
      "vs_plan_pct": 32.7,
      "quality_score": 6.8,
      "decision": "PAUSE"
    }
  ]
}
```

### GET /sample-csv
Download mock data để test

### GET /health
Health check + LLM config status

---

## 6. Core Logic Rules (KHÔNG THAY ĐỔI)

### Campaign Filter (2 bước bắt buộc)
1. Field 1 = `ZPI_` (team prefix)
2. Field 4 bắt đầu bằng `AEO-` (optimization event)
3. Loại `RET-`, `SEM`, và mọi prefix khác (ZFS_, DGS_, MKT_...)

### Creative Source Identification
- TikTok + field 5 chứa `Tiktok One` → **TTO**
- TikTok + không có `Tiktok One` → **Freelance**
- `Tiktok FS` (field 8) → **Freelance**
- Moloco → parse ad_name: `Scheme_USP_Team_Format_ContentID_ScriptID_V_Size_Date`

### Quality Score Formula
```
QS = CTR_score(30%) + LoginRate_score(40%) + CPLogin_vs_plan_score(30%)
```
- QS ≥ 7.5 + vs_plan ≤ +10% → **SCALE**
- QS ≥ 6.0 + vs_plan ≤ +30% → **MAINTAIN**
- Otherwise → **PAUSE**

### FX & Cost Rules
- `1 USD = 26,300 VND`
- TikTok: `cost_vnd = cost_usd × 26,300 × 1.05` (FCT 5%)
- Google / Facebook / Moloco: không có surcharge

### Primary KPI
- **CP Login** (cost per new login) — không phải CPI, không phải CTR alone
- Plan benchmark mặc định nếu không có plan file:
  - Google Android 24k / iOS 30k
  - TikTok Android 40k / iOS 40k
  - Moloco Android 32k / iOS 36k

---

## 7. LLM Configuration

Sau khi có AgentBase endpoint + API Key, tạo `.env`:
```
LLM_ENDPOINT=https://maas.greennode.ai/v1
LLM_API_KEY=<api_key_từ_portal>
LLM_MODEL=Qwen-3-27B
```

Nếu chưa có `.env`, app vẫn chạy — trả về rule-based analysis thay vì LLM narrative.

---

## 8. Test Results (Local — 2026-06-10)

```
Entities: 10
Google Android | QS=7.1 | CP=18,841 | MAINTAIN
Google Android | QS=6.8 | CP=21,437 | MAINTAIN
TikTok Android | TTO    | QS=6.8 | CP=53,094 | PAUSE
TikTok iOS     | TTO    | QS=6.4 | CP=62,803 | PAUSE
TikTok Android | Freelance | QS=6.0 | CP=97,325 | PAUSE  ← drag source
Moloco Android | Grab scheme | QS=5.7 | CP=69,904 | PAUSE
```
TTO vs Freelance split: ✅ chính xác
Moloco scheme parse: ✅ chính xác (Grab / ScanQR / Billing)

---

## 9. Submission Checklist (deadline 17/06 12:00)

- [ ] Agent deploy trên AgentBase → status ACTIVE
- [ ] BTC có thể gọi endpoint thành công
- [ ] GitHub repo public (không commit .env)
- [ ] Video demo 2–3 phút
- [ ] Project description ≤ 300 chữ
- [ ] README.md đầy đủ
- [ ] sample_input.csv trong repo

---

## 10. Recommended Model cho Claude Code session này
`claude-opus-4-6` — cần reasoning quality cao cho deploy + debug.
Set: `/model claude-opus-4-6`
