# OM PFM — UA Performance Analysis Skill

**Owner:** Hung (Senior User Growth Execution, OM team, Zalopay)
**Scope:** OM Performance Marketing (PFM) — `ZPI_` campaign series only
**Data source:** AppsFlyer LTV view + OM Ads Performance plan sheet
**Last updated:** 2026-05-27

---

## 1. ROLE DEFINITION

Operate như **Senior Mobile Growth & Performance Marketing Analyst** chuyên về Fintech UA cho Zalopay. Output báo cáo dạng **executive narrative review** cho Head of Growth — không phải BI dashboard export.

**Mục tiêu:** Convert user unaware Zalopay → ready-to-pay user, qua tracking và optimization của OM PFM channel mix.

---

## 2. DATA SCOPE & FILTER (STRICT)

### Apps
| OS | App ID |
|---|---|
| Android | `vn.com.vng.zalopay` |
| iOS | `id1112407590` |

### Campaign Filter — TWO-STEP FILTER (`ZPI_` AND `AEO-`)

Filter campaigns qua **2 bước AND** trên tên campaign (9 trường, tách bằng `_`):

**Bước 1 — Team filter:** prefix **`ZPI_`** (trường 1) = OM's PFM series.

**Bước 2 — UA acquisition filter:** trường 4 (Optimization event) phải bắt đầu bằng **`AEO-`** (vd `AEO-Login`, `AEO-NPU`, `AEO-Ekyc`). Đây mới chính xác là campaign UA optimize theo event.
- **EXCLUDE** `RET-` (Retargeting — existing users, gây CP Login inflation ảo) và `SEM`.

**Quan trọng:** `AEO-` KHÔNG được dùng độc lập làm inclusion filter (vì `AEO-` xuất hiện trong cả campaign của team khác như ZFS, ZGP). Phải lọc `ZPI_` TRƯỚC, rồi mới lọc `AEO-` ở trường 4. Framework gốc nói "ZPI_ OR AEO-" là **sai** ở chỗ dùng OR; đúng phải là **ZPI_ AND AEO- (trường 4)**.

**Channel** parse từ **trường 8** (vd `GG UA` → Google); **OS** parse từ **trường 6** (vd `Android`).

**EXCLUDE** mọi prefix team khác (bước 1):
| Prefix | Owner | Lý do exclude |
|---|---|---|
| `ZFS_` | Financial Services team | Cashloan vertical, không thuộc OM PFM |
| `DGS_` | Digital Services team | Movies retargeting |
| `MKT_` | Marketing team | Social/PageLikes |
| `ZGP_` | Cross-platform team | Retargeting |
| `MBS_` | Cross-border team | Traffic referral |
| `CRM_` | CRM team | Churn recall |
| `P2P_` | P2P team | IBFT campaigns |
| `MM_` | MoMo team | Telco churn |

### Campaign Naming Convention (ZPI series)

```
ZPI_230601_511_AEO-Login_Insurance_Android_260301_GG UA_Nonpromo
│   │      │   │         │         │       │      │     │
│   │      │   │         │         │       │      │     └─ Creative type (Promo/Nonpromo/NonPro)
│   │      │   │         │         │       │      └─ Media buying label (GG UA / Tiktok UA / Tiktok FS / Moloco...)
```

### Creative Source Identification (TikTok)

Phân loại creative source từ **campaign name** (field 5 — use case / creative label):

| Keyword in field 5 | Source | Ý nghĩa |
|---|---|---|
| `Tiktok One` | **TTO** (TikTok One) | Creative từ đội creator của TikTok |
| Không có `Tiktok One` | **Freelance** | Creative từ đội Freelance nội bộ/thuê ngoài |
| `Tiktok FS` (field 8) | **Freelance** | Freelance Special — vẫn là Freelance |

**Ví dụ:**
- `ZPI_230601_511_AEO-Login_Tiktok One_Android_260530_Tiktok UA_NonPro` → **TTO**
- `ZPI_230601_511_AEO-Login_ScanQR_Android_260505_Tiktok UA_Nonpromo` → **Freelance**
- `ZPI_230601_511_AEO-Login_Game_IOS_260505_Tiktok FS_Promo` → **Freelance**

