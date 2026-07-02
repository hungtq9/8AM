# HANDOVER — Creative Performance Insight Agent
**Claw-a-thon 2026 · Data Analysis Track**
**Cập nhật:** 2026-06-16 · **Đọc file này TRƯỚC khi làm bất cứ điều gì**

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
| Encoding fix (mojibake Vietnamese) | ✅ Done — hybrid CP1252 + Latin-1 |
| Channel resolution (user selection priority) | ✅ Done — không override bằng entity name |
| Format-aware skill routing | ✅ Done — Image vs Video dims đúng |
| Skill folder architecture (`analysis/skills/`) | ✅ Done — 6 modules |
| UI dropzone click fix | ✅ Done — `<label for>` thay JS `.click()` |
| **Deploy lên AgentBase** | ⏳ **VIỆC CẦN LÀM TIẾP THEO** |

---

## 3. File Structure

```
Build Agent/
├── CLAUDE.md                  ← file này
├── app.py                     ← FastAPI main (~2200 lines), tất cả logic UI + API
├── analysis/
│   ├── parser.py              ← campaign name parser, TTO/Freelance/Moloco
│   ├── metrics.py             ← Quality Score, CP Login, vs plan benchmark
│   ├── report.py              ← LLM prompt builder + Markdown formatter
│   └── skills/                ← skill router + per-channel/mode modules
│       ├── __init__.py        ← get_channel_skill() router
│       ├── general.py         ← fallback
│       ├── srn_tiktok.py      ← TikTok (Video / Image format-aware)
│       ├── srn_google.py      ← Google UAC
│       ├── srn_facebook.py    ← Meta / Facebook
│       ├── programmatic.py    ← Moloco / In-app Display (Image / Video banner)
│       └── notification.py    ← Push / In-app Message / Email
├── static/
│   └── index.html             ← Single-page UI (~1500 lines)
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

### Bugs đã fix (2026-06-16)

**Bug 1 — Mojibake encoding:**
- Vietnamese text bị garbled trong Warning banners và Key Takeaways
- Fix: `_fix_mojibake()` dùng hybrid CP1252 map + Latin-1 encode → UTF-8 decode
- Lý do không dùng pure CP1252: byte 0x90 undefined trong CP1252 nhưng là UTF-8 continuation của "Đ"

**Bug 2 — Channel detection sai (Tiktokshop):**
- Entity `Tiktokshop_..._Image_..._320x50` bị detect thành channel "TikTok" thay vì giữ user selection "In-app Display"
- Fix 1: `_guess_channel()` guard `"TIKTOK" in e and "TIKTOKSHOP" not in e`
- Fix 2: `_resolve_channel()` — nếu user chọn 1 channel → force toàn bộ, không override

**Bug 3 — Format-blind skill (Image entity → TikTok Video dims):**
- Entity format "Image" nhưng skill chạy TikTok Video (Hook/First 3s, Video Pacing, Sound)
- Fix: `_extract_format()` + `_extract_size()` detect từ extension + keyword trong tên
- Skill router dùng `format` field → programmatic.py phân nhánh `_analyze_image_banner()` vs `_analyze_video_banner()`

**Bug 4 — Dropzone không click được:**
- JS `.click()` trên `<input type="file">` fail sau khi `innerHTML` replace parent (DOM detach)
- Fix: đổi `<div id="csv-dz">` → `<label id="csv-dz" for="csv-in">`, move `<input>` ra ngoài label
- Browser natively mở file dialog khi click label — không cần JS handler
- Loading state chỉ replace `.dz-inner` content, label + input không bị touch

---

## 9. Submission Checklist (deadline 17/06 12:00)

- [ ] Hard refresh browser (Ctrl+Shift+R) sau khi restart uvicorn → verify dropzone click OK
- [ ] Agent deploy trên AgentBase → status ACTIVE
- [ ] BTC có thể gọi endpoint thành công
- [ ] GitHub repo public (không commit .env, không commit .greennode.json)
- [ ] Video demo 2–3 phút
- [ ] Project description ≤ 300 chữ
- [ ] README.md đầy đủ
- [ ] sample_input.csv trong repo

**Security constraints (bắt buộc giữ):**
- KHÔNG đọc hoặc print `.env` hay `.greennode.json`
- KHÔNG commit secrets
- Chỉ dùng public data, synthetic data, hoặc anonymized data — KHÔNG dùng customer data/PII

---

## 10. Recommended Model cho Claude Code session này
`claude-opus-4-6` — cần reasoning quality cao cho deploy + debug.
Set: `/model claude-opus-4-6`

---

## 11. EDITING RULES / GUARDRAILS — ĐỌC TRƯỚC KHI SỬA CODE

**Nguyên tắc số 1: giữ nguyên phần đang chạy tốt. Chỉ sửa đúng chỗ hỏng. KHÔNG sửa hàng loạt / refactor lan man.**
Một thay đổi rộng "cho sạch" mà chưa verify có thể phá vỡ hành vi đang đúng. Ưu tiên fix nhỏ, có chủ đích, kèm bằng chứng.

### Quy trình bắt buộc cho mỗi lần sửa
1. **Tái hiện bug** trước khi sửa — biết chính xác triệu chứng + dữ liệu gây ra.
2. **Tìm root cause thật** (đọc code, xác định dòng/hàm), đừng đoán rồi sửa đại.
3. **Xác định ranh giới**: cái gì đang đúng (giữ), cái gì sai (sửa). Ghi rõ trước khi đụng.
4. **Sửa tối thiểu**: edit đúng dòng/hàm, không đổi format/logic xung quanh.
5. **Verify sau sửa**:
   - app.py: chạy `/api/analyze` với `demo/sample_input.csv`, kiểm tra output (channels đúng, không còn mojibake, số entity hợp lý).
   - index.html: `node --check` trên hàm vừa sửa; xác nhận không vỡ template literal / brace.
   - So sánh trước–sau, đảm bảo phần khác KHÔNG đổi.
6. Nếu không chắc một thay đổi an toàn → **để lại, ghi chú, hỏi** thay vì tự ý sửa.

### Gotchas đã gặp (tránh lặp lại)

**A. Mojibake tiếng Việt — KHÔNG re-encode toàn file.**
Hầu hết chuỗi VN trong `app.py` lưu dạng mojibake và được sửa runtime bởi `_fix_mojibake()` — cơ chế này CHẠY ĐÚNG cho chuỗi mojibake thuần → **đừng đụng**.
Chỉ chuỗi **lẫn lộn** (vừa mojibake vừa có ký tự VN đã đúng) mới fail (vì `.encode('latin-1')` gặp ký tự >255 → trả nguyên chuỗi). Cách sửa đúng: **rewrite riêng chuỗi nguồn đó về UTF-8 sạch** (vd đã sửa dòng ~1803). KHÔNG blanket-decode cả file (sẽ hỏng phần đã đúng).
Phát hiện chuỗi còn hỏng: parse AST, chạy `_fix_mojibake`, flag chuỗi vẫn còn `Ã/á»/â€/Æ°/Ä‘`.

**B. OneDrive mount đọc bản STALE/CẮT CỤT.**
Sandbox/bash có thể thấy `app.py`, `index.html`, `CLAUDE.md` bị **cắt cụt đuôi** hoặc thiếu edit mới — đây là lỗi sync, KHÔNG phải file thật.
- **Nguồn sự thật = Read/Edit tool** (file Windows). Luôn verify bằng Read, đừng tin `wc/tail` của bash.
- **TUYỆT ĐỐI không ghi bản mount (cắt cụt) đè lại** → sẽ truncate file thật.
- Để test trong sandbox: dựng lại bản đầy đủ (mount head + đuôi lấy từ Read), và dùng `PYTHONPYCACHEPREFIX=/tmp/...` để tránh `.pyc` cũ.

**C. CACHE LÀ ROOT CAUSE SỐ 1 của "fix mà không thấy đổi" — phải loại trừ TRƯỚC khi kết luận fix hỏng.**
Nhiều lần "lỗi vẫn còn" sau khi đã sửa đúng trong file thực ra là do **bản cũ đang được serve** (`.pyc` của uvicorn, browser cache `index.html`/JS inline).
- Sau khi sửa: **kill hẳn uvicorn rồi chạy lại** (đừng chỉ dựa `--reload`) + hard-refresh (Ctrl+Shift+R).
- Đã thêm cơ chế xác nhận: `APP_BUILD` trong `app.py` + badge "build …" trên header UI (lấy từ `/health`). **Quy tắc: trước khi nói "fix không ăn", kiểm tra badge build trên UI == `APP_BUILD` ở server.** Nếu lệch → đang chạy bản cũ, KHÔNG phải lỗi code. Mỗi lần sửa → **bump `APP_BUILD`**.
- `/` đã set `Cache-Control: no-store` để tránh browser giữ HTML/JS cũ.

**D. Channel detection.** Trong naming `ZPI_`, field index 1 là **mã số**, KHÔNG phải channel. Channel nằm ở field sau: `GG UA`, `Tiktok One`, `Tiktok FS`, `Tiktok UA`, `Moloco`, `FB UA`. Dùng `_detect_channel_key()`. Đừng quay lại đọc `parts[1]`.

**E. Moloco / creative-level.** Tách entity theo `ad_name` (mỗi creative 1 dòng); channel/OS lấy từ campaign context, format/size lấy từ `ad_name`. Đừng gộp về 1 entity theo campaign_name.

**F. Code trùng trong index.html.** Các helper (`findImg`, `sn`, `dc`, `dbClass`, `chk`) bị khai báo trùng trong script 1 — **bản sau (dòng lớn hơn) thắng**. Khi sửa, sửa bản ACTIVE (cuối cùng). Việc dedupe toàn bộ phải là một pass RIÊNG, verify kỹ — không gộp chung với fix khác.

**G. VERIFY INPUT TRƯỚC KHI ĐỔ LỖI DATA.** Khi một thứ "không fix được", đọc lại flow thật + kiểm tra input thực tế thay vì quy chụp "data sai". Vd thumbnail: entity = `ad_name` nguyên văn (dòng ~679), `_extract_format` chỉ set field `format` riêng, KHÔNG đổi tên; mapping = `norm(ad_name)` vs `norm(tên file ảnh)`. Khi 2 tên không khớp → **vẫn phân tích chỉ số bình thường + báo rõ "không map được ảnh" + gợi ý next-step**, KHÔNG fail im lặng và KHÔNG coi là lỗi data.

**H. UI enhance bị gate theo `isProgrammatic`.** `normalizeProgrammaticUI()` (chạy sau render) chỉ gọi `enhanceSummaryCards` (highlight), `enhanceComparisonPanels` (font), `decodeRenderedText` (mojibake client-side), `hydrateThumbnails` **khi channel là Moloco/Programmatic/Display/DSP/in-app**. Channel SRN thuần (TikTok/Google/FB) sẽ KHÔNG được enhance → nếu sau này highlight/thumbnail "mất" ở SRN thì đây là lý do. Font convention: dashboard base 14px, card/table 12–13px; giữ body L2/detail ≥ 12px.

### Open items đã biết (chưa sửa — đừng tưởng là đã xong)
- `quality_score` có thể vượt thang 0–10 (overflow scoring).
- Chưa có benchmark → `vs_plan_pct` = null → CP Login vs plan chưa được chấm.
- `source` TTO/Freelance rỗng trong path `/api/analyze`.
- **Flexible image↔dimension mapping (deferred):** hiện chỉ match `ad_name` ↔ tên file. Spec mong muốn: auto-scan các dimension (campaign/ad_group/ad_name), match tốt nhất theo token ổn định (scheme+version+size+date, bỏ field phân loại), default `ad_name`; nếu match-rate < 80% → suggestion user chọn field map. Nên đưa logic match xuống backend trả `image_map` + meta. (Tạm hoãn vì user đã đồng bộ tên ảnh 100%.)
- **Segment/context connect mới ở mức nông:** segment/`analysis_question` chỉ vào `audience_context` + vài copy hint (chủ yếu path notification). Core analysis creative (QS/decision/variance/reco) CHƯA personalize theo segment + mục tiêu.

### Changelog 2026-06-16 (đợt fix UI #1)
- ✅ Fix mojibake chuỗi "Main Message" (app.py ~1803) — rewrite UTF-8 sạch.
- ✅ Gỡ Next Step render trùng ở L2 (`renderCreativeComparison`) — chống đè layout.
- ✅ Harden `findImg` (exact stem → longest contained → fragment).
- ✅ Channel detection + Moloco ad-level split (đợt trước).

### Changelog 2026-06-16 (đợt fix UI #2 — build 2026-06-16.5)
- ✅ `emphasizeHtml`: thêm ngắt câu + tô màu xanh(tốt)/đỏ(vấn đề) cho Key Learning/Bottleneck.
- ✅ `enhanceComparisonPanels` + `normalizeDetailFonts`: chuẩn hoá font L2 panel + detail về 12px.
- ✅ Bỏ "Owner:" khỏi Action Plan (recommendations render).
- ✅ Thumbnail: user đã đồng bộ tên ảnh 100% → exact match chạy đúng.
- ✅ **Version stamp**: `APP_BUILD` + badge UI + `/health` build + `Cache-Control: no-store` cho `/` (loại trừ cache khi verify).
- ⏭️ Chưa sửa: dedupe helper trùng, QS overflow, benchmark/vs_plan, TTO/Freelance source, flexible mapping, deep segment wiring.