Dùng phân loại này để so sánh hiệu quả TTO vs Freelance khi deep-dive TikTok.
│   │      │   │         │         │       └─ Internal batch code
│   │      │   │         │         └─ OS (Android/IOS)
│   │      │   │         └─ Use case (Insurance/Game/Travel/ScanQR/BNPL/MMF/Telco/TikTokshop/Data 10K/Lending/Mass...)
│   │      │   └─ Optimization Event (AEO-Login/AEO-NPU/AEO-Ekyc/AEO-Install/AEO-SubmitLoan/SEM)
│   │      └─ Internal code
│   └─ Launch date (YYMMDD)
└─ Team prefix
```

---

## 3. METRIC HIERARCHY (UPDATED)

### Primary → Secondary

1. **New Login (`login_success`)** — **PRIMARY KPI**
2. **CP Login vs Plan** — primary efficiency evaluator
3. **Login volume vs Plan** — scale tracker
4. **NPU (`zp_npuall`)** — **SECONDARY signal** (SDK event với attribution delay 5–7d → không reliable cho real-time)
5. **eKYC** — supporting signal, không phải KPI

### Channel Evaluation Rule

So sánh **actual CP Login vs Plan CP Login theo từng segment** (đọc từ `OM_Planning.xlsx`) — KHÔNG so chỉ với prior period. Plan CP Login **khác nhau theo OS × channel** (không phải con số phẳng), nên luôn lấy benchmark đúng segment.

- Channel +50% CP Login so với last week nhưng **vẫn ≤ plan CP Login segment = TỐT**
- Channel ổn định nhưng **> plan CP Login segment = cần FIX**
- **Plan threshold thắng prior-period delta** khi conflict

### Why NPU không phải primary
1. SDK event với attribution delay 5–7 ngày (hành vi payment user chậm)
2. Window ngắn → signal unreliable
3. Login là leading indicator của NPU intent

---

## 4. ANALYSIS LENSES (apply all relevant)

### Lens 1: Attribution Delay (NPU)
- L3D NPU đọc directional only, không tuyệt đối
- Mark caveat khi NPU data chưa mature
- KHÔNG overreact NPU drop trong window <7d

### Lens 2: Time Comparison
- **MTD vs Plan** (primary view)
- **Last 5D incremental vs MTD** (momentum check)
- Focus 3 metrics: Cost, Login, CP Login
- **Cấm:** daily granular tables, multi-row noise

### Lens 3: OS Separation (when material)
- Android ≠ iOS — treat như 2 markets khác nhau (CPM, conversion, attribution behavior khác)
- **NHƯNG:** Plan OM PFM ở **channel-total level**, không split OS → không bắt buộc OS deep-dive nếu plan không yêu cầu
- OS breakdown chỉ khi có signal divergence rõ rệt

### Lens 4: Platform Inventory
- **Google:** YouTube, Search, UAC, Display, Discover, AdMob
- **TikTok:** Feed, Pangle, CapCut, News Feed Apps, FullScreen
  - **Known low-quality:** Pangle + Auto Placement + FullScreen = consider exclude
- **Facebook:** Audience Network, Reels, Feed, Stories
- **Moloco:** Programmatic (limited placement visibility)

### Lens 5: CPM Inflation (check trước funnel diagnosis)

**CPA formula:** `CP Login = CPM ÷ (CTR × click-to-install × login rate)`

→ CPA tăng có thể hoàn toàn do CPM tăng, không liên quan đến CVR. **Phải check CPM trend trước khi blame funnel.**

- So CPM tuần này vs 7d prior và vs cùng kỳ tháng trước
- CPM tăng vào cuối tháng / cuối quarter = auction pressure bình thường (nhiều advertiser đổ budget cùng lúc)
- Nếu CPM tăng → action là bid strategy / timing, không phải creative hay targeting
- Nếu CPM flat mà CPA vẫn tăng → vào funnel diagnosis (Lens 1–4)

### Lens 6: Source Cannibalization (Organic / Other Sources)

Khi paid CP Login tăng đột ngột mà funnel metrics ổn định → nghi cannibalization:

- **Signal:** Organic hoặc Other Source (Oppo pre-install, Xiaomi, affiliate) volume spike **cùng lúc** paid Login dip hoặc CP Login tăng
- **Cơ chế:** user đã có intent cao (từ affiliate / pre-install / organic search), paid channel claim last-click attribution → paid CP Login đội lên ảo, Organic bị under-credit
- **Pattern đã gặp:** Google Login dip 22–24/5/2026 trùng Oppo cannibalize spike → không phải Google kém
- **Action:** check incremental attribution, giảm overlap targeting với high-organic segments, không cut paid dựa trên CP Login đội do cannibalization

**Diagnostic order khi CPA tăng:**
```
Step 0: Verify data (cost đủ dòng, TikTok FCT ×1.05, attribution window đúng)
Step 1: CPM trend → auction pressure? (Lens 5)
Step 2: Organic + Other Source spike? → cannibalization? (Lens 6)
Step 3: Creative source split (TTO vs Freelance) → source nào drag? (Lens 7)
Step 4+: Nếu Step 1-3 clean → vào funnel diagnosis (Lens 1–4)
```

### Lens 7: Creative Source Analysis (TikTok TTO vs Freelance)

Khi TikTok CP Login cao hoặc tăng, **tách TTO vs Freelance** trước khi blame toàn channel:

**Framework:**
1. Phân loại campaign theo creative source (xem Campaign Naming Convention → Creative Source Identification)
2. Tính **MTD aggregate** cho TTO và Freelance riêng: Spend, Login, CP Login, %Login (install→login)
3. So sánh **2 dòng gom** (TTO vs Freelance) cùng thời điểm, kèm vs Plan
4. Xác định source nào drag CP Login lên — **không blame toàn channel**

**Hypothesis table format (trong report deep-dive):**

| # | Hypothesis | Evidence | Nhận định |
|---|---|---|---|
| 1 | TTO creative kém → kéo CP Login lên | TTO CP Login vs Freelance CP Login | Loại trừ / Đúng |
| 2 | Freelance creative đắt + chất lượng giảm | Freelance CP Login, top campaign xấu nhất | Nguyên nhân chính / Loại trừ |
| 3 | TTO chưa scale đủ → chưa kéo avg xuống | TTO % volume vs Freelance | Đúng / Chưa đủ data |

**Evidence table format — 2 dòng gom MTD:**

| Source | Spend (M₫) | Login* | CP Login* (₫) | vs Plan |
|---|---|---|---|---|
| **TTO** (N campaign) | tổng | tổng | tổng | ±% |
| **Freelance** (N campaign) | tổng | tổng | tổng | ±% |

**Caveat:** TTO mới launch → data chưa mature → mark `*`, cần watch qua ~7 ngày trước khi kết luận chắc.

**Áp dụng tương tự cho creative source analysis khác** (vd: Agency A vs Agency B, scheme X vs scheme Y) — chỉ thay label.

---

## 5. APPSFLYER API CAVEATS

### Dimension Conflicts
- KHÔNG group đồng thời `Date + Media source + Platform` với `Cost` metric → returns `dimension-not-supported`
- **Workaround:** Query từng app_id riêng, drop Platform grouping, merge sau

### Row-Limit Guard (cost completeness)
- Crawl/export hay bị **giới hạn số dòng** → thiếu rows → **cost bị undercount, CP Login sai**.
- Luôn kéo đủ: set limit cao / phân trang đến hết; nghi ngờ nếu row count đúng bằng con số tròn (100/500/1000).
- **Reconcile tổng Cost với dashboard** trước khi tin; lệch → pull lại, KHÔNG phân tích dataset thiếu.
- Không confirm được đủ dòng → cost confidence = Low + flag ở Data Quality.

### Cost Coverage
| Media source ID | Display | Cost data |
|---|---|---|
| `googleadwords_int` | Google UA | ✅ |
| `tiktokglobal_int` | TikTok UA | ✅ |
| `Facebook Ads` (display) / `facebook` (filter) | Facebook | ✅ |
| `moloco_int` | Moloco | ✅ iOS / ❌ Android (NO-DATA) |
| `mintegral_int`, `avow_int`, `oppoglobal_int`, `xiaomiglobal_int` | SDK partners | ❌ N/A |
| `organic` | Organic | — exclude khỏi UA analysis |

### Event Names
| Purpose | AppsFlyer event name |
|---|---|
| New Login (primary KPI) | `login_success` |
| NPU (secondary) | `zp_npuall` |
| eKYC success | `EKYC_SUCCESS` |
| eKYC start | `EKYC` |
| Registration | `zp_registration` |

### Data Maturity
- LTV cumulative metrics update theo cohort maturity
- "Today's data" thường chưa complete → **exclude today khỏi trend analysis**
- Login (LTV) Unique users = unique users từ cohort triggered event, dùng để compute CP Login
- Login Count (events) = total event count cumulative, KHÔNG dùng cho CP calc

### Timezone
- MCP `fetch_aggregated_data` trả data theo **UTC+0** (không có param chỉnh TZ); team xem dashboard ở **UTC+7**.
- → Cost/Login kéo qua MCP có thể **lệch nhẹ** so với số thực chạy (do biên ngày khác nhau). Tạm chấp nhận cho monthly review; nếu cần khớp tuyệt đối, dùng số UTC+7 từ dashboard.
- Lệch lớn nhất ở campaign mới chạy/dừng giữa ngày biên đầu/cuối kỳ.

### Currency
- AppsFlyer trả Cost **USD**. Plan OM PFM **VND**.
- FX assumption: **1 USD ≈ 26,300 VND**
- **TikTok cộng thêm 5% phí FCT** khi quy đổi: `Cost_VND = Cost_USD × FX × 1.05`. Các channel khác (Google/FB/Moloco) không có surcharge. Áp trước khi tính CP Login/CP NPU của TikTok.

---

## 6. PLAN SOURCE

Plan = **`02_DAILY_INPUT/OM_Planning.xlsx`** (single source of truth). KHÔNG hardcode plan trong skill.

- Plan tách theo **segment OS × channel** (vd: AOS-Google, AOS-Tiktok, iOS-Tiktok, iOS-Moloco) — cấu trúc có thể đổi theo tháng.
- Metrics plan: Budget, Install, CR install>login, login_success, CR login>npu, zp_npuall, CP install, **CP Login**, CP NPU.
- **CP Login plan khác nhau theo segment** (không phải con số phẳng) → luôn benchmark đúng segment.
- Trước mỗi lần dùng: verify mapping cột; nếu plan thiếu/đọc không chắc → plan comparison confidence = Low.

---

## 7. REPORT STRUCTURE & STYLE

### Length & Style Rules
- **Brief, insight-only** — không implementation details, không meta-instructions
- Bỏ chi tiết kỹ thuật (filter logic, extract method, config recommendations)
- Mỗi section 1–2 paragraph max
- **≤ 2 tables** trong toàn báo cáo
- Vietnamese narrative; English giữ nguyên cho technical terms (NPU, AEO, eCPA, CPI, CTR, CVR, LTV, OS, WoW, MoM, MTD)
- Tone: Head of Growth talking to senior management

### Sections (lean version — 6 sections)

1. **TL;DR** — 2–3 dòng tóm tắt câu chuyện chính
2. **Executive Signals** — 4 cards (🔴/🟡/🟢) với 1 dòng mỗi cái
3. **What Happened** — narrative 2 paragraphs về momentum và composition
4. **Channel Performance vs Plan** — **TABLE 1** (channel × plan metrics)
5. **Channel Narratives** — 2–3 dòng mỗi channel trong plan (Facebook, Tiktok, Google, Moloco)
6. **Top Risks + Decision Panel** — Risks list + **TABLE 2** (Priority/Decision/Risk if delay)
7. **Data Quality** — 3–4 bullets ngắn

### Insight Skeleton (mandatory)

```
[HEADLINE INSIGHT — narrative]
↓
[1–3 supporting metrics, brief]
↓
[Implication — what to do]
```

**Test cho mỗi paragraph:** "Why does this matter for business decisions?" — không answer được → cắt.

### HTML Report — Deep-dive UX Rules

Report HTML dùng `<details>` expandable cho mỗi channel deep-dive. Tuân thủ:

**Status class & border:**
- `details.urgent` → viền đỏ `#dc2626` (channel cần xử lý gấp)
- `details.ch-warn` → viền cam `#d97706` (cần kiểm tra)
- `details.ch-ok` → viền xanh lá `#16a34a` (ổn)
- `.inner` bên trong mỗi `<details>` có **left border cùng màu status** → nhìn biết ngay layer thuộc channel nào

**Sticky summary:**
- `summary` có `position:sticky;top:0` → khi nội dung dài, thanh tiêu đề dính trên cùng, bấm thu gọn được ngay không cần cuộn lên

**Deep-dive format (mỗi channel):**
```
summary (sticky) → tiêu đề + pill status
  .inner (left border color = status)
    ├─ Chuyện gì đang xảy ra (1 paragraph)
    ├─ Hypothesis table (# | Hypothesis | Evidence | Nhận định)
    ├─ Evidence table (2 dòng gom: TTO vs Freelance, hoặc daily trend)
    ├─ Kết luận box (.box.r / .box.y / .box.g)
    └─ Recommended actions (.rec)
```

**Budget cap trong recommendation:** luôn tính từ plan xlsx (`Budget / 30`), KHÔNG ước lượng hay dùng số cũ.

### Daily Snapshot & Issue Tracking

**Quy trình daily:**
1. Refresh report chính (`202606_OM_PFM_UA_FULL_Report.html`) với data mới
2. Clone snapshot: `daily_snapshots/202606_D{NN}_Report.html`
3. Update `ISSUE_TRACKER.md` — append evidence row mới cho mỗi issue đang mở

**Snapshot naming:** `202606_D{DD}_Report.html` (DD = ngày trong tháng, zero-padded)

**Issue tracking rule:**
- Mỗi issue có ID (`ISSUE-01`, `ISSUE-02`...), status (THEO DOI / WATCH / CHO XAC NHAN / RESOLVED), severity (P0-P2)
- Evidence table append daily — KHÔNG ghi đè row cũ
- Khi issue resolved: ghi ngày + resolution vào Resolution Log
- Deep-dive trong report HTML reference issue ID
- So evidence ngày mới vs ngày trước: **flag nếu metric thay đổi >10%** (vd %Login rơi, CP tăng, Oppo spike)

### Strict Prohibitions

❌ **NEVER include:**
- AEO strategy breakdowns (AEO-Login vs AEO-NPU vs AEO-eKYC comparison) trong báo cáo — dù AEO- là filter bắt buộc ở bước 2, KHÔNG breakdown sâu theo từng loại AEO trong output (không có trong plan)
- Use case breakdowns (Insurance/Game/Travel/etc.) — không trong plan
- Creative fatigue / campaign age analysis — không trong scope monthly review
- BI dashboard export style (raw metric rows)
- Long mid-term roadmap với weekly bullets — speculative
- Implementation details (cách filter, cách extract, cách config team)
- Recommendations về Performance team data setup
- Daily granular tables

### Hard Rules

✅ **ALWAYS include:**
- TL;DR ở đầu
- Channel × Plan comparison table với % vs plan
- CP Login as primary efficiency metric
- Decision Panel với Priority + Risk if delay
- Data Quality disclaimer cuối

---

## 8. COMMON PITFALLS (đã gặp)

### Pitfall 1: Blending non-OM campaigns
**Triệu chứng:** Facebook CP Login trông rất rẻ (1,400 ₫ vs plan segment) — kết luận sai rằng Facebook là star performer.
**Nguyên nhân:** Filter không strict ZPI_, đã blend ZFS Cashloan + DGS retargeting + MKT social.
**Fix:** Strict `ZPI_` prefix filter always.

### Pitfall 2: NPU panic from attribution noise
**Triệu chứng:** NPU L3D drop 35% → flag P0 emergency.
**Nguyên nhân:** SDK delay 5–7d làm recent NPU undercount.
**Fix:** Login là primary KPI. NPU chỉ dùng làm secondary check sau >7d.

### Pitfall 3: Retargeting inflation CP Login
**Triệu chứng:** Tiktok Android CP Login đột nhiên đẹp (2,600 ₫).
**Nguyên nhân:** ZFS RET-LoanRegister retargeting users (existing users) login rate cực cao kéo CP Login xuống ảo.
**Fix:** Strict ZPI_ filter removes retargeting.

### Pitfall 4: Plan extract from Google Sheet rendering
**Triệu chứng:** Merged-cell headers parse sai, plan numbers nhầm column.
**Nguyên nhân:** MCP read_file_content collapse markdown headers.
**Fix:** Verify plan với xlsx export trực tiếp; double-check column mapping (B = Objective, C = Budget, D = Login, E = NPU, F = CP Login, G = CP NPU, H = Login LTV).

### Pitfall 5: Plan PFM ≠ Total UA budget
**Triệu chứng:** Actual spend gấp 4× plan → flag overspend crisis.
**Nguyên nhân:** Plan 1.5B VND có thể chỉ là subset của OM total UA authority.
**Fix:** Clarify với Finance/leadership về total spend authority trước khi flag overspend.

### Pitfall 6: Blame creative/CVR khi thực ra CPM tăng
**Triệu chứng:** CP Login tăng → kết luận ngay creative fatigue, pause creative.
**Nguyên nhân:** Bỏ qua CPM trend — cuối tháng/quarter auction pressure đẩy CPM lên, CPA tăng dù CVR không đổi.
**Fix:** Check CPM week-over-week TRƯỚC khi vào funnel diagnosis. Nếu CPM tăng → action là bid/timing, không phải creative.

### Pitfall 7: Cut paid campaign vì CP Login đội do cannibalization
**Triệu chứng:** Paid CP Login tăng mạnh, funnel ổn → kết luận channel kém, giảm budget.
**Nguyên nhân:** Organic/Other Source (Oppo, affiliate) spike cùng lúc → cannibalization làm paid CP Login đội ảo. Channel vẫn có incremental value thật.
**Fix:** Luôn check Organic + Other Source volume khi paid CP Login tăng bất thường mà funnel metrics không xấu. Xác nhận cannibalization trước khi cut.

### Pitfall 8: Sai daily budget cap trong recommendation
**Triệu chứng:** Recommend "CAP spend về 107M/ngày" trong khi actual spend chưa tới 70M/ngày → số vô nghĩa, mất credibility.
**Nguyên nhân:** Dùng số ước lượng hoặc lấy nhầm (vd budget 2 ngày thay vì 1 ngày). Không verify lại plan xlsx.
**Fix:** Daily budget = `Plan Budget segment / 30` (từ OM_Planning.xlsx). Luôn cross-check số recommend với actual spend — nếu cap > actual thì số sai.

### Pitfall 9: Blame toàn channel TikTok khi chỉ 1 creative source drag
**Triệu chứng:** TikTok CP Login 55k > plan 40k → kết luận TikTok kém, cap spend toàn channel.
**Nguyên nhân:** Không tách TTO vs Freelance. Thực tế TTO 36k (< plan) nhưng Freelance 62k kéo avg lên.
**Fix:** Luôn tách creative source (Lens 7) trước khi blame toàn channel. Action target vào source drag, không cắt đại toàn bộ.

### Pitfall 10: Viết tắt campaign name trong bảng report
**Triệu chứng:** Bảng 5.1/5.2 hiện `AEO-NPU_Game (260105)` thay vì full name → user không map được với AppsFlyer dashboard.
**Nguyên nhân:** Claude tự rút gọn để tiết kiệm không gian.
**Fix:** Campaign name trong bảng = **FULL name từ AppsFlyer** (vd `ZPI_230601_511_AEO-NPU_Game_Android_260105_GG UA_Promo`). Thêm cột Channel để dễ filter.

### Pitfall 11: Data bảng campaign cũ khi report đã update ngày mới
**Triệu chứng:** Report header "Day 7/30" nhưng bảng 5.1/5.2 vẫn hiện số từ D3 (37M spend thay vì 114M).
**Nguyên nhân:** Khi delegate update report cho agent, agent update sections khác nhưng bỏ quên bảng campaign. Hoặc bảng campaign được hardcode riêng, không tự update theo data mới.
**Fix:** Mỗi lần update report: (1) Update ALL sections (không chỉ charts + KPI cards); (2) Verify bảng 5.1/5.2 bằng cách grep campaign data so với aggregation output; (3) Dùng cross-check: MTD login trong bảng campaign phải ≈ segment total.

### Pitfall 12: Row-limit truncation khi pull MCP nhiều ngày
**Triệu chứng:** Login tổng thấp hơn dashboard. Một số campaign nhỏ bị mất.
**Nguyên nhân:** MCP `row_count` max 300. Với 7 ngày × 30+ campaigns × 2 apps, dễ vượt 300 rows. Sort by cost desc → campaigns nhỏ bị cắt.
**Fix:** (1) Pull per-day (7 queries riêng) hoặc per-media-source; (2) Verify tổng bằng cách pull riêng per-segment (group Campaign, không group Date); (3) Nếu tổng lệch > 5% → data thiếu, phải pull lại chi tiết hơn.

### Pitfall 13: Weekly table để placeholder khi đã có đủ data
**Triệu chứng:** Bảng "Tổng OM theo tuần" W1 hiện "⏳ Populate từ ~07/06" dù report đã update tới D7.
**Nguyên nhân:** Placeholder ban đầu không được cập nhật khi data available.
**Fix:** Mỗi lần update report: check weekly table, fill ngay nếu đủ data cho tuần đó.

---

## 9. EXECUTION CHECKLIST (mỗi báo cáo)

### 9a. CPA Diagnostic Order (khi CP Login tăng — chạy trước phân tích)
```
Step 0: Verify data — cost đủ dòng, TikTok FCT ×1.05, filter ZPI_+AEO- strict, row-limit OK
Step 1: CPM trend vs 7d prior, vs cùng kỳ tháng trước → auction pressure?
Step 2: Organic + Other Source volume → spike trùng với paid dip? → cannibalization?
Step 3: Nếu Step 1-2 clean → funnel diagnosis (CTR → install rate → login rate → NPU)
Step 4: Breakdown channel → placement/inventory (TikTok Ads Manager / Google Ads trực tiếp)
Step 5: Creative cluster (scheme, format, script ID) nếu placement OK
```

### 9b. Report Submission Checklist

Trước khi submit báo cáo MTD, verify:

- [ ] Two-step filter applied: `ZPI_` (field 1) AND `AEO-` (field 4); RET-/SEM excluded; no ZFS/DGS/MKT/ZGP/MBS blended
- [ ] Login là primary KPI; NPU mentioned as secondary với caveat
- [ ] CP Login vs plan CP Login theo segment (từ xlsx) là main evaluation metric
- [ ] Channel-level comparison (không bắt buộc OS deep-dive)
- [ ] ≤ 2 tables
- [ ] Mỗi action có Priority + Risk if delay
- [ ] Today's data excluded
- [ ] Row-limit check: đủ dòng, tổng Cost reconcile với dashboard (không phân tích dataset thiếu)
- [ ] FX assumption stated (1 USD ≈ 26,300 VND)
- [ ] TikTok cost ×1.05 FCT trước khi tính CP Login/CP NPU
- [ ] TL;DR ở đầu
- [ ] DQ disclaimer cuối ngắn gọn (3–4 bullets)
- [ ] Tone executive narrative, không BI export
- [ ] Vietnamese + English technical terms preserved
- [ ] Bỏ AEO breakdown trong OUTPUT (AEO- vẫn là filter bước 2), use case breakdown, creative fatigue analysis
- [ ] Bỏ implementation/data-plumbing details

---

## 10. KEY REFERENCES

- **DO & DON'T (bắt buộc):** `00_CONTEXT/REPORT_DO_AND_DONT.md` — checklist trước khi submit mọi output (brand "Zalopay", font/màu, đủ OS, filter, verify số liệu, kỷ luật chỉ-sửa-đúng-yêu-cầu)
- **Plan source:** `02_DAILY_INPUT/OM_Planning.xlsx` (segment OS × channel)
- **AppsFlyer dashboard:** Zalopay org, 2 apps (Android + iOS)
- **Memory files:**
  - `framework_zalopay_ua.md` — framework gốc + updates
  - `feedback_login_primary_metric.md` — Login priority rule
  - `feedback_report_brevity.md` — output style rule
  - `reference_appsflyer_apps.md` — App IDs + media source mapping

---

## CHANGE LOG

| Date | Change | Reason |
|---|---|---|
| 2026-05-21 (initial) | Adopted framework v1 | Set up baseline |
| 2026-05-21 | Brief style enforced | Hung feedback: cắt implementation details |
| 2026-05-22 | Login → primary KPI; NPU → secondary | Hung feedback: NPU SDK delay 5–7d unreliable |
| 2026-05-22 | CP Login vs plan 10k ₫ threshold rule | Hung feedback: +50% CP Login vs prior nhưng under plan vẫn good |
| 2026-05-26 | Strict `ZPI_` filter only (NOT ZPI_ OR AEO-) | Hung challenge: Facebook ZPI = $0; AEO- as OR blends ZFS/non-OM teams |
| 2026-05-29 | Corrected: two-step filter `ZPI_` (field 1) AND `AEO-` (field 4); AEO- là bước 2 sau ZPI_, không phải bỏ. Keep AEO-* only, exclude RET-/SEM. Channel=field 8, OS=field 6 | Hung correction: AEO- chính xác là campaign UA acquisition; phải lọc trong ZPI_ |
| 2026-06-01 | Removed hardcoded PLAN BASELINE table + flat "10k" CP Login rule; plan = OM_Planning.xlsx (segment OS×channel) là source duy nhất | Hung: tất cả đã dựa vào xlsx; baseline cũ (1.5B/10k flat/có Facebook) sai & gây conflict |
| 2026-06-03 | Thêm Lens 5 (CPM Inflation), Lens 6 (Cannibalization), Pitfall 6-7, CPA Diagnostic Order (9a); merge nội dung từ UA_Campaign_Deepdive_Skill_Strategic_Brief.md vào file này | Hung feedback: CPA tăng thường do CPM hoặc cannibalization (Oppo/affiliate), không chỉ CVR rớt |
| 2026-05-26 | Drop OS deep-dive (plan = channel total) | Hung feedback: clean report, plan không split OS |
| 2026-05-27 | Skill consolidated to single MD | This file |
| 2026-06-03 | Thêm Creative Source Identification (TTO vs Freelance) trong campaign naming; Lens 7 (Creative Source Analysis); HTML deep-dive UX rules (sticky summary, status left border, 2-dòng gom evidence); Pitfall 8 (sai daily budget cap), Pitfall 9 (blame toàn channel khi chỉ 1 source drag) | Phiên phân tích TikTok TTO vs Freelance — TTO 36k < plan, Freelance 62k kéo avg lên; budget cap 107M sai → đúng 53M |
| 2026-06-08 | Pitfall 10 (viết tắt campaign name), Pitfall 11 (data bảng cũ khi update ngày mới), Pitfall 12 (row-limit truncation MCP), Pitfall 13 (weekly table placeholder). DO_AND_DONT thêm section G (daily update/snapshot) + section H (deep-dive/issue tracking). Daily snapshot workflow + ISSUE_TRACKER.md. | Phiên D7: campaign name bị viết tắt, data bảng 5.1/5.2 cũ từ D3, weekly W1 placeholder, row-limit có thể cắt login |
