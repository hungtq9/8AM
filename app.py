"""
Creative Performance Insight Agent — v4
Claw-a-thon 2026 — Data Analysis Track
"""

import os, io, json, re, traceback, uuid, httpx, pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from analysis.parser import parse_campaign
from analysis.metrics import aggregate_metrics
from analysis.report import build_llm_prompt, format_markdown_report
from analysis.skills.action import get_action_skill

APP_BUILD = "2026-06-16.27"  # bump mỗi lần sửa để xác nhận đang chạy bản mới (xem /health hoặc badge UI)
app = FastAPI(title="Creative Performance Insight Agent", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def json_utf8_charset_middleware(request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json") and "charset" not in content_type.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response


@app.exception_handler(Exception)
async def json_exception_handler(request, exc):
    trace_id = str(uuid.uuid4())
    print(f"[trace_id={trace_id}] Unhandled error: {exc}")
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"error": str(exc), "trace_id": trace_id})

LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen-3-27B")
FX_RATE = 26_300

app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.mount("/demo", StaticFiles(directory=Path(__file__).parent / "demo"), name="demo")


def _vn(text: str) -> str:
    return text.encode("ascii").decode("unicode_escape")


_CH_NAMES = {"tiktok": "TikTok", "google": "Google", "facebook": "Facebook", "moloco": "Moloco"}


def _detect_channel_key(text: str) -> str:
    """Return canonical channel key (tiktok/google/facebook/moloco) by scanning the
    full entity/campaign name. Handles the ZPI_ convention where the channel appears
    as a later field ("GG UA", "Tiktok One", "Tiktok FS", "Tiktok UA", "Moloco", "FB UA"),
    NOT as field index 1 (which is a numeric campaign code here)."""
    # Normalize: underscores → spaces, pad so " TOKEN " word-boundary checks work.
    s = " " + str(text).upper().replace("_", " ") + " "
    # Field-2 channel code (other ZPI conventions): ZPI_TT_..., ZPI_GG_...
    parts = str(text).split("_")
    if len(parts) > 1:
        code = parts[1].strip().upper()
        code_map = {"TT": "tiktok", "GG": "google", "GOO": "google", "GOOGLE": "google",
                    "FB": "facebook", "META": "facebook", "FACEBOOK": "facebook",
                    "MLO": "moloco", "MOLOCO": "moloco"}
        if code in code_map:
            return code_map[code]
    # Keyword scan (order matters — check specific channels before generic).
    if "MOLOCO" in s or " MLO " in s:
        return "moloco"
    if "FACEBOOK" in s or " META " in s or " FB " in s:
        return "facebook"
    if " GG " in s or "GOOGLE" in s or " UAC " in s:
        return "google"
    # "TIKTOK" standalone = channel; "TIKTOKSHOP" = use case, not channel.
    if ("TIKTOK" in s and "TIKTOKSHOP" not in s and "TIKTOK SHOP" not in s) or " TT " in s:
        return "tiktok"
    return ""


def _guess_channel(entity: str) -> str:
    """Detect channel from entity/campaign name. Only called when user did NOT select a channel."""
    return _CH_NAMES.get(_detect_channel_key(entity), "Unknown")


def _resolve_channel(entity: str, user_channels: list) -> str:
    """Determine channel for an entity.
    - No selection: detect from name.
    - Single-channel selection: force that channel (trust user).
    - Multi-channel selection: detect from name; match to a selected channel if possible,
      otherwise trust the name (data is authoritative), else fall back to first selected."""
    if not user_channels:
        return _guess_channel(entity)
    if len(user_channels) == 1:
        return user_channels[0]   # Trust user — don't override with entity name

    key = _detect_channel_key(entity)
    if key:
        for uc in user_channels:
            if key in uc.lower():
                return uc
        return _CH_NAMES.get(key, user_channels[0])
    return user_channels[0]


def _extract_format(entity: str) -> str:
    """Extract creative format (Image/Video/GIF) from entity/ad name.
    For Moloco naming: Scheme_USP_Team_Format_ContentID_..."""
    e_lower = entity.lower()
    # File extension is most reliable
    if any(e_lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
        return "Image"
    if any(e_lower.endswith(ext) for ext in (".mp4", ".mov", ".avi", ".m4v")):
        return "Video"
    if e_lower.endswith(".gif"):
        return "GIF"
    e_up = entity.upper()
    # Explicit keywords in name
    parts = entity.split("_")
    for p in parts:
        pu = p.upper().rstrip("0123456789")
        if pu in ("IMAGE", "IMG", "STATIC"):
            return "Image"
        if pu in ("VIDEO", "VID"):
            return "Video"
        if pu == "GIF":
            return "GIF"
    return "Unknown"


def _extract_size(entity: str) -> str:
    """Extract banner size (e.g. 320x50) from entity/ad name."""
    import re as _re
    match = _re.search(r'(\d{2,4})[xX×](\d{2,4})', entity)
    return match.group(0) if match else ""


def _guess_os(entity: str) -> str:
    """Detect OS from entity/campaign name string."""
    e = entity.upper()
    if "IOS" in e or "IPHONE" in e:
        return "iOS"
    if "AND" in e or "ANDROID" in e:
        return "Android"
    return ""


def _is_srn_channel(channel: str) -> bool:
    """Return True if channel is a Social/Search/SRN (not Moloco/DSP/notification)."""
    c = (channel or "").lower()
    return any(k in c for k in ("tiktok", "google", "facebook", "meta", "srn", "social"))


def _fix_mojibake(obj):
    """Fix mojibake: UTF-8 bytes stored as CP1252 codepoints in the Python source.
    Strategy: replace CP1252-specific chars (€→0x80, '→0x91, "→0x94, —→0x97, etc.)
    with their raw byte equivalents, then encode as Latin-1 → decode as UTF-8."""
    _CP1252 = {
        '€':'\x80','‚':'\x82','ƒ':'\x83','„':'\x84',
        '…':'\x85','†':'\x86','‡':'\x87','ˆ':'\x88',
        '‰':'\x89','Š':'\x8a','‹':'\x8b','Œ':'\x8c',
        'Ž':'\x8e','‘':'\x91','’':'\x92','“':'\x93',
        '”':'\x94','•':'\x95','–':'\x96','—':'\x97',
        '˜':'\x98','™':'\x99','š':'\x9a','›':'\x9b',
        'œ':'\x9c','ž':'\x9e','Ÿ':'\x9f',
    }
    if isinstance(obj, str):
        try:
            s = obj
            for uc, bc in _CP1252.items():
                if uc in s:
                    s = s.replace(uc, bc)
            return s.encode('latin-1').decode('utf-8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            return obj
    elif isinstance(obj, dict):
        return {k: _fix_mojibake(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_fix_mojibake(i) for i in obj]
    return obj


# ── Channel Skill Analysis ─────────────────────────────────

def _channel_skill_analysis(entity_result: dict, all_results: list) -> dict:
    """Delegate to analysis/skills router — maps (channel, format) → correct skill module.
    Skill modules live in analysis/skills/: srn_tiktok, srn_google, srn_facebook,
    programmatic (format-aware), notification, general."""
    try:
        from analysis.skills import get_channel_skill
        return get_channel_skill(entity_result, all_results)
    except Exception:
        # Fallback: inline general skill
        return _skill_general(entity_result, all_results)


def _skill_moloco(r: dict, all_results: list) -> dict:
    """Format-aware Moloco/In-app Display skill analysis.
    Image banners vs Video banners have completely different dimension priorities."""
    ctr, cvr = r.get("ctr_pct", 0), r.get("cvr_pct", 0)
    fmt = (r.get("format") or _extract_format(r.get("entity", ""))).lower()
    size = r.get("size") or _extract_size(r.get("entity", ""))
    is_image = "image" in fmt or (fmt == "unknown" and not any(v in fmt for v in ("video","mp4","mov")))

    if is_image:
        # ── IMAGE BANNER analysis ────────────────────────────────────────────
        size_note = f"Detected size: {size}." if size else "Size not detected — check naming."
        size_tier = "small" if any(s in size for s in ("320x50","728x90")) else                     "medium" if "300x250" in size or "320x100" in size else                     "large" if any(s in size for s in ("320x480","300x600","480x320")) else "unknown"
        findings = [
            {
                "dim": "Size & Placement Tier",
                "icon": "📐",
                "finding": f"CTR {ctr:.2f}%. {size_note} Size tier: {size_tier}. "
                           f"{'Banner nhỏ (<50px height): text tối thiểu, offer phải dominance toàn bộ.' if size_tier=='small' else 'MREC/Medium: cân bằng image + text, storytelling ngắn.' if size_tier=='medium' else 'Interstitial/Large: có không gian, nhưng user muốn đóng nhanh — offer phải rõ trong 1 giây đầu.' if size_tier=='large' else 'Kiểm tra size trong naming để phân tích chính xác hơn.'}",
                "signal": "warn" if ctr < 0.5 else "ok",
                "action": f"Breakdown CTR theo size: 320×50 (banner) vs 300×250 (MREC) vs 320×480 (interstitial). "
                          f"{'Size 320×50 quá nhỏ — chỉ nên có 1 element: offer number + brand. Không đặt text phụ.' if size_tier=='small' else 'MREC 300×250: test image có face/context vs pure offer graphic.' if size_tier=='medium' else 'Interstitial: first 0.5s phải capture — offer dominant, exit button không che offer.'}",
            },
            {
                "dim": "Offer Visibility",
                "icon": "💰",
                "finding": f"CVR {cvr:.1f}%. Image banner: offer phải readable ở thumb-size (user xem banner nhỏ, không zoom).",
                "signal": "ok" if cvr > 3 else "warn",
                "action": "Checklist: (1) Số tiền offer ≥14sp font size; (2) Màu text contrast ratio ≥4.5:1 với background; "
                          "(3) Offer không bị overlap bởi brand logo hoặc decorative element; "
                          "(4) Test: shrink banner xuống 50% — offer còn readable không?",
            },
            {
                "dim": "Visual Hierarchy",
                "icon": "🎨",
                "finding": "Image banner phải truyền message trong <1 giây. Eye path: Offer → CTA → Brand.",
                "signal": "warn" if ctr < 0.5 else "ok",
                "action": "Nguyên tắc: (1) Offer = largest element; (2) CTA button = second most prominent; "
                          "(3) Brand logo = smallest. Loại bỏ decorative elements không contribute vào action. "
                          "Background không được cạnh tranh với offer text.",
            },
            {
                "dim": "CTA Button",
                "icon": "👆",
                "finding": f"CTA trên image banner phải là button riêng biệt, không phải text thường. "
                           f"{'CTR thấp có thể do CTA không clickable-looking.' if ctr < 0.5 else 'CTA đang tạo được click.'}",
                "signal": "ok" if ctr > 0.3 else "warn",
                "action": "CTA phải: (1) Có màu nền khác biệt (contrast button); (2) Text cụ thể: 'Nhận 15K' không phải 'Tải ngay'; "
                          "(3) Đủ to để tap trên mobile (min 44px height); (4) Positioned gần offer, không tách biệt.",
            },
        ]
        gap_note = ""
        if ctr < 0.5 and cvr > 5:
            gap_note = f"Low CTR + High CVR trên image banner → offer đang qualify đúng intent nhưng banner không visible đủ. Check size placement: {size or 'unknown size'} có đang bị đặt vào low-visibility position không?"
        elif ctr > 1 and cvr < 2:
            gap_note = "High CTR + Low CVR → image hấp dẫn nhưng post-click không match offer. Kiểm tra deeplink và onboarding."
        return {
            "channel": "In-app Display / Moloco",
            "format": "Image Banner",
            "size": size,
            "dimensions": ["Size & Placement", "Offer Visibility", "Visual Hierarchy", "CTA Button"],
            "analysis_order": "Size/Placement → Offer Visibility → Visual Hierarchy → CTA Button",
            "key_insight": f"Image banner {size or ''}: user xem <1 giây — offer phải chiếm dominant space, readable ngay, CTA phải là button rõ ràng. Ưu tiên thứ tự: size/placement → offer visibility → contrast/readability.",
            "gap_note": gap_note,
            "specific_analysis": findings,
        }
    else:
        # ── VIDEO BANNER analysis ────────────────────────────────────────────
        findings = [
            {
                "dim": "First Frame / Static Fallback",
                "icon": "🖼️",
                "finding": f"CTR {ctr:.2f}%. Video in-app: nhiều inventory không autoplay — first frame phải standalone as image.",
                "signal": "warn" if ctr < 0.5 else "ok",
                "action": "First frame phải đủ mạnh như một image banner độc lập. Offer phải visible ngay frame 0 kể cả khi video không play.",
            },
            {
                "dim": "Video Length & Pacing",
                "icon": "⏱️",
                "finding": "In-app video: user không chủ động tìm content — tolerance thấp hơn social feed.",
                "signal": "warn",
                "action": "Optimal: 6-15 giây. Offer phải xuất hiện trong 2 giây đầu. Kết thúc bằng CTA rõ ràng + offer recap.",
            },
            {
                "dim": "Offer & CTA Overlay",
                "icon": "💰",
                "finding": f"CVR {cvr:.1f}%. Video cần text overlay liên tục cho offer — user có thể watch without audio.",
                "signal": "ok" if cvr > 3 else "warn",
                "action": "Persistent offer overlay suốt video. CTA button xuất hiện từ giây thứ 3 trở đi và giữ đến hết.",
            },
            {
                "dim": "Size Fit",
                "icon": "📐",
                "finding": f"Size: {size or 'unknown'}. Video cần aspect ratio phù hợp với banner size.",
                "signal": "warn" if not size else "ok",
                "action": f"{'320x480: vertical format — dùng 9:16 creative, không letterbox.' if '320x480' in (size or '') else '300x250: near-square — 1:1 creative tốt hơn 16:9 letterboxed.' if '300x250' in (size or '') else 'Verify video aspect ratio match với banner size để tránh letterbox/crop.'}",
            },
        ]
        gap_note = ""
        if ctr < 0.5 and cvr > 3:
            gap_note = "Low CTR + High CVR trên video banner → video content qualify tốt nhưng first frame chưa đủ mạnh để trigger click. Fix first frame trước."
        return {
            "channel": "In-app Display / Moloco",
            "format": "Video Banner",
            "size": size,
            "dimensions": ["First Frame", "Video Length", "Offer Overlay", "Size Fit"],
            "analysis_order": "First Frame → Size Fit → Offer Overlay → CTA",
            "key_insight": f"Video banner {size or ''}: first frame phải standalone as image, offer phải overlay persistent, audio-off safe.",
            "gap_note": gap_note,
            "specific_analysis": findings,
        }


def _skill_tiktok(r: dict, all_results: list) -> dict:
    """Format-aware TikTok skill analysis. TikTok is primarily video, but static/image ads exist."""
    ctr, cvr = r.get("ctr_pct", 0), r.get("cvr_pct", 0)
    fmt = (r.get("format") or _extract_format(r.get("entity", ""))).lower()
    is_image = "image" in fmt

    if is_image:
        # TikTok static/TopView image ads
        findings = [
            {
                "dim": "Visual Hook (Static)",
                "icon": "🎨",
                "finding": f"CTR {ctr:.2f}%. TikTok image ad phải cạnh tranh với video feed — visual phải cực kỳ bold để thumb-stop.",
                "signal": "warn" if ctr < 1 else "ok",
                "action": "Image phải: high contrast, bold offer text, human element nếu có thể. Tránh muted colors và complex composition.",
            },
            {
                "dim": "Offer Prominence",
                "icon": "💰",
                "finding": f"CVR {cvr:.1f}%. TikTok user expect value upfront — offer phải chiếm ≥40% visual space.",
                "signal": "ok" if cvr > 5 else "warn",
                "action": "Số tiền/offer phải là focal point. Dùng màu contrast mạnh (đỏ/vàng trên nền tối). Test: remove everything except offer + CTA — still makes sense?",
            },
            {
                "dim": "CTA & Text Overlay",
                "icon": "✍️",
                "finding": "Static TikTok ad: CTA phải cực kỳ rõ ràng vì không có movement để guide attention.",
                "signal": "ok" if ctr > 1 else "warn",
                "action": "CTA: button shape + action text cụ thể. 'Nhận 15K ngay' tốt hơn 'Tìm hiểu thêm'. Position: bottom center hoặc right.",
            },
            {
                "dim": "Brand & Offer Clarity",
                "icon": "🏷️",
                "finding": "User TikTok scroll nhanh — brand + offer phải readable trong 0.5 giây.",
                "signal": "warn",
                "action": "Test: nhìn image 0.5 giây rồi nhắm mắt. Bạn nhớ gì? Nếu không nhớ offer + brand → redesign.",
            },
        ]
        gap_note = "Low CTR + High CVR trên TikTok static → image chưa đủ bold để stop scroll, nhưng message tốt. Test bolder visual với cùng offer." if ctr < 1 and cvr > 5 else ""
        return {
            "channel": "TikTok",
            "format": "Static Image",
            "dimensions": ["Visual Hook", "Offer Prominence", "CTA", "Brand Clarity"],
            "analysis_order": "Visual Hook → Offer Prominence → CTA → Brand Clarity",
            "key_insight": "TikTok image ad phải bold hơn bình thường vì cạnh tranh với video content. Offer dominant, visual contrast cao.",
            "gap_note": gap_note,
            "specific_analysis": findings,
        }

    # ── VIDEO (default for TikTok) ───────────────────────────────────────────
    findings = [
        {
            "dim": "Hook / First 3s",
            "icon": "🎣",
            "finding": f"CTR {ctr:.2f}% — {'hook chưa đủ mạnh để thumb-stop trong scroll feed' if ctr < 1.5 else 'hook đang tạo được click volume tốt'}.",
            "signal": "warn" if ctr < 1.5 else "ok",
            "action": "Test 3 hook approach: (1) Offer-dominant — số tiền lớn, contrast cao ngay frame 0; (2) Human-context — người dùng thật đang checkout; (3) Problem-first — show pain point trước khi reveal solution.",
        },
        {
            "dim": "Offer Framing trong Hook",
            "icon": "💸",
            "finding": f"CVR {cvr:.1f}% — {'offer resonates sau click — giữ nguyên message' if cvr > 5 else 'offer chưa translate thành action sau click'}.",
            "signal": "ok" if cvr > 5 else "warn",
            "action": "Offer phải xuất hiện trong 3 giây đầu, không đợi đến mid-video. User TikTok không kiên nhẫn đợi. Overlay text offer ngay frame 0-2.",
        },
        {
            "dim": "Video Pacing & Length",
            "icon": "⏱️",
            "finding": "TikTok feed cạnh tranh với organic content — video quá chậm mất attention trước khi truyền đủ message.",
            "signal": "warn" if ctr < 1 else "ok",
            "action": "Optimal: 7-15 giây cho UA. Mỗi 3 giây phải có một hook/reveal mới giữ retention. Tránh slow intro.",
        },
        {
            "dim": "CTA & Text Overlay",
            "icon": "✍️",
            "finding": "Text overlay và CTA phải cụ thể, không generic — 'Tải Zalopay nhận 15K' tốt hơn 'Tải ngay'.",
            "signal": "ok" if cvr > 5 else "warn",
            "action": "CTA cụ thể: kết nối với offer + action trong app. Kiểm tra: user biết họ nhận gì sau khi tải không? Text overlay: dùng bold + màu tương phản cao.",
        },
    ]
    gap_note = ""
    if ctr < 1.5 and cvr > 5:
        gap_note = "Low CTR + High CVR → message tốt nhưng hook chưa thumb-stop. Giữ nguyên offer, rebuild hook."
    elif ctr > 2 and cvr < 3:
        gap_note = "High CTR + Low CVR → hook hấp dẫn nhưng promise không match post-click. Audit landing/deeplink."
    return {
        "channel": "TikTok",
        "format": "Video",
        "dimensions": ["Hook / First 3s", "Offer Framing", "Video Pacing", "CTA & Text Overlay"],
        "analysis_order": "Hook/First 3s → Video Pacing → Offer Framing → CTA",
        "key_insight": "TikTok: hook 3 giây đầu quyết định CTR. Concept chỉ phát huy khi hook đủ mạnh. Offer phải visible trong 3s đầu.",
        "gap_note": gap_note,
        "specific_analysis": findings,
    }


def _skill_facebook(r: dict, all_results: list) -> dict:
    ctr, cvr = r.get("ctr_pct", 0), r.get("cvr_pct", 0)
    findings = [
        {
            "dim": "Format (Static vs Video)",
            "icon": "🖼️",
            "finding": f"CTR {ctr:.2f}% — Format quyết định cách user tiếp nhận message trong feed.",
            "signal": "warn" if ctr < 1 else "ok",
            "action": "Test static (single image) vs carousel vs video. Static phù hợp offer rõ ràng; carousel phù hợp nhiều use case; video phù hợp story-telling.",
        },
        {
            "dim": "Text % & Offer Visibility",
            "icon": "📊",
            "finding": "Meta penalizes ads với text quá nhiều trên image. Offer phải visible ngay từ thumbnail.",
            "signal": "warn",
            "action": "Rule: text trên ảnh ≤20% diện tích. Offer number (VD: 15K) nên là focal point của image. Dùng contrast color để offer nổi bật.",
        },
        {
            "dim": "Hook / Thumbnail",
            "icon": "🎣",
            "finding": f"CTR {ctr:.2f}% — Thumbnail/first frame quyết định user có dừng scroll không.",
            "signal": "warn" if ctr < 1 else "ok",
            "action": "Test thumbnail: human face > product only > graphic. Offer in thumbnail > offer in caption. Màu sắc tương phản cao với feed mặc định.",
        },
        {
            "dim": "CTA & Ad Copy",
            "icon": "✍️",
            "finding": f"CVR {cvr:.1f}% — Ad copy phải qualify đúng intent trước khi user click.",
            "signal": "ok" if cvr > 5 else "warn",
            "action": "Primary text: nêu pain/benefit trong câu đầu. CTA: cụ thể ('Nhận 15K') không generic ('Xem thêm'). Caption phải match với image offer.",
        },
    ]
    gap_note = ""
    if ctr < 1 and cvr > 5:
        gap_note = "Low CTR + High CVR → message qualify tốt nhưng creative chưa thumb-stop. Test thumbnail mới."
    elif ctr > 2 and cvr < 3:
        gap_note = "High CTR + Low CVR → click rồi nhưng không convert. Kiểm tra landing page hoặc deeplink mismatch."
    return {
        "channel": "Meta / Facebook",
        "dimensions": ["Format (Static/Video)", "Text % & Offer Visibility", "Hook / Thumbnail", "CTA & Ad Copy"],
        "analysis_order": "Format → Hook/Thumbnail → Offer Visibility → CTA",
        "key_insight": "Meta: hook + offer visibility trong thumbnail quyết định CTR. Text% trên ảnh ≤20%. Offer phải visible không cần đọc caption.",
        "gap_note": gap_note,
        "specific_analysis": findings,
    }


def _skill_google(r: dict, all_results: list) -> dict:
    ctr, cvr = r.get("ctr_pct", 0), r.get("cvr_pct", 0)
    findings = [
        {
            "dim": "Headline Clarity",
            "icon": "📢",
            "finding": f"CTR {ctr:.2f}% — Headline phải nêu rõ benefit cụ thể, không chỉ brand name.",
            "signal": "warn" if ctr < 0.5 else "ok",
            "action": "Test headline variants: benefit-led ('Nhận 15K khi tải') vs feature-led ('Thanh toán mọi nơi') vs use-case-led ('Thanh toán TikTok Shop').",
        },
        {
            "dim": "Asset Quality (Image/Video)",
            "icon": "🎨",
            "finding": "Google UAC auto-mix assets — asset quality thấp sẽ bị deprioritize.",
            "signal": "warn",
            "action": "Upload đủ: 1-2 landscape (1200×628), 1-2 square (1200×1200), 1-2 portrait (960×1200). Image phải high-res và offer-visible.",
        },
        {
            "dim": "Description",
            "icon": "📝",
            "finding": f"CVR {cvr:.1f}% — Description phải reinforce offer và clarify action tiếp theo.",
            "signal": "ok" if cvr > 3 else "warn",
            "action": "Description: expand on headline offer + nêu cụ thể action trong app. Tránh generic phrases như 'Tải ngay để trải nghiệm'.",
        },
        {
            "dim": "CTA",
            "icon": "👆",
            "finding": "Google cho phép chọn CTA button — chọn CTA phù hợp với campaign goal.",
            "signal": "ok",
            "action": "Với NPU goal: 'Cài đặt ngay' > 'Tải xuống' > 'Dùng thử'. Test CTA button kết hợp với headline benefit.",
        },
    ]
    return {
        "channel": "Google / UAC",
        "dimensions": ["Headline Clarity", "Asset Quality", "Description", "CTA"],
        "analysis_order": "Asset Group → Headline → Description → Image/Video Quality → CTA",
        "key_insight": "Google UAC auto-optimizes placement — focus vào asset quality và message clarity. Upload đủ size và test headline variants.",
        "gap_note": "",
        "specific_analysis": findings,
    }


def _skill_general(r: dict, all_results: list) -> dict:
    ctr, cvr = r.get("ctr_pct", 0), r.get("cvr_pct", 0)
    return {
        "channel": "General",
        "dimensions": ["Offer / Promotion", "CTA", "Visual Hook", "Message Clarity"],
        "analysis_order": "Delivery Dimension → Offer → CTA → Visual",
        "key_insight": "Chưa xác định channel cụ thể — phân tích theo dimension chung: offer, CTA, visual hook, message clarity.",
        "gap_note": "",
        "specific_analysis": [
            {"dim": "Offer / Promotion", "icon": "💰", "finding": f"CVR {cvr:.1f}%.", "signal": "ok" if cvr > 3 else "warn", "action": "Kiểm tra offer có cụ thể và visible không."},
            {"dim": "CTA", "icon": "👆", "finding": f"CTR {ctr:.2f}%.", "signal": "ok" if ctr > 1 else "warn", "action": "CTA phải kết nối với benefit cụ thể."},
        ],
    }


def _has_promo_signal(entity: str) -> bool:
    """Check if entity/campaign name contains promotion/offer signal."""
    e = entity.lower()
    promo_keywords = [
        "promo", "voucher", "discount", "cashback", "offer", "deal",
        "giam", "giảm", "uu dai", "ưu đãi", "tang", "tặng", "free",
        "15k", "20k", "30k", "50k", "100k", "nhan", "nhận",
    ]
    return any(kw in e for kw in promo_keywords)


@app.get("/")
async def dashboard():
    # no-store: luôn nạp bản mới nhất, tránh browser cache làm "fix không thấy đổi"
    return FileResponse(
        Path(__file__).parent / "static" / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "build": APP_BUILD, "model": LLM_MODEL, "llm_configured": bool(LLM_ENDPOINT and LLM_API_KEY)}


@app.get("/sample-csv")
async def sample_csv():
    p = Path(__file__).parent / "demo" / "sample_input.csv"
    if p.exists():
        return FileResponse(p, media_type="text/csv", filename="sample_input.csv")
    raise HTTPException(404, "Sample file not found")


@app.post("/api/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    content = await file.read()
    try:
        filename = (file.filename or "").lower()
        df = pd.read_excel(io.BytesIO(content)) if filename.endswith((".xlsx", ".xls")) else pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(400, f"Cannot parse file: {e}")
    df.columns = [c.strip() for c in df.columns]
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    sample = df.head(5).fillna("").to_dict(orient="records")
    mode_info = _detect_analysis_mode([c.lower() for c in df.columns])
    return {"columns": list(df.columns), "numeric_columns": numeric_cols, "row_count": len(df), "sample_rows": sample, "detected_mode": mode_info}


@app.post("/api/parse-naming")
async def parse_naming(body: dict):
    samples = body.get("samples", [])
    if not samples:
        raise HTTPException(400, "No samples provided")
    sample = str(samples[0])
    delimiter = "_"
    if sample.count("_") < 2 and sample.count("-") > sample.count("_"):
        delimiter = "-"
    parts = sample.split(delimiter)
    common_meanings = ["Team", "Promotion", "Team", "Format", "Content ID", "Version / Concept ID", "Version", "Size", "Creative Date"]
    fields = []
    for i, part in enumerate(parts):
        meaning = common_meanings[i] if i < len(common_meanings) else "Other"
        p = part.strip().lower()
        clean = re.sub(r"\.(jpg|jpeg|png|webp|gif)$", "", p)
        if p in ("android", "ios"): meaning = "OS"
        elif p in ("gg ua", "google", "tiktok ua", "tiktok fs", "facebook", "moloco"): meaning = "Channel / Media"
        elif p.startswith("aeo-") or p.startswith("ret-"): meaning = "Optimization Event"
        elif p.startswith("zpi") or p.startswith("zfs") or p.startswith("mkt"): meaning = "Team"
        elif re.fullmatch(r"\d+(\.\d+)?k", p) or any(token in p for token in ("promo", "voucher", "discount", "cashback", "offer")): meaning = "Promotion"
        elif p in ("promo", "nonpromo", "nonpro"): meaning = "Creative Type"
        elif p in ("image", "img", "video", "banner", "html5", "static"): meaning = "Format"
        elif re.fullmatch(r"\d+x\d+", p): meaning = "Size"
        elif re.fullmatch(r"v\d+", p): meaning = "Version"
        elif re.fullmatch(r"\d{1,2}[a-z]{3}", clean) or re.fullmatch(r"\d{6,8}", clean): meaning = "Creative Date"
        elif "tiktok one" in p: meaning = "Use Case / Creative"
        elif p.isdigit() and len(p) == 6: meaning = "Date"
        fields.append({"index": i, "value": part, "meaning": meaning})
    return {"fields": fields, "delimiter": delimiter, "sample": sample}


# ── Main Analysis ──────────────────────────────────────────

@app.post("/api/analyze")
async def analyze_v2(
    file: UploadFile = File(...),
    config: str = Form("{}"),
    images: list[UploadFile] = File(default=[]),
):
    cfg = json.loads(config)
    content = await file.read()
    try:
        filename = (file.filename or "").lower()
        df = pd.read_excel(io.BytesIO(content)) if filename.endswith((".xlsx", ".xls")) else pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(400, f"Cannot parse file: {e}")

    df.columns = [c.strip().lower() for c in df.columns]

    channels = cfg.get("channels", [])
    analysis_question = cfg.get("analysis_question", "")
    breakdown_dim = cfg.get("breakdown_dimension", cfg.get("analysis_level", "")).lower()
    primary_metric = cfg.get("primary_metric", cfg.get("cpa_action_col", "")).lower()
    supporting_metrics = [s.lower() for s in cfg.get("supporting_metrics", [])]
    cpa_benchmark = float(cfg.get("cpa_benchmark") or 0)
    currency = cfg.get("currency", "USD")
    convert_to_vnd = currency == "USD_TO_VND"
    display_currency = "VND" if convert_to_vnd else currency

    if not breakdown_dim or breakdown_dim not in df.columns:
        for fb in ["campaign_name", "ad_name", "ad_group_name", "creative", "title"]:
            if fb in df.columns:
                breakdown_dim = fb
                break
        else:
            breakdown_dim = df.columns[0]

    def _is_computed_metric_col(name: str) -> bool:
        n = str(name or "").lower()
        return any(k in n for k in ["ecpa", "e_cpa", "cpa", "cpi", "cost", "spend", "%", "%cr", "ctr", "cvr", "roas", "revenue"]) or " rate" in n or n.endswith("_rate")

    if primary_metric and _is_computed_metric_col(primary_metric):
        primary_metric = ""

    if not primary_metric or primary_metric not in df.columns:
        for c in df.columns:
            if not _is_computed_metric_col(c) and ("login" in c or "install" in c or "payment" in c or "npu" in c or "mpu" in c):
                primary_metric = c
                break
        else:
            for c in df.columns:
                if "click" in c:
                    primary_metric = c
                    break
    cfg["_resolved_primary_metric"] = primary_metric

    cost_col = _find_col(supporting_metrics, df.columns, "cost")
    click_col = _find_col(supporting_metrics, df.columns, "click")
    imp_col = _find_col(supporting_metrics, df.columns, "impression")

    mode_info = _detect_analysis_mode(list(df.columns))
    selected_channels = [str(c).lower() for c in cfg.get("channels", [])]
    is_notification = (
        mode_info.get("mode") == "notification"
        or "notification" in mode_info.get("possible_modes", [])
        or any(c in ("push notification", "message", "in-app message") for c in selected_channels)
    )
    if is_notification:
        try:
            return _analyze_notification(df, cfg, mode_info, images)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JSONResponse(status_code=500, content={"error": str(e), "detail": f"Notification analysis error: {e}"})

    # Creative-level grouping: when an ad_name is present (e.g. Moloco creatives that
    # share one campaign_name but differ by ad), break down by ad_name so each creative
    # is its own entity. Otherwise group by campaign_name as before.
    def _grp_key(r):
        camp = str(r.get(breakdown_dim, "") or "")
        ad = str(r.get("ad_name", "") or "").strip()
        if ad and ad.lower() not in ("nan", "none"):
            return ad
        return camp
    if "ad_name" in df.columns:
        df["_grp"] = df.apply(_grp_key, axis=1)
        group_col = "_grp"
        # Representative campaign_name per group (for channel/OS context detection).
        grp_to_camp = df.groupby(group_col)[breakdown_dim].first().to_dict()
    else:
        group_col = breakdown_dim
        grp_to_camp = {}

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    agg_dict = {c: "sum" for c in numeric_cols if c != group_col}
    if agg_dict:
        grouped = df.groupby(group_col, as_index=False).agg(agg_dict)
    else:
        grouped = df.groupby(group_col, as_index=False).first()

    results = []
    for _, row in grouped.iterrows():
        entity = str(row[group_col])
        # Context for channel/OS detection: the creative ad_name (entity) often omits
        # channel/OS, so combine it with the parent campaign_name.
        camp = str(grp_to_camp.get(entity, entity))
        context = f"{entity} {camp}"
        cost_raw = float(row.get(cost_col, 0) or 0) if cost_col else 0
        actions = float(row.get(primary_metric, 0) or 0) if primary_metric else 0
        cost_display = cost_raw * FX_RATE if convert_to_vnd else cost_raw
        cpa_display = cost_display / actions if actions > 0 else 0
        impressions = float(row.get(imp_col, 0) or 0) if imp_col else 0
        clicks = float(row.get(click_col, 0) or 0) if click_col else 0
        ctr = (clicks / impressions * 100) if impressions > 0 else 0
        cvr = (actions / clicks * 100) if clicks > 0 else 0
        vs_plan = ((cpa_display - cpa_benchmark) / cpa_benchmark * 100) if cpa_benchmark > 0 else None

        # Channel: user selection takes priority — only fall back to name when nothing selected
        detected_ch = _resolve_channel(context, channels)
        # Format & size: prefer the creative ad_name, fall back to campaign context.
        ad_format = _extract_format(entity)
        if ad_format == "Unknown":
            ad_format = _extract_format(camp)
        ad_size = _extract_size(entity) or _extract_size(camp)
        sup_values = {}
        for s in supporting_metrics:
            if s in df.columns and s in row.index:
                sup_values[s] = float(row.get(s, 0) or 0)

        results.append({
            "entity": entity, "channel": detected_ch, "os": _guess_os(context),
            "format": ad_format, "size": ad_size,
            "source": "", "ctr_pct": round(ctr, 2), "cvr_pct": round(cvr, 2),
            "cpa_vnd": round(cpa_display), "vs_plan_pct": round(vs_plan, 1) if vs_plan is not None else None,
            "quality_score": 0, "decision": "", "cost_vnd": round(cost_display),
            "actions": int(actions), "clicks": int(clicks), "impressions": int(impressions),
            "primary_value": int(actions), "supporting_values": sup_values,
            "warning": "No primary metric events" if actions == 0 else None,
        })

    detected_channels = list(set(r["channel"] for r in results if r["channel"]))
    all_channels = list(set(channels + detected_channels))

    qs_weights = _objective_weights(cfg)
    _rank_and_decide(results, cpa_benchmark, qs_weights)

    audience_ctx = _build_audience_context(cfg)
    ccy = "đ" if display_currency == "VND" else "$" if display_currency == "USD" else display_currency

    # v6: new analysis order — variance first, then creative elements
    concept_groups = _detect_concept_groups(results)
    variance_check = _check_same_concept_variance(concept_groups, ccy)
    dim_priority = _get_dimension_priority(all_channels, list(df.columns))
    selected_channel_keys = {str(c).strip().lower() for c in all_channels}
    if "in-app display" in selected_channel_keys:
        for dp in dim_priority:
            if str(dp.get("channel", "")).lower() in ("moloco / programmatic", "moloco"):
                dp["channel"] = "In-app Display"
                dp["reason"] = "In-app Display banner inventory: size/placement ảnh hưởng trực tiếp đến CTR/Action Rate. Phải kiểm tra size trước khi kết luận concept thắng/thua."
    elif "dsp" in selected_channel_keys:
        for dp in dim_priority:
            if str(dp.get("channel", "")).lower() in ("moloco / programmatic", "moloco"):
                dp["channel"] = "DSP / Programmatic"
                dp["reason"] = "DSP / Programmatic banner inventory: size/placement ảnh hưởng trực tiếp đến CTR/Action Rate. Phải kiểm tra placement trước khi kết luận concept thắng/thua."
    elif "other network" in selected_channel_keys:
        for dp in dim_priority:
            if str(dp.get("channel", "")).lower() in ("moloco / programmatic", "moloco"):
                dp["channel"] = "Other Network"
                dp["reason"] = "Other Network banner placement: size/placement ảnh hưởng trực tiếp đến CTR/Action Rate. Phải kiểm tra placement trước khi kết luận concept thắng/thua."
    has_variance = bool(variance_check)
    primary_kind = _primary_metric_kind(primary_metric)
    best_for_action = max([r for r in results if r.get("actions", 0) > 0], key=lambda r: r.get("quality_score", 0), default={})
    action_skill = get_action_skill(
        primary_kind if primary_kind != "action" else "generic",
        cfg.get("goal", "ua"),
        cfg.get("segment", ""),
        float(best_for_action.get("ctr_pct") or 0),
        float(best_for_action.get("cvr_pct") or 0),
    )
    cfg["_action_skill"] = action_skill

    creative_takeaways = _build_creative_takeaways(results, cfg, all_channels, ccy, has_variance, dim_priority)
    key_learning = _build_key_learning(creative_takeaways, results, cfg, ccy, variance_check, dim_priority)
    recommendations = _build_recommendations(results, cfg, all_channels, ccy, has_variance, dim_priority)
    warnings = _build_warnings(cfg, results, list(df.columns), bool(images), all_channels)
    aq_l = str(analysis_question or "").lower()
    ctr_only = any(k in aq_l for k in ["ctr-only", "ctr only", "chỉ phân tích ctr", "chi phan tich ctr", "tối ưu ctr", "toi uu ctr", "attention-only", "attention only"])
    if ctr_only and primary_kind not in ("ctr", "click", "unknown"):
        warnings.append(f"Metric/context conflict: Primary Metric(s) đang là {primary_metric}, nhưng Analysis Brief yêu cầu CTR/attention-only. Report chỉ nên kết luận attention/packaging, không kết luận downstream quality.")

    response = {
        "status": "ok", "rows_processed": len(df), "entities_analyzed": len(results),
        "analysis_mode": mode_info["mode"], "possible_modes": mode_info["possible_modes"],
        "channels": all_channels, "detected_channels": detected_channels,
        "metrics_summary": results, "audience_context": audience_ctx,
        "creative_takeaways": creative_takeaways, "key_learning": key_learning,
        "recommendations": recommendations, "warnings": warnings,
        "variance_check": variance_check, "dimension_priority": dim_priority,
        "has_benchmark": cpa_benchmark > 0,
        "cpa_applicable": True,
        "display_currency": display_currency,
        "qs_objective": cfg.get("qs_objective", "balanced_ua"), "qs_weights": qs_weights,
        "analysis_question": analysis_question,
        "primary_metric_label": primary_metric, "breakdown_label": breakdown_dim,
        "primary_metric_kind": primary_kind,
        "rate_metric_label": _rate_metric_label(primary_metric),
        "cost_metric_label": _cost_metric_label(primary_metric),
        "primary_metric_formula": _primary_metric_formula(primary_metric),
        "action_skill": action_skill,
    }
    return _fix_mojibake(response)


# ── Helpers ────────────────────────────────────────────────

def _find_first_col(columns, candidates):
    cols = list(columns)
    for cand in candidates:
        cand_l = cand.lower()
        for c in cols:
            if c == cand_l:
                return c
    for cand in candidates:
        cand_l = cand.lower()
        for c in cols:
            if cand_l in c:
                return c
    return ""


def _find_col(selected, columns, keyword):
    selected = [str(s).lower() for s in (selected or [])]
    columns = list(columns)
    for s in selected:
        if keyword in s:
            for c in columns:
                if c.lower() == s:
                    return c
    for c in columns:
        if keyword in c.lower():
            return c
    return ""


def _find_click_cols(columns):
    return [c for c in columns if "click" in c.lower() and not c.strip().startswith("%")]


def _find_exact_metric_col(columns, names):
    norm_names = {n.lower().replace(" ", "").replace("_", "") for n in names}
    for c in columns:
        norm = c.lower().replace(" ", "").replace("_", "")
        if norm in norm_names:
            return c
    return ""


def _extract_promotion_text(*parts):
    import re
    text = " ".join(str(p or "") for p in parts)
    patterns = [
        r"\b\d+\s?k\b",
        r"\b\d+\.?\d*\s?%",
        r"\b\d{1,3}[.,]?\d{3}\s?(?:d|đ|vnd)\b",
        r"(?:voucher|cashback|discount|sale|free|promo|promotion)",
        r"(?:giáº£m|Æ°u Ä‘Ã£i|hoÃ n tiá»n|miá»…n phÃ­|voucher|khuyáº¿n mÃ£i)",
    ]
    found = []
    for pat in patterns:
        found.extend(m.group(0).strip() for m in re.finditer(pat, text, flags=re.IGNORECASE))
    cleaned = []
    for item in found:
        if item and item.lower() not in [x.lower() for x in cleaned]:
            cleaned.append(item)
    return ", ".join(cleaned[:4]) if cleaned else "No explicit promotion detected"


def _parse_user_focus(cfg):
    text = " ".join([
        str(cfg.get("analysis_question", "")),
        str(cfg.get("qs_objective", "")),
        str(cfg.get("primary_metric", "")),
    ]).lower()
    if "npu" in text:
        return "npu"
    if "mpu" in text:
        return "mpu"
    if any(k in text for k in ["payment", "revenue", "transaction", "first payment"]):
        return "payment"
    if any(k in text for k in ["funnel", "downstream", "full funnel", "conversion path"]):
        return "funnel"
    if any(k in text for k in ["title", "copy", "message", "body", "rewrite"]):
        return "title"
    if any(k in text for k in ["send time", "hour", "timing", "schedule", "khung gi"]):
        return "hour"
    if any(k in text for k in ["click rate", "ctr", "click signal"]):
        return "click_rate"
    return "general"


def _notification_quality_score(ctr, cvr, sent_rate, max_ctr, max_cvr, weights=None, open_rate=0, max_open=0):
    if weights is None:
        weights = {"sent": 20, "ctr": 40, "cvr": 40}
    w_sent = weights.get("sent", 0) + weights.get("sent_rate", 0) + weights.get("success_rate", 0) + weights.get("sent_volume", 0)
    w_ctr = weights.get("ctr", 0) + weights.get("click_rate", 0)
    w_cvr = weights.get("cvr", 0) + weights.get("payment_rate", 0) + weights.get("click_to_payment", 0)
    w_open = weights.get("open_rate", 0)
    total = w_sent + w_ctr + w_cvr + w_open
    if total == 0: total = 1
    w_sent, w_ctr, w_cvr, w_open = w_sent/total, w_ctr/total, w_cvr/total, w_open/total
    ctr_score = min(ctr / max(max_ctr, 0.01), 1.0) * 10
    cvr_score = min(cvr / max(max_cvr, 0.01), 1.0) * 10
    sent_score = min(sent_rate / 100, 1.0) * 10
    open_score = min(open_rate / max(max_open, 0.01), 1.0) * 10
    return round(ctr_score * w_ctr + cvr_score * w_cvr + sent_score * w_sent + open_score * w_open, 1)


def _notification_decision(item, median_ctr, median_cvr, median_sent):
    ctr_good = (item["ctr_pct"] or 0) >= median_ctr
    cvr_good = (item["cvr_pct"] or 0) >= median_cvr if item["cvr_pct"] is not None else True
    sent_good = (item["sent_rate_pct"] or 0) >= median_sent
    if ctr_good and cvr_good and sent_good:
        return "SCALE", "strong_notification"
    if not ctr_good and cvr_good:
        return "ITERATE COPY", "low_ctr_high_cvr"
    if ctr_good and not cvr_good:
        return "INVESTIGATE FUNNEL", "high_ctr_low_cvr"
    if not sent_good:
        return "CHECK DELIVERY", "low_sent_rate"
    if not ctr_good and not cvr_good:
        return "PAUSE", "weak_all"
    return "MAINTAIN", "mixed_signals"


def _analyze_notification(df, cfg, mode_info, images):
    cols = list(df.columns)
    breakdown_dim = cfg.get("breakdown_dimension", "").lower()
    if not breakdown_dim or breakdown_dim not in df.columns:
        breakdown_dim = _find_first_col(cols, ["campaign name", "campaign_name", "notification id", "notification_id", "title"])
        if not breakdown_dim:
            breakdown_dim = cols[0]

    title_col = _find_first_col(cols, ["title", "notification title"])
    desc_col = _find_first_col(cols, ["out-app description", "description", "message", "body"])
    time_col = _find_first_col(cols, ["send time", "sent time", "created time", "time"])
    sent_col = _find_first_col(cols, ["sent", "send", "total sent", "notification sent"])
    success_col = _find_first_col(cols, ["success", "delivered", "sent success"])
    open_col = _find_first_col(cols, ["open", "opens", "notification open", "noti open"])
    payment_col = _find_first_col(cols, ["payment", "payments", "paid", "transaction", "transactions", "orders"])
    click_cols = _find_click_cols(cols)
    open_rate_col = _find_exact_metric_col(cols, ["open rate", "open_rate", "%open", "% open"])
    ctr_col = _find_exact_metric_col(cols, ["ctr", "%ctr", "% ctr"])
    cr_col = _find_exact_metric_col(cols, ["%cr", "cr", "% cr", "conversion rate", "% conversion", "click-to-payment rate", "click to payment rate"])

    numeric_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    num_agg = {c: "sum" for c in numeric_cols if c != breakdown_dim}
    text_agg = {}
    for c in [title_col, desc_col, time_col]:
        if c and c not in num_agg and c != breakdown_dim:
            text_agg[c] = "first"
    agg_dict = {**num_agg, **text_agg}
    if agg_dict:
        try:
            grouped = df.groupby(breakdown_dim, as_index=False).agg(agg_dict)
        except (ValueError, TypeError):
            grouped = df.groupby(breakdown_dim, as_index=False).agg(num_agg) if num_agg else df.groupby(breakdown_dim, as_index=False).first()
            for c, fn in text_agg.items():
                if c in df.columns:
                    grouped[c] = df.groupby(breakdown_dim)[c].first().values
    else:
        grouped = df.groupby(breakdown_dim, as_index=False).first()

    has_open = bool(open_col or open_rate_col)
    has_payment = bool(payment_col)
    has_success = bool(success_col)
    has_click = bool(click_cols)

    denom_pref = cfg.get("click_rate_denominator", "auto")
    if denom_pref == "auto":
        if has_success:
            click_denom = "success"
        elif sent_col:
            click_denom = "sent"
        else:
            click_denom = "sent"
    else:
        click_denom = denom_pref

    results = []
    for _, row in grouped.iterrows():
        entity = str(row[breakdown_dim])
        sent = float(row.get(sent_col, 0) or 0) if sent_col else 0
        success = float(row.get(success_col, 0) or 0) if success_col else sent
        opens = float(row.get(open_col, 0) or 0) if (open_col and open_col in grouped.columns) else None
        clicks = sum(float(row.get(c, 0) or 0) for c in click_cols)
        payment = float(row.get(payment_col, 0) or 0) if payment_col else None
        sent_rate = (success / sent * 100) if sent > 0 else 0
        if has_open:
            open_rate_raw = float(row.get(open_rate_col, 0) or 0) if open_rate_col else 0
            o = opens if opens is not None else 0
            open_rate = open_rate_raw if 0 < open_rate_raw <= 100 else (open_rate_raw / 100 if open_rate_raw > 100 else ((o / success * 100) if success > 0 and o > 0 else 0))
        else:
            open_rate = None
        ctr_raw = float(row.get(ctr_col, 0) or 0) if ctr_col else 0
        if click_denom == "open" and has_open and opens and opens > 0:
            click_base = opens
        elif click_denom == "success" and success > 0:
            click_base = success
        else:
            click_base = sent if sent > 0 else success
        ctr = ctr_raw if 0 < ctr_raw <= 100 else (ctr_raw / 100 if ctr_raw > 100 else ((clicks / click_base * 100) if click_base > 0 else 0))
        if has_payment:
            cr_raw = float(row.get(cr_col, 0) or 0) if cr_col else 0
            p = payment if payment is not None else 0
            cvr = cr_raw if 0 < cr_raw <= 100 else (cr_raw / 100 if cr_raw > 100 else ((p / clicks * 100) if clicks > 0 and p > 0 else 0))
        else:
            cvr = None
        if has_open and has_payment and opens is not None and payment is not None:
            open_to_payment = (payment / opens * 100) if opens > 0 and payment > 0 else 0
        else:
            open_to_payment = None
        title = str(row.get(title_col, "") or "") if title_col else ""
        desc = str(row.get(desc_col, "") or "") if desc_col else ""
        send_time = str(row.get(time_col, "") or "") if time_col else ""
        results.append({
            "entity": entity, "channel": "Notification", "os": "", "source": "",
            "title": title, "description": desc,
            "send_time": send_time,
            "promotion": _extract_promotion_text(entity, title, desc),
            "sent": int(sent), "success": int(success), "sent_rate_pct": round(sent_rate, 3),
            "open": int(opens) if opens is not None else None,
            "open_rate_pct": round(open_rate, 3) if open_rate is not None else None,
            "ctr_pct": round(ctr, 3), "click_rate_pct": round(ctr, 3),
            "cvr_pct": round(cvr, 3) if cvr is not None else None,
            "click_to_payment_rate_pct": round(cvr, 3) if cvr is not None else None,
            "open_to_payment_rate_pct": round(open_to_payment, 3) if open_to_payment is not None else None,
            "payment": int(payment) if payment is not None else None,
            "cpa_vnd": None, "vs_plan_pct": None,
            "quality_score": 0, "decision": "", "pattern": "",
            "cost_vnd": 0, "actions": int((payment or 0) if has_payment else clicks),
            "clicks": int(clicks), "impressions": int(success),
            "primary_value": int((payment or 0) if has_payment else clicks),
            "supporting_values": {},
            "warning": "No payment conversion column detected" if not has_payment else None,
        })

    ctrs = sorted([r["ctr_pct"] for r in results if r["ctr_pct"] is not None])
    cvrs = sorted([r["cvr_pct"] for r in results if r["cvr_pct"] is not None])
    sents = sorted([r["sent_rate_pct"] for r in results if r["sent_rate_pct"] is not None])
    opens_rates = sorted([r["open_rate_pct"] for r in results if r["open_rate_pct"] is not None])
    median_ctr = ctrs[len(ctrs)//2] if ctrs else 0
    median_cvr = cvrs[len(cvrs)//2] if cvrs else 0
    median_sent = sents[len(sents)//2] if sents else 0
    max_ctr = max(ctrs) if ctrs else 0
    max_cvr = max(cvrs) if cvrs else 0
    max_open = max(opens_rates) if opens_rates else 0
    noti_weights = _notification_weights(cfg)
    avail_weights = {}
    for mk, mw in noti_weights.items():
        if mk in ("click_rate", "ctr") and has_click:
            avail_weights[mk] = mw
        elif mk in ("open_rate",) and has_open:
            avail_weights[mk] = mw
        elif mk in ("cvr", "payment_rate", "click_to_payment") and has_payment:
            avail_weights[mk] = mw
        elif mk in ("sent_rate", "success_rate", "sent_volume"):
            avail_weights[mk] = mw
        elif mk not in ("click_rate", "ctr", "open_rate", "cvr", "payment_rate", "click_to_payment"):
            avail_weights[mk] = mw
    if avail_weights and sum(avail_weights.values()) > 0:
        total_aw = sum(avail_weights.values())
        normalized_weights = {k: round(v / total_aw, 4) for k, v in avail_weights.items()}
    else:
        normalized_weights = noti_weights
    scoring_note = None
    if set(normalized_weights.keys()) != set(noti_weights.keys()):
        removed = set(noti_weights.keys()) - set(normalized_weights.keys())
        label_map = {
            "open_rate": "Open metric",
            "payment_rate": "Payment metric",
            "click_to_payment": "Payment/Login metric",
            "cvr": "Payment/Login metric",
        }
        removed_labels = [label_map.get(x, x) for x in sorted(removed)]
        scoring_note = f"Auto-normalized scoring: removed missing {', '.join(removed_labels)}. Remaining weights re-scaled to 100%."

    for r in results:
        r["quality_score"] = _notification_quality_score(
            r["ctr_pct"] or 0, r["cvr_pct"] or 0, r["sent_rate_pct"] or 0,
            max_ctr, max_cvr, normalized_weights, r["open_rate_pct"] or 0, max_open)
        r["decision"], r["pattern"] = _notification_decision(r, median_ctr, median_cvr, median_sent)

    click_denom_labels = {"success": "Click / Delivered (Success)", "sent": "Click / Sent", "open": "Click / Open"}
    metric_availability = {
        "open": has_open, "payment": has_payment, "success": has_success,
        "click": has_click, "sent": bool(sent_col),
    }
    hourly_data = _build_notification_hourly(df, time_col, sent_col, success_col, open_col, click_cols, payment_col)
    hourly = hourly_data["by_hour"]
    funnel_breakdown = _build_notification_funnel_breakdown(results)
    return {
        "status": "ok", "rows_processed": len(df), "entities_analyzed": len(results),
        "analysis_mode": "notification", "possible_modes": mode_info.get("possible_modes", ["notification"]),
        "channels": ["Notification"], "detected_channels": ["Notification"],
        "metrics_summary": results, "audience_context": _build_audience_context(cfg),
        "creative_takeaways": _build_notification_takeaways(results, hourly, has_payment),
        "key_learning": _build_notification_key_learning(results, hourly, has_payment, cfg),
        "recommendations": _build_notification_recommendations(results, hourly, has_payment, has_open),
        "warnings": _build_notification_warnings(title_col, desc_col, time_col, payment_col, bool(images)),
        "variance_check": [], "dimension_priority": [{
            "channel": "Notification / In-app",
            "order": ["Title", "Description", "Promotion trigger", "Send time", "%Sent", "CTR", "%CR to payment"],
            "reason": _vn(r"Notification l\u00e0 owned/free traffic n\u00ean CPA kh\u00f4ng ph\u00f9 h\u1ee3p; c\u1ea7n \u0111\u1ecdc title/description v\u00e0 funnel delivered -> click -> payment."),
        }],
        "hourly_performance": hourly_data, "funnel_breakdown": funnel_breakdown,
        "has_benchmark": False, "cpa_applicable": False,
        "display_currency": "N/A", "qs_objective": "notification_funnel",
        "qs_weights": normalized_weights, "qs_weights_original": noti_weights,
        "qs_scoring_note": scoring_note,
        "analysis_question": cfg.get("analysis_question", ""),
        "primary_metric_label": payment_col or "clicks", "breakdown_label": breakdown_dim,
        "notification_fields": {"title": title_col, "description": desc_col, "send_time": time_col, "sent": sent_col, "success": success_col, "open": open_col, "open_rate": open_rate_col, "clicks": click_cols, "payment": payment_col},
        "metric_availability": metric_availability,
        "click_rate_denominator": click_denom,
        "click_rate_formula": click_denom_labels.get(click_denom, f"Click / {click_denom}"),
    }


def _build_notification_hourly(df, time_col, sent_col, success_col, open_col, click_cols, payment_col):
    if not time_col:
        return {"by_hour": [], "by_day_hour": [], "has_weekday": False}
    work = df.copy()
    work["_send_dt"] = pd.to_datetime(work[time_col], errors="coerce")
    work = work[work["_send_dt"].notna()]
    if work.empty:
        return {"by_hour": [], "by_day_hour": [], "has_weekday": False}
    work["_hour"] = work["_send_dt"].dt.hour
    has_weekday = work["_send_dt"].dt.date.nunique() > 1
    if has_weekday:
        work["_dow"] = work["_send_dt"].dt.dayofweek

    def _agg_group(g):
        sent = float(g[sent_col].sum()) if sent_col else 0
        success = float(g[success_col].sum()) if success_col else sent
        opens = float(g[open_col].sum()) if open_col else None
        clicks = sum(float(g[c].sum()) for c in click_cols)
        payment = float(g[payment_col].sum()) if payment_col else None
        click_base = opens if opens is not None and opens > 0 else success
        return {
            "sent": int(sent), "success": int(success),
            "sent_rate_pct": round((success / sent * 100) if sent > 0 else 0, 3),
            "open": int(opens) if opens is not None else None,
            "open_rate_pct": round((opens / success * 100) if opens is not None and success > 0 and opens > 0 else 0, 3) if open_col else None,
            "clicks": int(clicks), "ctr_pct": round((clicks / click_base * 100) if click_base > 0 else 0, 3),
            "payment": int(payment) if payment is not None else None,
            "cvr_pct": round((payment / clicks * 100) if payment is not None and clicks > 0 and payment > 0 else 0, 3) if payment_col else None,
            "open_to_payment_rate_pct": round((payment / opens * 100) if opens is not None and payment is not None and opens > 0 and payment > 0 else 0, 3) if open_col and payment_col else None,
        }

    by_hour = []
    for hour, g in work.groupby("_hour"):
        row = _agg_group(g)
        row["hour"] = int(hour)
        by_hour.append(row)
    by_hour.sort(key=lambda x: (x["ctr_pct"], x["cvr_pct"], x["clicks"]), reverse=True)

    by_day_hour = []
    if has_weekday:
        for (dow, hour), g in work.groupby(["_dow", "_hour"]):
            row = _agg_group(g)
            row["dow"] = int(dow)
            row["hour"] = int(hour)
            by_day_hour.append(row)

    return {"by_hour": by_hour, "by_day_hour": by_day_hour, "has_weekday": has_weekday}


def _build_notification_funnel_breakdown(results):
    sent = sum(r.get("sent", 0) or 0 for r in results)
    delivered = sum(r.get("success", 0) or 0 for r in results)
    has_open = any(r.get("open_rate_pct") is not None for r in results)
    has_payment = any(r.get("cvr_pct") is not None for r in results)
    opens = sum(r.get("open", 0) or 0 for r in results) if has_open else None
    clicks = sum(r.get("clicks", 0) or 0 for r in results)
    payments = sum(r.get("payment", 0) or 0 for r in results) if has_payment else None
    click_base = opens if opens is not None and opens > 0 else delivered
    return {
        "sent": sent,
        "delivered": delivered,
        "open": opens,
        "clicks": clicks,
        "payment": payments,
        "sent_rate_pct": round((delivered / sent * 100) if sent else 0, 3),
        "open_rate_pct": round((opens / delivered * 100) if opens is not None and delivered and opens else 0, 3) if has_open else None,
        "click_rate_pct": round((clicks / click_base * 100) if click_base else 0, 3),
        "click_to_payment_rate_pct": round((payments / clicks * 100) if payments is not None and clicks and payments else 0, 3) if has_payment else None,
        "open_to_payment_rate_pct": round((payments / opens * 100) if opens is not None and payments is not None and opens and payments else 0, 3) if has_open and has_payment else None,
    }


def _build_notification_key_learning(results, hourly, has_payment, cfg=None):
    cfg = cfg or {}
    if not results:
        return {
            "learning": _vn(r"Ch\u01b0a c\u00f3 notification \u0111\u1ec3 ph\u00e2n t\u00edch."),
            "bottleneck": _vn(r"Thi\u1ebfu d\u1eef li\u1ec7u notification."),
            "next_step": _vn(r"Upload notification report c\u00f3 title, description, send time, sent/success v\u00e0 click."),
            "structured": None,
        }

    has_open_data = any(r.get("open_rate_pct") is not None for r in results)
    has_payment_data = any(r.get("cvr_pct") is not None for r in results)
    available_metrics = ["Sent / Success", "Click / Click Rate"]
    missing_metrics = []
    if has_open_data:
        available_metrics.insert(1, "Open / Open Rate")
    if has_payment_data:
        available_metrics.append("Payment / Payment Rate")

    best = max(results, key=lambda r: ((r.get("ctr_pct") or 0), (r.get("sent_rate_pct") or 0), (r.get("quality_score") or 0)))
    worst = min(results, key=lambda r: ((r.get("ctr_pct") or 0), (r.get("sent_rate_pct") or 0), -(r.get("quality_score") or 0)))
    top_hour = hourly[0] if hourly else None

    best_click = best.get("ctr_pct") or 0
    worst_click = worst.get("ctr_pct") or 0
    best_title = best.get("title") or best.get("entity") or "Best notification"
    worst_title = worst.get("title") or worst.get("entity") or "Weak notification"
    best_desc = best.get("description") or ""
    best_promo = best.get("promotion") or ""

    def classify_trigger(title, desc, promo):
        txt = f"{title} {desc} {promo}".lower()
        if any(k in txt for k in ["fpt", "bill", "internet", "payment", "pay", "hoa don", _vn(r"h\u00f3a \u0111\u01a1n"), _vn(r"thanh to\u00e1n"), "dien", "nuoc", _vn(r"\u0111i\u1ec7n"), _vn(r"n\u01b0\u1edbc"), "tiktok", "shop"]):
            return _vn(r"use case c\u1ee5 th\u1ec3")
        if any(k in txt for k in ["voucher", "cashback", "%", "15k", "10k", "discount", "offer", _vn(r"\u01b0u \u0111\u00e3i"), _vn(r"gi\u1ea3m")]):
            return "promotion / offer"
        if any(k in txt for k in ["today", "now", "deadline", "due", _vn(r"h\u00f4m nay"), _vn(r"\u0111\u1ebfn h\u1ea1n")]):
            return "urgency"
        if "?" in title:
            return _vn(r"c\u00e2u h\u1ecfi tr\u1ef1c di\u1ec7n")
        return "generic benefit"

    def trigger_reason(trigger):
        if trigger == _vn(r"use case c\u1ee5 th\u1ec3"):
            return _vn(r"message g\u1ecdi \u0111\u00fang m\u1ed9t t\u00ecnh hu\u1ed1ng c\u1ee5 th\u1ec3 n\u00ean user hi\u1ec3u ngay v\u00ec sao notification li\u00ean quan \u0111\u1ebfn m\u00ecnh.")
        if trigger == "promotion / offer":
            return _vn(r"offer t\u1ea1o l\u00fd do click r\u00f5, nh\u01b0ng body v\u1eabn c\u1ea7n n\u00f3i r\u00f5 h\u00e0nh \u0111\u1ed9ng ti\u1ebfp theo \u0111\u1ec3 tr\u00e1nh click t\u00f2 m\u00f2.")
        if trigger == "urgency":
            return _vn(r"y\u1ebfu t\u1ed1 th\u1eddi \u0111i\u1ec3m c\u00f3 th\u1ec3 t\u1ea1o \u0111\u1ed9ng l\u1ef1c x\u1eed l\u00fd ngay n\u1ebfu message \u0111\u1ee7 c\u1ee5 th\u1ec3.")
        if trigger == _vn(r"c\u00e2u h\u1ecfi tr\u1ef1c di\u1ec7n"):
            return _vn(r"c\u00e1ch \u0111\u1eb7t c\u00e2u h\u1ecfi gi\u00fap user t\u1ef1 nh\u1eadn di\u1ec7n nhu c\u1ea7u.")
        return _vn(r"message c\u00f2n chung, ch\u01b0a n\u00f3i r\u00f5 user nh\u1eadn g\u00ec, c\u1ea7n l\u00e0m g\u00ec v\u00e0 v\u00ec sao ph\u1ea3i click ngay.")

    best_trigger = classify_trigger(best_title, best_desc, best_promo)
    worst_trigger = classify_trigger(worst_title, worst.get("description") or "", worst.get("promotion") or "")
    focus_text = " ".join([str(cfg.get("analysis_question", "")), str(cfg.get("qs_objective", "")), str(cfg.get("primary_metric", "")), str(cfg.get("breakdown_dimension", ""))]).lower()
    funnel_focus = any(k in focus_text for k in ["open", "payment", "login", "funnel", "downstream", "conversion", "cvr", "%cr"])

    # Segment context for deeper insight
    segment = cfg.get("segment", "")
    age_min = cfg.get("age_min", 18)
    age_max = cfg.get("age_max", 65)
    location = cfg.get("location", "Vietnam")
    seg_ctx = f" v\u1edbi segment \u2018{segment}\u2019 ({age_min}\u2013{age_max} tu\u1ed5i, {location})" if segment else ""
    seg_hypothesis = (
        f" V\u1edbi segment \u2018{segment}\u2019: title n\u00ean \u0111\u1eb7t \u0111\u00fang scenario h\u1ecd \u0111ang g\u1eb7p, kh\u00f4ng ch\u1ec9 n\u00eau l\u1ee3i \u00edch chung."
        if segment else ""
    )
    seg_variant_hint = (
        f" Copy variant cho \u2018{segment}\u2019: d\u00f9ng ng\u00f4n ng\u1eef v\u00e0 scenario c\u1ee7a h\u1ecd (v\u00ed d\u1ee5: \u2018B\u1ea1n ch\u01b0a thanh to\u00e1n l\u1ea7n n\u00e0o\u2014nh\u1eadn ngay \u01b0u \u0111\u00e3i\u2019 thay v\u00ec generic)."
        if segment else ""
    )

    if best_click > 0:
        learning_summary = (
            f"Best notification th\u1eafng \u1edf Click Rate{seg_ctx}: \u2018{best_title[:50]}\u2019 \u0111\u1ea1t {best_click:.3f}%. "
            f"Pattern m\u1ea1nh: {best_trigger} \u2014 {trigger_reason(best_trigger)}{seg_hypothesis}"
        )
    else:
        learning_summary = "Ch\u01b0a c\u00f3 notification n\u00e0o t\u1ea1o \u0111\u01b0\u1ee3c click signal r\u00f5 r\u00e0ng trong d\u1eef li\u1ec7u hi\u1ec7n c\u00f3."

    if worst_click <= 0:
        bottleneck_summary = (
            f"Weak: \u2018{worst_title[:50]}\u2019 Click Rate 0.000%. "
            "Title/body ch\u01b0a t\u1ea1o l\u00fd do click: kh\u00f4ng n\u00f3i r\u00f5 user nh\u1eadn g\u00ec, c\u1ea7n l\u00e0m g\u00ec, v\u00e0 t\u1ea1i sao ph\u1ea3i click ngay b\u00e2y gi\u1edd."
        )
    else:
        bottleneck_summary = (
            f"Weak: \u2018{worst_title[:50]}\u2019 ch\u1ec9 \u0111\u1ea1t {worst_click:.3f}%. "
            f"Pattern y\u1ebfu ({worst_trigger}): message c\u1ea7n r\u00f5 h\u01a1n v\u1ec1 user nh\u1eadn g\u00ec v\u00e0 h\u00e0nh \u0111\u1ed9ng ti\u1ebfp theo."
        )

    # --- Connected story next_step: winner pattern + timing + specific test ---
    top3_hours = [f"{h['hour']:02d}:00" for h in (hourly or [])[:3]]
    hours_str = " / ".join(top3_hours) if top3_hours else None
    winner_hour_str = f"{top_hour['hour']:02d}:00" if top_hour else None

    if best_click > 0 and winner_hour_str:
        # Story: winner won because of [trigger] + [timing] \u2192 test to isolate driver
        step1 = _vn(
            r"B\u01af\u1edaC 1 \u2014 Isolate driver: Best notification '{title}' (Click Rate {rate:.3f}%) "
            r"th\u1eafng v\u1edbi pattern '{trigger}' v\u00e0 g\u1eedi l\u00fac {hour}. "
            r"Test: gi\u1eef nguy\u00ean title/body, A/B send time {hours} \u0111\u1ec3 x\u00e1c nh\u1eadn timing hay copy l\u00e0 driver ch\u00ednh."
        ).format(title=best_title[:35], rate=best_click, trigger=best_trigger, hour=winner_hour_str, hours=hours_str or winner_hour_str)
        step2 = (
            f"B\u01b0\u1edbc 2 \u2014 T\u1ed1i \u01b0u copy: Sau khi x\u00e1c nh\u1eadn timing, t\u1ea1o 3 variant t\u1eeb pattern \u2018{best_trigger}\u2019 c\u1ee7a winner: "
            f"(1) Use-case-led: \u0111\u1eb7t th\u1eb3ng t\u00ecnh hu\u1ed1ng user c\u1ea7n x\u1eed l\u00fd. "
            f"(2) Benefit-led: n\u00f3i r\u00f5 l\u1ee3i \u00edch + h\u00e0nh \u0111\u1ed9ng c\u1ee5 th\u1ec3. "
            f"(3) Urgency-led: th\u00eam l\u00fd do th\u1eddi \u0111i\u1ec3m. "
            f"G\u1eedi \u1edf {top3_hours[0] if top3_hours else winner_hour_str} (peak \u0111\u00e3 x\u00e1c nh\u1eadn t\u1eeb B\u01b0\u1edbc 1)."
            f"{seg_variant_hint}"
        )
        next_step_summary = step1 + "\n" + step2
    elif best_click > 0:
        # Has winner but no timing data
        next_step_summary = _vn(
            r"Winner pattern '{trigger}' t\u1eeb '{title}' (Click Rate {rate:.3f}%). "
            r"T\u1ea1o 3 variant: (1) Use-case-led, (2) Benefit-led, (3) Urgency-led. "
            r"Gi\u1eef c\u00f9ng m\u1ed9t send time \u0111\u1ec3 isolate copy impact."
        ).format(trigger=best_trigger, title=best_title[:35], rate=best_click)
    else:
        # No winner signal
        next_step_summary = _vn(
            r"Ch\u01b0a c\u00f3 click signal r\u00f5 r\u00e0ng. "
            r"Test c\u1ea3 3 h\u01b0\u1edbng copy: use-case-led, benefit-led, urgency-led. "
            r"G\u1eedi \u1edf {hours} (peak theo sent volume hi\u1ec7n t\u1ea1i)."
        ).format(hours=hours_str or "gi\u1edd cao \u0111i\u1ec3m")

    # Split BƯỚC 1 / BƯỚC 2 into separate items for frontend ordered list
    if '\nBƯỚC 2' in next_step_summary:
        parts = next_step_summary.split('\nBƯỚC 2')
        test_items = [parts[0].strip(), 'BƯỚC 2' + parts[1].strip()]
    elif '\n' in next_step_summary:
        test_items = [s.strip() for s in next_step_summary.split('\n') if s.strip()]
    else:
        test_items = [next_step_summary]

    if funnel_focus and (not has_open_data or not has_payment_data):
        next_step_summary += _vn(r" N\u1ebfu m\u1ee5c ti\u00eau l\u00e0 audit full funnel, b\u1ed5 sung conversion metric ph\u00f9 h\u1ee3p v\u1edbi campaign.")

    limitation_note = ""
    recommended_data = []
    user_focus = _parse_user_focus(cfg)
    avail_str = " / ".join(available_metrics)
    if has_open_data and has_payment_data:
        pass
    elif user_focus in ("click_rate", "title", "send_time", "hour", "body"):
        limitation_note = _vn(r"Ph\u00e2n t\u00edch hi\u1ec7n d\u1ef1a tr\u00ean metric c\u00f3 s\u1eb5n: {avail}.").format(avail=avail_str)
    else:
        limitation_note = _vn(r"Ph\u00e2n t\u00edch hi\u1ec7n d\u1ef1a tr\u00ean metric c\u00f3 s\u1eb5n: {avail}. N\u1ebfu mu\u1ed1n \u0111\u00e1nh gi\u00e1 s\u00e2u h\u01a1n theo funnel, h\u00e3y b\u1ed5 sung ho\u1eb7c \u0111\u1ecbnh ngh\u0129a conversion metric ph\u00f9 h\u1ee3p (v\u00ed d\u1ee5 NPU, MPU, Login, Payment ho\u1eb7c event ri\u00eang c\u1ee7a campaign).").format(avail=avail_str)
    if user_focus == "npu":
        recommended_data = ["NPU event", "Click-to-NPU rate"]
    elif user_focus == "mpu":
        recommended_data = ["MPU event", "Monthly active/payment user", "Cohort/month"]
    elif user_focus == "payment":
        if not has_payment_data:
            recommended_data = ["Payment event", "Click-to-payment rate"]
    elif user_focus == "funnel":
        if not has_open_data:
            recommended_data.append("Open event")
        if not has_payment_data:
            recommended_data.append("Conversion event (NPU, Login, Payment...)")
    elif user_focus in ("click_rate", "title", "send_time", "hour", "body"):
        pass
    else:
        if not has_open_data or not has_payment_data:
            recommended_data.append(_vn(r"B\u1ea1n c\u00f3 th\u1ec3 b\u1ed5 sung conversion metric nh\u01b0 NPU, MPU, Login, Payment ho\u1eb7c action event c\u1ee7a campaign n\u1ebfu mu\u1ed1n ph\u00e2n t\u00edch s\u00e2u h\u01a1n."))

    learning_bullets = [{"text": learning_summary, "signal": "info"}]

    return {
        "learning": learning_summary,
        "bottleneck": bottleneck_summary,
        "next_step": next_step_summary,
        "structured": {
            "best_entity": best.get("entity", ""), "best_title": best_title, "best_description": best_desc, "best_promotion": best_promo, "best_send_time": best.get("send_time", ""),
            "best_hour": f"{top_hour['hour']:02d}:00" if top_hour else None,
            "best_hour_metrics": {"ctr_pct": top_hour.get("ctr_pct") or 0, "sent": top_hour.get("sent") or 0} if top_hour else None,
            "worst_entity": worst.get("entity", ""), "title_trigger": best_trigger, "desc_trigger": "description supports click intent" if best_desc else "description missing", "promo_trigger": best_promo,
            "use_case": best_trigger if best_trigger == _vn(r"use case c\u1ee5 th\u1ec3") else "", "tracking_anomaly": False,
            "has_open_data": has_open_data, "has_payment_data": has_payment_data, "available_metrics": available_metrics, "missing_metrics": [],
            "learning_bullets": learning_bullets, "bottleneck_bullets": [{"text": bottleneck_summary, "signal": "risk"}], "next_step_items": test_items,
            "data_limitation_note": limitation_note,
            "recommended_data": recommended_data,
            "best_metrics": {"sent_rate_pct": best.get("sent_rate_pct") or 0, "open_rate_pct": best.get("open_rate_pct") if has_open_data else None, "click_rate_pct": best_click, "click_to_payment_pct": best.get("cvr_pct") if has_payment_data else None, "open_count": best.get("open") if has_open_data else None},
            "worst_metrics": {"open_rate_pct": worst.get("open_rate_pct") if has_open_data else None, "click_rate_pct": worst_click, "click_to_payment_pct": worst.get("cvr_pct") if has_payment_data else None},
        },
    }


def _build_notification_takeaways(results, hourly, has_payment):
    if not results:
        return []
    has_open_data = any(r.get("open_rate_pct") is not None for r in results)
    has_payment_data = any(r.get("cvr_pct") is not None for r in results)
    best_click = max(results, key=lambda r: (r.get("ctr_pct") or 0, r.get("sent_rate_pct") or 0))
    weak_click = min(results, key=lambda r: (r.get("ctr_pct") or 0, -(r.get("sent_rate_pct") or 0)))
    best_title = best_click.get("title") or best_click.get("entity") or "Best notification"
    best_desc = best_click.get("description") or "N/A"
    weak_title = weak_click.get("title") or weak_click.get("entity") or "Weak notification"
    takeaways = [
        {"element": "Title", "signal": _vn(r"Title '{title}' \u0111\u1ea1t Click Rate {rate:.3f}%.").format(title=best_title, rate=(best_click.get('ctr_pct') or 0)), "strength": _vn(r"Title t\u1ed1t nh\u1ea5t \u0111\u1ee7 c\u1ee5 th\u1ec3 \u0111\u1ec3 user hi\u1ec3u l\u00fd do c\u1ea7n click."), "weakness": _vn(r"Pattern y\u1ebfu: '{title}' kh\u00f4ng t\u1ea1o \u0111\u1ee7 click intent n\u1ebfu message generic ho\u1eb7c offer m\u01a1 h\u1ed3.").format(title=weak_title), "insight": _vn(r"Title d\u1ea1ng use case c\u1ee5 th\u1ec3 ho\u1eb7c c\u00e2u h\u1ecfi tr\u1ef1c di\u1ec7n th\u01b0\u1eddng t\u1ed1t h\u01a1n promo generic v\u00ec user t\u1ef1 nh\u1eadn di\u1ec7n \u0111\u01b0\u1ee3c nhu c\u1ea7u ngay."), "action": _vn(r"T\u1ea1o 3 bi\u1ebfn th\u1ec3: use-case-led, benefit-led, urgency-led.")},
        {"element": "Message Body / Description", "signal": _vn(r"Body c\u1ee7a best notification: {desc}").format(desc=best_desc), "strength": _vn(r"Body t\u1ed1t support title b\u1eb1ng c\u00e1ch l\u00e0m r\u00f5 h\u00e0nh \u0111\u1ed9ng ti\u1ebfp theo."), "weakness": _vn(r"N\u1ebfu body ch\u1ec9 l\u1eb7p l\u1ea1i title, user kh\u00f4ng c\u00f3 th\u00eam l\u00fd do \u0111\u1ec3 click."), "insight": _vn(r"Body n\u00ean n\u1ed1i intent t\u1eeb title sang action: [Use case] + [Benefit] + [Action]."), "action": _vn(r"Rewrite body v\u1edbi m\u1ed9t action c\u1ee5 th\u1ec3 v\u00e0 m\u1ed9t benefit r\u00f5.")},
    ]
    if hourly:
        top = hourly[0]
        takeaways.append({"element": "Send Time / Hour", "signal": _vn(r"{hour:02d}:00 l\u00e0 best timing signal hi\u1ec7n t\u1ea1i v\u1edbi Click Rate {rate:.3f}%.").format(hour=top['hour'], rate=(top.get('ctr_pct') or 0)), "strength": _vn(r"Timing t\u1ed1t gi\u00fap c\u00f9ng m\u1ed9t message d\u1ec5 \u0111\u01b0\u1ee3c x\u1eed l\u00fd h\u01a1n."), "weakness": _vn(r"N\u1ebfu \u0111\u1ed5i c\u1ea3 copy v\u00e0 th\u1eddi gian c\u00f9ng l\u00fac, s\u1ebd kh\u00f4ng bi\u1ebft driver \u0111\u1ebfn t\u1eeb \u0111\u00e2u."), "insight": _vn(r"V\u1edbi bill/payment reminder, \u0111\u1ea7u gi\u1edd chi\u1ec1u c\u00f3 th\u1ec3 l\u00e0 action window h\u1ee3p l\u00fd, nh\u01b0ng c\u1ea7n retest c\u00f3 ki\u1ec3m so\u00e1t."), "action": _vn(r"Test c\u00f9ng title/body \u1edf {h1:02d}:00 / {h2:02d}:00 / {h3:02d}:00.").format(h1=max(top['hour']-1,0), h2=top['hour'], h3=min(top['hour']+1,23))})
    extra_data = [_vn(r"Segment \u0111\u1ec3 ph\u00e2n t\u00edch audience fit")]
    if not has_open_data or not has_payment_data:
        extra_data.insert(0, _vn(r"Conversion metric ph\u00f9 h\u1ee3p v\u1edbi campaign (v\u00ed d\u1ee5 NPU, MPU, Login, Payment ho\u1eb7c event ri\u00eang)"))
    takeaways.append({"element": _vn(r"G\u1ee3i \u00fd b\u1ed5 sung data"), "signal": _vn(r"D\u1eef li\u1ec7u hi\u1ec7n t\u1ea1i \u0111\u1ee7 \u0111\u1ec3 ph\u00e2n t\u00edch Click Rate, Title, Description v\u00e0 Send time."), "strength": _vn(r"Ph\u00e2n t\u00edch hi\u1ec7n t\u1ea1i d\u1ef1a tr\u00ean metric c\u00f3 s\u1eb5n trong file."), "weakness": _vn(r"Ch\u01b0a \u0111\u1ee7 \u0111\u1ec3 \u0111\u00e1nh gi\u00e1 full funnel n\u1ebfu thi\u1ebfu conversion event ph\u00f9 h\u1ee3p."), "insight": _vn(r"Ch\u1ec9 b\u1ed5 sung metric khi n\u00f3 ph\u1ee5c v\u1ee5 m\u1ee5c ti\u00eau ph\u00e2n t\u00edch. N\u1ebfu brief h\u1ecfi title/click/timing th\u00ec available data \u0111\u00e3 \u0111\u1ee7."), "action": "; ".join(extra_data) + "."})
    return takeaways


def _build_notification_recommendations(results, hourly, has_payment, has_open=False):
    recs = []
    if results:
        best = max(results, key=lambda r: (r.get("ctr_pct") or 0, r.get("sent_rate_pct") or 0))
        best_title = best.get("title") or best.get("entity") or "best notification"
        recs.append({"priority": _vn(r"Cao"), "learning": _vn(r"Title theo use case c\u1ee5 th\u1ec3 k\u00e9o Click Rate t\u1ed1t h\u01a1n title generic."), "action": _vn(r"T\u1ea1o 3 title m\u1edbi t\u1eeb pattern c\u1ee7a '{title}': use-case-led, benefit-led, urgency-led.").format(title=best_title), "owner": "CRM", "output": "3 notification variants ready for A/B test"})
    if hourly:
        top = hourly[0]
        recs.append({"priority": _vn(r"Cao"), "learning": _vn(r"{hour:02d}:00 l\u00e0 best timing signal hi\u1ec7n t\u1ea1i.").format(hour=top['hour']), "action": _vn(r"Test c\u00f9ng title/body \u1edf {h1:02d}:00, {h2:02d}:00, {h3:02d}:00 \u0111\u1ec3 isolate send-time impact.").format(h1=max(top['hour']-1,0), h2=top['hour'], h3=min(top['hour']+1,23)), "owner": "CRM / Lifecycle", "output": "Send-time A/B test result"})
    recs.append({"priority": _vn(r"Trung b\u00ecnh"), "learning": _vn(r"Notification l\u00e0 owned/free traffic n\u00ean CPA kh\u00f4ng ph\u1ea3i KPI ph\u00f9 h\u1ee3p."), "action": _vn(r"D\u00f9ng KPI funnel hi\u1ec7n c\u00f3: Sent/Success v\u00e0 Click Rate. B\u1ed5 sung conversion metric ph\u00f9 h\u1ee3p v\u1edbi campaign (NPU, MPU, Login, Payment...) n\u1ebfu mu\u1ed1n \u0111\u00e1nh gi\u00e1 s\u00e2u h\u01a1n."), "owner": "CRM / Data", "output": _vn(r"Notification KPI view kh\u00f4ng c\u00f3 CPA")})
    if not has_open or not has_payment:
        recs.append({"priority": _vn(r"Trung b\u00ecnh"), "learning": _vn(r"File hi\u1ec7n ch\u01b0a c\u00f3 \u0111\u1ee7 funnel event, nh\u01b0ng kh\u00f4ng ph\u1ee7 \u0111\u1ecbnh learning v\u1ec1 Click Rate."), "action": _vn(r"N\u1ebfu mu\u1ed1n \u0111\u00e1nh gi\u00e1 full funnel, b\u1ed5 sung conversion metric ph\u00f9 h\u1ee3p v\u1edbi campaign: NPU, MPU, Login, Payment ho\u1eb7c action event ri\u00eang."), "owner": "Data", "output": "Updated notification export schema"})
    def _rank(rec):
        p = str(rec.get("priority", "")).strip().lower()
        if "cao" in p and "nh" in p:
            return 0
        if "cao" in p:
            return 1
        if "trung" in p:
            return 2
        return 9

    return sorted(recs, key=_rank)


def _build_notification_warnings(title_col, desc_col, time_col, payment_col, has_images):
    warnings = [_vn(r"Notification l\u00e0 owned/free traffic n\u00ean CPA/CPI/currency \u0111\u01b0\u1ee3c \u1ea9n m\u1eb7c \u0111\u1ecbnh.")]
    if not title_col: warnings.append(_vn(r"Ch\u01b0a t\u00ecm th\u1ea5y c\u1ed9t Title. Insight v\u1ec1 click trigger s\u1ebd y\u1ebfu h\u01a1n."))
    if not desc_col: warnings.append(_vn(r"Ch\u01b0a t\u00ecm th\u1ea5y c\u1ed9t Description/message body. Agent ch\u01b0a \u0111\u00e1nh gi\u00e1 \u0111\u1ea7y \u0111\u1ee7 l\u00fd do user click sau khi \u0111\u1ecdc title."))
    if not time_col: warnings.append(_vn(r"Ch\u01b0a t\u00ecm th\u1ea5y c\u1ed9t Send time n\u00ean ch\u01b0a th\u1ec3 ph\u00e2n t\u00edch hi\u1ec7u qu\u1ea3 theo gi\u1edd."))
    if not payment_col: warnings.append(_vn(r"Ch\u01b0a c\u00f3 conversion event trong file. N\u1ebfu mu\u1ed1n \u0111\u00e1nh gi\u00e1 downstream quality, b\u1ed5 sung metric ph\u00f9 h\u1ee3p (NPU, MPU, Login, Payment...)."))
    if not has_images: warnings.append(_vn(r"Notification c\u00f3 th\u1ec3 c\u00f3 ho\u1eb7c kh\u00f4ng c\u00f3 banner. Agent \u01b0u ti\u00ean title, description, promotion trigger v\u00e0 send time; image l\u00e0 optional context."))
    return warnings


def _detect_analysis_mode(columns: list) -> dict:
    cols = [c.lower() for c in columns]
    modes = []
    if sum(1 for c in cols if any(s in c for s in ["impression", "click", "install", "cost", "creative", "ad_name"])) >= 3:
        modes.append("creative_performance")
    if (
        sum(1 for c in cols if any(s in c for s in ["notification", "noti_sent", "noti_open", "open_rate"])) >= 2
        or (
            any("title" in c for c in cols)
            and any("sent" in c for c in cols)
            and any("click" in c for c in cols)
        )
    ):
        modes.append("notification")
    if sum(1 for c in cols if any(s in c for s in ["install", "login", "payment", "revenue"])) >= 3:
        modes.append("funnel_performance")
    if any("hour" in c for c in cols):
        modes.append("hourly_performance")
    if sum(1 for c in cols if any(s in c for s in ["size", "inventory", "exchange", "placement"])) >= 2:
        modes.append("channel_placement")
    if sum(1 for c in cols if any(s in c for s in ["title", "description", "message", "cta"])) >= 2:
        modes.append("copy_message")
    return {"mode": modes[0] if modes else "creative_performance", "possible_modes": modes}


def _build_warnings(cfg, results, columns, has_images, all_channels) -> list:
    warnings = []
    benchmark = float(cfg.get("cpa_benchmark") or 0)

    if not all_channels:
        warnings.append(
            "ChÆ°a cÃ³ channel/platform nÃªn insight cÃ³ thá»ƒ bá»‹ chung chung. "
            "Moloco cáº§n Æ°u tiÃªn size/placement; TikTok cáº§n Æ°u tiÃªn hook/video retention; "
            "Notification cáº§n Æ°u tiÃªn title/open rate."
        )

    if len(all_channels) > 1:
        ch_str = ", ".join(all_channels)
        warnings.append(
            f"File cÃ³ nhiá»u channel ({ch_str}). Agent tÃ¡ch learning theo tá»«ng channel trÆ°á»›c, "
            "sau Ä‘Ã³ tá»•ng há»£p cross-channel learning."
        )

    if benchmark <= 0:
        warnings.append(
            "ChÆ°a cÃ³ benchmark/historical reference nÃªn káº¿t luáº­n chá»‰ lÃ  relative "
            "trong file upload, khÃ´ng pháº£i káº¿t luáº­n absolute."
        )

    if not has_images:
        warnings.append(
            "ChÆ°a Ä‘á»§ dá»¯ liá»‡u visual Ä‘á»ƒ káº¿t luáº­n CTA/mÃ u/font/text density. "
            "HÃ£y upload creative asset hoáº·c báº­t image vision."
        )

    valid = [r for r in results if r["actions"] > 0]
    if len(valid) < 5:
        warnings.append(
            f"Sample nhá» ({len(valid)} creative cÃ³ conversion). "
            "Káº¿t luáº­n cáº§n Ä‘Æ°á»£c xÃ¡c nháº­n láº¡i khi cÃ³ thÃªm data."
        )

    if len(valid) < 3:
        warnings.append(
            "Cáº¢NH BÃO: Dá»¯ liá»‡u khÃ´ng Ä‘á»§ Ä‘á»ƒ rÃºt káº¿t luáº­n Ä‘Ã¡ng tin cáº­y. "
            "Chá»‰ cÃ³ " + str(len(valid)) + " creative cÃ³ conversion â€” cáº§n tá»‘i thiá»ƒu 5 Ä‘á»ƒ so sÃ¡nh cÃ³ Ã½ nghÄ©a."
        )

    unique_channels = set(r["channel"] for r in valid if r["channel"])
    for ch in unique_channels:
        ch_items = [r for r in valid if r["channel"] == ch]
        if len(ch_items) < 2:
            warnings.append(
                f"Channel {ch}: chá»‰ cÃ³ {len(ch_items)} creative â€” khÃ´ng Ä‘á»§ Ä‘á»ƒ káº¿t luáº­n vá» channel-specific pattern."
            )

    unique_os = set(r["os"] for r in valid if r["os"])
    for os_name in unique_os:
        os_items = [r for r in valid if r["os"] == os_name]
        if len(os_items) < 2:
            warnings.append(
                f"OS {os_name}: chá»‰ cÃ³ {len(os_items)} creative â€” khÃ´ng Ä‘á»§ Ä‘á»ƒ káº¿t luáº­n OS-specific pattern."
            )

    return warnings


def _objective_weights(cfg: dict) -> dict:
    sc = cfg.get("scoring_config")
    if sc and sc.get("weights"):
        w = {"ctr": 0, "cvr": 0, "cpa": 0}
        for item in sc["weights"]:
            m = item.get("metric", "").lower()
            wt = int(item.get("weight", 0))
            if "ctr" in m and "click-to" not in m:
                w["ctr"] += wt
            elif any(k in m for k in ["cvr", "login rate", "payment rate", "open rate", "click rate", "click-to"]):
                w["cvr"] += wt
            elif any(k in m for k in ["cpa", "cpi", "cost", "roas"]):
                w["cpa"] += wt
            elif any(k in m for k in ["%sent", "success rate", "sent volume"]):
                w["cpa"] += wt
        return w
    objective = cfg.get("qs_objective", "balanced_ua")
    presets = {
        "creative_balanced": {"ctr": 30, "cvr": 30, "cpa": 40},
        "install_volume": {"ctr": 25, "cvr": 35, "cpa": 40},
        "conversion_quality": {"ctr": 15, "cvr": 45, "cpa": 40},
        "cost_efficiency": {"ctr": 15, "cvr": 25, "cpa": 60},
        "custom": {"ctr": int(cfg.get("qs_weight_ctr", 15)), "cvr": int(cfg.get("qs_weight_cvr", 45)), "cpa": int(cfg.get("qs_weight_cpa", 40))},
    }
    return presets.get(objective, presets["conversion_quality"]).copy()


def _primary_metric_kind(metric: str) -> str:
    m = str(metric or "").lower()
    if any(k in m for k in ["qualified_lead", "qualified lead", "mql", "sql"]):
        return "qualified_lead"
    if any(k in m for k in ["lead", "form_submit", "signup", "sign_up", "register"]):
        return "lead"
    if "install" in m:
        return "install"
    if "login_success" in m or m in ("login", "logins", "login success", "success login"):
        return "login"
    if any(k in m for k in ["payment_success", "first_payment", "purchase_success"]):
        return "payment"
    return "action"


def _rate_metric_label(metric: str) -> str:
    kind = _primary_metric_kind(metric)
    if kind == "install":
        return "Install Rate"
    if kind == "login":
        return "Login Rate"
    if kind in ("lead", "qualified_lead"):
        return "Action Rate"
    return "Action Rate"


def _cost_metric_label(metric: str) -> str:
    kind = _primary_metric_kind(metric)
    if kind == "install":
        return "CPI"
    if kind == "login":
        return "Cost per Login"
    if kind == "lead":
        return "Cost per Lead"
    if kind == "qualified_lead":
        return "Cost per Qualified Lead"
    return "Cost per Action"


def _primary_metric_formula(metric: str) -> str:
    kind = _primary_metric_kind(metric)
    if kind == "install":
        return "Install Rate = Install / Click"
    if kind == "login":
        return "Login Rate = Login / Click"
    if kind in ("lead", "qualified_lead"):
        return "Action Rate = selected Primary Metric(s) / Click"
    return "Action Rate = selected Primary Metric(s) / Click"


def _notification_weights(cfg: dict) -> dict:
    sc = cfg.get("scoring_config")
    if sc and sc.get("weights"):
        w = {}
        for item in sc["weights"]:
            m = item.get("metric", "").lower()
            wt = int(item.get("weight", 0))
            if any(k in m for k in ["%sent", "success rate", "sent volume"]):
                w["sent_rate"] = w.get("sent_rate", 0) + wt
            elif any(k in m for k in ["open rate"]):
                w["open_rate"] = w.get("open_rate", 0) + wt
            elif "click-to" in m:
                w["click_to_payment"] = w.get("click_to_payment", 0) + wt
            elif "payment rate" in m:
                w["payment_rate"] = w.get("payment_rate", 0) + wt
            elif "click rate" in m:
                w["click_rate"] = w.get("click_rate", 0) + wt
            elif "ctr" in m:
                w["ctr"] = w.get("ctr", 0) + wt
        return w or {"sent_rate": 20, "click_rate": 80}
    return {"sent_rate": 20, "click_rate": 40, "click_to_payment": 40}


def _rank_and_decide(results, benchmark, weights=None):
    if weights is None:
        weights = {"ctr": 30, "cvr": 30, "cpa": 40}
    total = weights["ctr"] + weights["cvr"] + weights["cpa"]
    if total == 0: total = 100
    w_ctr, w_cvr, w_cpa = weights["ctr"]/total, weights["cvr"]/total, weights["cpa"]/total

    valid = [r for r in results if r["actions"] > 0]
    zero_action = [r for r in results if r["actions"] == 0]

    if not valid:
        for r in results:
            r["quality_score"], r["decision"], r["pattern"] = 0, "PAUSE", "no_data"
        return

    ctrs = sorted([r["ctr_pct"] for r in valid])
    cvrs = sorted([r["cvr_pct"] for r in valid])
    cpas = sorted([r["cpa_vnd"] for r in valid if r["cpa_vnd"] > 0])
    max_ctr = max(ctrs) if ctrs else 1
    max_cvr = max(cvrs) if cvrs else 1
    median_ctr = ctrs[len(ctrs)//2] if ctrs else 1
    median_cvr = cvrs[len(cvrs)//2] if cvrs else 1
    median_cpa = cpas[len(cpas)//2] if cpas else 1

    for r in valid:
        ctr_score = min(r["ctr_pct"] / max(max_ctr, 0.01), 1.0) * 10
        cvr_score = min(r["cvr_pct"] / max(max_cvr, 0.01), 1.0) * 10
        if benchmark > 0 and r["cpa_vnd"] > 0:
            cpa_score = max(0, 10 - (r["cpa_vnd"]/benchmark - 1) * 10)
        elif r["cpa_vnd"] > 0 and median_cpa > 0:
            cpa_score = max(0, 10 - (r["cpa_vnd"]/median_cpa - 1) * 5)
        else:
            cpa_score = 0
        qs = ctr_score * w_ctr + cvr_score * w_cvr + cpa_score * w_cpa
        r["quality_score"] = round(qs, 1)

        ctr_good = r["ctr_pct"] >= median_ctr
        cvr_good = r["cvr_pct"] >= median_cvr
        cpa_ok = (benchmark > 0 and r["cpa_vnd"] <= benchmark * 1.3) or (benchmark == 0 and r["cpa_vnd"] > 0 and r["cpa_vnd"] <= median_cpa * 1.3)

        if ctr_good and cvr_good and cpa_ok:
            r["decision"], r["pattern"] = "SCALE", "strong_all"
        elif not ctr_good and cvr_good:
            r["decision"], r["pattern"] = "ITERATE HOOK", "low_ctr_high_cvr"
        elif ctr_good and not cvr_good:
            r["decision"], r["pattern"] = "INVESTIGATE FUNNEL", "high_ctr_low_cvr"
        elif not ctr_good and not cvr_good and r["quality_score"] >= 4.0:
            r["decision"], r["pattern"] = "MAINTAIN", "mixed_signals"
        else:
            r["decision"], r["pattern"] = "PAUSE", "weak_all"

    for r in zero_action:
        r["quality_score"], r["decision"], r["pattern"] = 0, "PAUSE", "no_conversions"


def _build_audience_context(cfg):
    product = cfg.get("product", "App")
    goal = cfg.get("goal", "ua")
    age_min, age_max = cfg.get("age_min", "18"), cfg.get("age_max", "35")
    location = cfg.get("location", "Vietnam")
    segment = cfg.get("segment", "")
    goal_labels = {"ua": "User Acquisition", "retargeting": "Retargeting", "other": "Other"}
    goal_label = goal_labels.get(goal, goal)
    context_notes = []
    if goal == "ua":
        context_notes.append(f"Vá»›i nhÃ³m {age_min}-{age_max} {location} UA, creative cáº§n message Ä‘á»c Ä‘Æ°á»£c ngay trÃªn mobile vÃ  offer pháº£i rÃµ rÃ ng tá»« giÃ¢y Ä‘áº§u.")
    elif goal == "retargeting":
        context_notes.append("Retargeting audience Ä‘Ã£ biáº¿t sáº£n pháº©m. Æ¯u tiÃªn offer cá»¥ thá»ƒ, reminder hoáº·c feature má»›i.")
    elif goal == "other":
        context_notes.append("Other dùng cho lead, qualified lead hoặc event đặc thù. Primary Metric(s) quyết định action skill và post-click factors.")
    segment_note = f"Segment: {segment}." if segment else f"Segment chÆ°a Ä‘Æ°á»£c nháº­p. Insight Ä‘ang giáº£ Ä‘á»‹nh nhÃ³m {age_min}-{age_max} {location} {goal_label} rá»™ng."
    return {"product": product, "goal": goal_label, "age_range": f"{age_min}-{age_max}", "location": location, "segment": segment or "Not specified", "context_notes": context_notes, "segment_note": segment_note}


# â”€â”€ v6: Variance-First Analysis â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _extract_concept_tokens(entity: str) -> str:
    uc_keywords = {"grab", "billing", "scan", "scanqr", "game", "insurance", "data", "voucher", "discount", "topup", "transfer", "electric", "water"}
    promo_keywords = {"promo", "nonpromo", "nonpro"}
    ignore = {"zpi", "aeo", "login", "npu", "android", "ios", "gg", "ua", "tiktok", "one", "fs", "moloco", "mass", "nonpromo", "nonpro", "promo"}
    tokens = entity.lower().replace("-", " ").replace("_", " ").split()
    concept = []
    for t in tokens:
        if t in ignore or t.isdigit() or (len(t) == 6 and t.isdigit()):
            continue
        if t in uc_keywords or t in promo_keywords or any(c.isdigit() for c in t):
            concept.append(t)
    return " ".join(sorted(concept)) if concept else entity.lower()[:20]


def _detect_concept_groups(results) -> dict:
    groups = {}
    for r in results:
        key = _extract_concept_tokens(r["entity"])
        groups.setdefault(key, []).append(r)
    return {k: v for k, v in groups.items() if len(v) >= 2}


def _check_same_concept_variance(concept_groups: dict, ccy: str) -> list:
    checks = []
    for concept, items in concept_groups.items():
        ctrs = [r["ctr_pct"] for r in items]
        cvrs = [r["cvr_pct"] for r in items]
        cpas = [r["cpa_vnd"] for r in items if r["cpa_vnd"] > 0]
        if len(ctrs) < 2:
            continue
        ctr_spread = max(ctrs) - min(ctrs)
        cvr_spread = max(cvrs) - min(cvrs) if len(cvrs) >= 2 else 0
        cpa_spread_ratio = max(cpas) / min(cpas) if cpas and min(cpas) > 0 else 1

        if ctr_spread < 0.3 and cvr_spread < 1.0 and cpa_spread_ratio < 1.5:
            continue

        entities = [r["entity"][:40] for r in items]
        diff_dims = []
        oses = set(r["os"] for r in items if r["os"])
        channels = set(r["channel"] for r in items if r["channel"])
        if len(oses) > 1:
            diff_dims.append(f"OS ({', '.join(oses)})")
        if len(channels) > 1:
            diff_dims.append(f"Channel ({', '.join(channels)})")

        best_item = max(items, key=lambda r: r["quality_score"])
        worst_item = min(items, key=lambda r: r["quality_score"])

        check = {
            "concept": concept,
            "count": len(items),
            "entities": entities,
            "ctr_spread_pp": round(ctr_spread, 2),
            "cvr_spread_pp": round(cvr_spread, 2),
            "cpa_spread_ratio": round(cpa_spread_ratio, 2),
            "different_dimensions": diff_dims if diff_dims else ["ChÆ°a xÃ¡c Ä‘á»‹nh â€” cáº§n breakdown thÃªm (size, placement, date, audience)"],
            "best": {"entity": best_item["entity"][:40], "ctr": best_item["ctr_pct"], "cvr": best_item["cvr_pct"], "cpa": best_item["cpa_vnd"]},
            "worst": {"entity": worst_item["entity"][:40], "ctr": worst_item["ctr_pct"], "cvr": worst_item["cvr_pct"], "cpa": worst_item["cpa_vnd"]},
        }

        if ctr_spread >= 0.5:
            check["warning"] = (
                f"CÃ¹ng concept \"{concept}\" nhÆ°ng CTR chÃªnh {ctr_spread:.1f}pp. "
                f"TrÆ°á»›c khi káº¿t luáº­n CTA/hook yáº¿u, hÃ£y kiá»ƒm tra dimension khÃ¡c: "
                f"{', '.join(diff_dims) if diff_dims else 'size, placement, date, audience'}."
            )
        if cvr_spread >= 2.0:
            check["warning"] = check.get("warning", "") + (
                f" CVR chÃªnh {cvr_spread:.1f}pp trong cÃ¹ng concept â€” "
                "cÃ³ thá»ƒ do post-click flow khÃ¡c nhau theo OS/channel."
            )
        if cpa_spread_ratio >= 2.0:
            check["warning"] = check.get("warning", "") + (
                f" CPA chÃªnh {cpa_spread_ratio:.1f}x â€” "
                "delivery dimension (size, placement, campaign type) cÃ³ thá»ƒ lÃ  driver chÃ­nh."
            )

        checks.append(check)
    return checks


def _get_dimension_priority(all_channels: list, columns: list) -> list:
    priorities = []
    ch_lower = [c.lower() for c in all_channels]

    if any(c in ("moloco", "dsp", "in-app display", "other network") for c in ch_lower):
        priorities.append({
            "channel": "Moloco / Programmatic",
            "order": ["Size / Placement", "Offer Visibility", "CTA Visibility", "Text Density", "Mobile Readability", "Concept / Use Case"],
            "reason": "Moloco lÃ  in-app banner inventory â€” size áº£nh hÆ°á»Ÿng trá»±c tiáº¿p Ä‘áº¿n CTR/CVR. Pháº£i kiá»ƒm tra size trÆ°á»›c khi káº¿t luáº­n concept tháº¯ng/thua.",
        })
    if any(c in ("tiktok",) for c in ch_lower):
        priorities.append({
            "channel": "TikTok",
            "order": ["Hook / First 3s", "Video Pacing", "Sound/Music", "Offer Framing", "CTA", "Concept / Use Case"],
            "reason": "TikTok lÃ  short-form video feed â€” hook vÃ  3 giÃ¢y Ä‘áº§u quyáº¿t Ä‘á»‹nh CTR. Concept chá»‰ phÃ¡t huy khi hook Ä‘á»§ máº¡nh.",
        })
    if any(c in ("google", "google uac") for c in ch_lower):
        priorities.append({
            "channel": "Google / UAC",
            "order": ["Asset Group / Concept", "Headline", "Description", "Image/Video Quality", "CTA"],
            "reason": "Google UAC auto-optimizes placement â€” focus vÃ o asset quality vÃ  message clarity.",
        })
    if any(c in ("facebook", "meta") for c in ch_lower):
        priorities.append({
            "channel": "Meta / Facebook",
            "order": ["Hook / Thumbnail", "Offer Framing", "Ad Copy", "CTA", "Audience Fit"],
            "reason": "Meta feed cáº¡nh tranh attention vá»›i organic content â€” hook + offer pháº£i rÃµ rÃ ng.",
        })

    has_noti = any("noti" in c or "notification" in c or "push" in c for c in [col.lower() for col in columns])
    if has_noti:
        priorities.append({
            "channel": "Notification / Push",
            "order": ["Title", "Open Rate", "Message Body", "Send Time", "Deep Link"],
            "reason": "Notification phá»¥ thuá»™c title â€” open rate lÃ  KPI Ä‘áº§u tiÃªn cáº§n check.",
        })

    if not priorities:
        priorities.append({
            "channel": "General",
            "order": ["Delivery Dimension (size, placement, OS)", "Offer / Promotion", "CTA", "Main Message", "Visual Execution"],
            "reason": "ChÆ°a xÃ¡c Ä‘á»‹nh channel cá»¥ thá»ƒ â€” Æ°u tiÃªn delivery dimension trÆ°á»›c creative element.",
        })

    return priorities


def _build_creative_takeaways(results, cfg, all_channels, ccy="Ä‘", has_variance=False, dim_priority=None) -> list:
    valid = [r for r in results if r["actions"] > 0]
    if not valid:
        return []

    product = cfg.get("product", "App")
    has_moloco = any(ch.lower() in ("moloco", "in-app display", "dsp") for ch in all_channels)
    has_srn = any(ch.lower() in ("tiktok", "meta", "facebook", "google", "google uac") for ch in all_channels)

    takeaways = []
    ctrs = [r["ctr_pct"] for r in valid]
    cvrs = [r["cvr_pct"] for r in valid]
    cpas = [r["cpa_vnd"] for r in valid if r["cpa_vnd"] > 0]
    median_ctr = sorted(ctrs)[len(ctrs)//2] if ctrs else 0
    median_cvr = sorted(cvrs)[len(cvrs)//2] if cvrs else 0
    median_cpa = sorted(cpas)[len(cpas)//2] if cpas else 0
    best = max(valid, key=lambda r: r["quality_score"])
    worst = min(valid, key=lambda r: r["quality_score"])
    action_skill = cfg.get("_action_skill") or {}
    if action_skill:
        factors = ", ".join(action_skill.get("post_click_factors", [])[:4])
        tests = "; ".join(action_skill.get("tests", [])[:3])
        takeaways.append({
            "element": "Primary Metric / Action Skill",
            "signal": f"{action_skill.get('action_label', 'Selected Action')} dùng {action_skill.get('rate_label', 'Action Rate')} để đọc post-click action.",
            "strength": action_skill.get("goal_note", ""),
            "weakness": action_skill.get("segment_note", ""),
            "insight": f"Impact factors khác nhau theo Primary Metric(s): {factors}. Vì vậy không nên dùng cùng một logic cho install, login, payment hay lead.",
            "action": f"Ưu tiên test theo action skill: {tests}.",
        })

    # v6: Variance-aware preamble â€” if same-concept variance detected, flag it BEFORE element analysis
    if has_variance:
        takeaways.append({
            "element": "Cáº£nh bÃ¡o: Variance trong cÃ¹ng concept",
            "signal": "PhÃ¡t hiá»‡n creative cÃ¹ng concept/promo nhÆ°ng performance khÃ¡c nhau Ä‘Ã¡ng ká»ƒ. Delivery dimension (OS, size, placement, campaign type) cÃ³ thá»ƒ lÃ  driver chÃ­nh â€” KHÃ”NG nÃªn káº¿t luáº­n CTA/hook yáº¿u trÆ°á»›c khi kiá»ƒm tra.",
            "strength": "CÃ³ Ä‘á»§ data Ä‘á»ƒ phÃ¢n tÃ­ch variance â€” Ä‘Ã¢y lÃ  cÆ¡ há»™i tÃ¬m Ä‘Ãºng driver thay vÃ¬ Ä‘oÃ¡n.",
            "weakness": "Náº¿u bá» qua variance check, insight sáº½ sai hÆ°á»›ng: thay Ä‘á»•i creative element trong khi váº¥n Ä‘á» náº±m á»Ÿ delivery.",
            "insight": "PhÃ¢n tÃ­ch Ä‘Ãºng thá»© tá»±: variance check â†’ delivery dimension â†’ rá»“i má»›i creative element. Xem chi tiáº¿t á»Ÿ má»¥c 'Kiá»ƒm tra Variance cÃ¹ng Concept' bÃªn dÆ°á»›i.",
            "action": "Xem variance_check Ä‘á»ƒ hiá»ƒu dimension nÃ o gÃ¢y chÃªnh lá»‡ch trÆ°á»›c khi tá»‘i Æ°u creative.",
        })


    # 1. Offer / Promotion
    promo_entities = [r for r in valid if _has_promo_signal(r["entity"])]
    non_promo = [r for r in valid if r not in promo_entities]
    if promo_entities and non_promo:
        avg_cvr_p = sum(r["cvr_pct"] for r in promo_entities) / len(promo_entities)
        avg_cvr_np = sum(r["cvr_pct"] for r in non_promo) / len(non_promo)
        ratio = avg_cvr_p / max(avg_cvr_np, 0.01)
        if ratio > 1.2:
            takeaways.append({
                "element": "Offer / Promotion",
                "signal": f"Creative cÃ³ promotion signal Ä‘áº¡t Avg CVR {avg_cvr_p:.1f}%, cao hÆ¡n {ratio:.1f}x so vá»›i nhÃ³m non-promo ({avg_cvr_np:.1f}%).",
                "strength": "Offer cÃ³ kháº£ nÄƒng lá»c Ä‘Ãºng user cÃ³ nhu cáº§u. ÄÃ¢y lÃ  tÃ­n hiá»‡u tá»‘t vá» conversion quality.",
                "weakness": "Náº¿u CTR váº«n tháº¥p, offer cÃ³ thá»ƒ chÆ°a Ä‘á»§ visible hoáº·c packaging chÆ°a Ä‘á»§ máº¡nh Ä‘á»ƒ thumb-stop.",
                "insight": f"Vá»›i {product}, Æ°u Ä‘Ã£i cá»¥ thá»ƒ (sá»‘ tiá»n, use case) táº¡o qualified intent tá»‘t hÆ¡n promise chung chung. NhÆ°ng offer cáº§n Ä‘Æ°á»£c Ä‘Ã³ng gÃ³i báº±ng visual máº¡nh Ä‘á»ƒ táº¡o cáº£ click volume.",
                "action": f"Test 3 offer framing:\n1. \"Táº£i {product} nháº­n 15K\"\n2. \"Thanh toÃ¡n TikTok Shop báº±ng {product} giáº£m 15K\"\n3. \"Má»Ÿ {product} Ä‘á»ƒ nháº­n voucher â€” chá»‰ hÃ´m nay\"",
            })
        else:
            takeaways.append({
                "element": "Offer / Promotion",
                "signal": f"CÃ³ promotion trong naming nhÆ°ng CVR chÆ°a tá»‘t hÆ¡n rÃµ rá»‡t (Promo {avg_cvr_p:.1f}% vs Non-promo {avg_cvr_np:.1f}%).",
                "strength": "Offer Ä‘Ã£ xuáº¥t hiá»‡n trong creative.",
                "weakness": "Offer chÆ°a Ä‘á»§ specific, visible hoáº·c motivating Ä‘á»ƒ táº¡o conversion gap cÃ³ Ã½ nghÄ©a.",
                "insight": "Offer tá»“n táº¡i nhÆ°ng execution chÆ°a lÃ m nÃ³ ná»•i báº­t. CÃ³ thá»ƒ do text quÃ¡ nhá», vá»‹ trÃ­ khÃ´ng tá»‘t, hoáº·c framing chÆ°a gáº¯n vá»›i use case cá»¥ thá»ƒ.",
                "action": f"Test offer vá»›i framing cá»¥ thá»ƒ hÆ¡n: sá»‘ tiá»n + use case + deadline.\nVD: \"Giáº£m 50K khi thanh toÃ¡n Ä‘iá»‡n nÆ°á»›c báº±ng {product}\"",
            })

    # 2. CTA
    best_ctr_r = max(valid, key=lambda r: r["ctr_pct"])
    worst_ctr_r = min(valid, key=lambda r: r["ctr_pct"])
    ctr_gap = best_ctr_r["ctr_pct"] - worst_ctr_r["ctr_pct"]
    if ctr_gap > 0.5:
        high_ctr_low_cvr = [r for r in valid if r["ctr_pct"] > median_ctr and r["cvr_pct"] < median_cvr]
        takeaways.append({
            "element": "CTA",
            "signal": f"CTR spread = {best_ctr_r['ctr_pct']:.1f}% (best) vs {worst_ctr_r['ctr_pct']:.1f}% (worst). Gap = {ctr_gap:.1f}pp.",
            "strength": "Má»™t sá»‘ CTA/hook Ä‘á»§ táº¡o click, cho tháº¥y cÃ³ room Ä‘á»ƒ tá»‘i Æ°u.",
            "weakness": f"{'NhÃ³m CTR cao láº¡i cÃ³ CVR tháº¥p â€” CTA chÆ°a qualify rÃµ action sau click.' if high_ctr_low_cvr else 'CTA cá»§a nhÃ³m worst chÆ°a Ä‘á»§ rÃµ rÃ ng hoáº·c chÆ°a gáº¯n vá»›i benefit cá»¥ thá»ƒ.'}",
            "insight": f"Vá»›i user chÆ°a tá»«ng táº£i {product}, CTA khÃ´ng nÃªn chá»‰ nÃ³i \"Nháº­n ngay\". CTA pháº£i gáº¯n offer vá»›i hÃ nh Ä‘á»™ng cá»¥ thá»ƒ trong app Ä‘á»ƒ qualify intent.",
            "action": f"Test 3 CTA:\n1. \"Táº£i {product} nháº­n 15K\"\n2. \"Thanh toÃ¡n TikTok Shop báº±ng {product}\"\n3. \"Má»Ÿ {product} Ä‘á»ƒ nháº­n voucher\"",
        })

    # 3. Main Message
    high_cvr = [r for r in valid if r["cvr_pct"] >= median_cvr * 1.3]
    low_cvr = [r for r in valid if r["cvr_pct"] < median_cvr * 0.7]
    if high_cvr and low_cvr:
        takeaways.append({
            "element": "Main Message",
            "signal": f"{len(high_cvr)} creative cÃ³ CVR cao (â‰¥ {median_cvr*1.3:.1f}%) vs {len(low_cvr)} creative CVR tháº¥p (â‰¤ {median_cvr*0.7:.1f}%).",
            "strength": "NhÃ³m high-CVR cho tháº¥y message cÃ³ thá»ƒ qualify user Ä‘Ãºng cÃ¡ch.",
            "weakness": "NhÃ³m low-CVR cho tháº¥y message cÃ³ thá»ƒ quÃ¡ rá»™ng hoáº·c promise khÃ´ng align vá»›i post-click experience.",
            "insight": "Message rÃµ benefit + action cá»¥ thá»ƒ thÆ°á»ng convert tá»‘t hÆ¡n message chung chung. Sá»± chÃªnh lá»‡ch CVR giá»¯a 2 nhÃ³m cho tháº¥y message quality lÃ  má»™t driver tháº­t.",
            "action": "Phân tích message/naming của nhóm high-CVR. Lấy pattern (offer cụ thể? use case rõ?) và test 2-3 variant với message structure tương tự nhưng đổi visual/CTA.",
        })

    # 4. Hook / First Frame â€” CHá»ˆ cho SRN, KHÃ”NG cho Moloco static
    if has_srn:
        iterate_hooks = [r for r in valid if r["pattern"] == "low_ctr_high_cvr" and _is_srn_channel(r["channel"])]
        investigate_funnels = [r for r in valid if r["pattern"] == "high_ctr_low_cvr" and _is_srn_channel(r["channel"])]
        if iterate_hooks:
            avg_ctr = sum(r["ctr_pct"] for r in iterate_hooks) / len(iterate_hooks)
            avg_cvr = sum(r["cvr_pct"] for r in iterate_hooks) / len(iterate_hooks)
            takeaways.append({
                "element": "Hook / First Frame",
                "signal": f"{len(iterate_hooks)} creative (SRN) convert tá»‘t nhÆ°ng thiáº¿u click volume (Avg CTR {avg_ctr:.1f}%, CVR {avg_cvr:.1f}%).",
                "strength": "Core offer/message cÃ³ giÃ¡ trá»‹ â€” user nÃ o click vÃ o Ä‘á»u cÃ³ intent tá»‘t.",
                "weakness": "First frame/visual packaging chÆ°a Ä‘á»§ máº¡nh Ä‘á»ƒ dá»«ng scroll vÃ  táº¡o volume trong social feed.",
                "insight": "ÄÃ¢y lÃ  dáº¡ng \"qualified but not scalable\" â€” creative khÃ´ng nÃªn bá»‹ pause vÃ¬ CVR tá»‘t, nhÆ°ng cÅ©ng khÃ´ng nÃªn scale nguyÃªn báº£n vÃ¬ thiáº¿u attention.",
                "action": "Giá»¯ message. Rebuild first frame:\n1. Offer-dominant: Æ°u Ä‘Ã£i lá»›n, ná»•i báº­t, contrast cao\n2. Human-context: ngÆ°á»i dÃ¹ng Ä‘ang checkout/nháº­n voucher\n3. Product-screenshot: mÃ n hÃ¬nh app vá»›i offer overlay",
            })
        if investigate_funnels:
            avg_ctr = sum(r["ctr_pct"] for r in investigate_funnels) / len(investigate_funnels)
            avg_cvr = sum(r["cvr_pct"] for r in investigate_funnels) / len(investigate_funnels)
            takeaways.append({
                "element": "Hook / First Frame",
                "signal": f"{len(investigate_funnels)} creative (SRN) kÃ©o click nhÆ°ng khÃ´ng convert (Avg CTR {avg_ctr:.1f}%, CVR {avg_cvr:.1f}%).",
                "strength": "Hook/visual Ä‘á»§ táº¡o attention vÃ  click.",
                "weakness": "Click khÃ´ng chuyá»ƒn thÃ nh action â€” cÃ³ thá»ƒ lÃ  curiosity click hoáº·c mismatch giá»¯a ad promise vÃ  post-click experience.",
                "insight": "Vá»›i UA, creative cáº§n vá»«a kÃ©o attention vá»«a qualify Ä‘Ãºng intent install/login/payment. Hook quÃ¡ rá»™ng sáº½ táº¡o traffic khÃ´ng cÃ³ giÃ¡ trá»‹.",
                "action": "LÃ m promise cá»¥ thá»ƒ hÆ¡n:\n- NÃ³i rÃµ user nháº­n gÃ¬ sau khi táº£i app\n- Äiá»u kiá»‡n gÃ¬ (miá»…n phÃ­? giá»›i háº¡n thá»i gian?)\n- HÃ nh Ä‘á»™ng cá»¥ thá»ƒ gÃ¬ trong app",
            })

    # 5. Moloco-specific: Size/Ratio, Offer visibility, CTA visibility, Mobile readability
    if has_moloco:
        moloco_results = [r for r in valid if r["channel"].lower() == "moloco" or "moloco" in r["entity"].lower()]
        if moloco_results:
            # Channel context
            takeaways.append({
                "element": "Channel Fit (Moloco)",
                "signal": f"PhÃ¡t hiá»‡n {len(moloco_results)} creative trÃªn Moloco â€” programmatic in-app banner inventory.",
                "strength": "Moloco cho phÃ©p reach lá»›n qua in-app placements Ä‘a dáº¡ng.",
                "weakness": "KhÃ¡c vá»›i social feed (TikTok/Meta), Moloco creative cáº§n tá»‘i Æ°u cho small placements, fast impression, vÃ  mobile readability. Hook video kiá»ƒu TikTok khÃ´ng phÃ¹ há»£p.",
                "insight": "VÃ¬ Ä‘Ã¢y lÃ  Moloco / in-app banner inventory, phÃ¢n tÃ­ch cáº§n Æ°u tiÃªn size, placement, mobile readability, offer visibility vÃ  CTA visibility. KhÃ´ng nÃªn dÃ¹ng quÃ¡ nhiá»u video hook logic.",
                "action": "Æ¯u tiÃªn phÃ¢n tÃ­ch theo: Creative Size â†’ Offer Visibility â†’ CTA Visibility â†’ Text Density â†’ Mobile Readability.",
            })
            # Size/Ratio
            takeaways.append({
                "element": "Creative Size / Ratio",
                "signal": "Moloco yÃªu cáº§u nhiá»u size (320x480, 300x250, 728x90...) cho má»—i placement.",
                "strength": "Má»™t sá»‘ size cÃ³ thá»ƒ phÃ¹ há»£p inventory hÆ¡n vÃ  táº¡o CTR tá»‘t hÆ¡n.",
                "weakness": "Náº¿u khÃ´ng tÃ¡ch theo size, agent cÃ³ thá»ƒ káº¿t luáº­n sai ráº±ng concept tháº¯ng/thua, trong khi driver tháº­t lÃ  size/placement.",
                "insight": "Vá»›i Moloco, size lÃ  má»™t impact dimension quan trá»ng. Cáº§n phÃ¢n tÃ­ch size trÆ°á»›c khi káº¿t luáº­n vá» hook/CTA.",
                "action": "Breakdown theo size:\n- 320x50 (banner)\n- 320x480 (interstitial)\n- 300x250 (medium rectangle)\n- 728x90 (leaderboard)\nSo sÃ¡nh CTR, CVR, CPA theo tá»«ng size rá»“i má»›i chá»n concept Ä‘á»ƒ nhÃ¢n báº£n.",
            })
            # Text Density for Moloco
            takeaways.append({
                "element": "Text Density / Readability",
                "signal": "Moloco lÃ  in-app banner â€” nhiá»u size nhá» nhÆ° 320x50 hoáº·c 300x250.",
                "strength": "Banner cÃ³ thá»ƒ truyá»n táº£i offer nhanh náº¿u message Ä‘Æ¡n giáº£n.",
                "weakness": "Náº¿u quÃ¡ nhiá»u text phá»¥, user khÃ´ng Ä‘á»c ká»‹p trong mobile placement nhá».",
                "insight": "Vá»›i Moloco, text density áº£nh hÆ°á»Ÿng trá»±c tiáº¿p Ä‘áº¿n CTR vÃ¬ user chá»‰ cÃ³ vÃ i giÃ¢y nhÃ¬n banner.",
                "action": "Ãp dá»¥ng rule:\n- 1 main message\n- 1 offer chÃ­nh\n- 1 CTA\n- Logo/brand Ä‘á»§ rÃµ\n- Bá» text phá»¥ náº¿u khÃ´ng giÃºp user hiá»ƒu offer nhanh hÆ¡n",
            })

    # 6. SRN Channel Fit
    if has_srn and not has_moloco:
        srn_channels = [ch for ch in all_channels if _is_srn_channel(ch)]
        if "TikTok" in srn_channels or "tiktok" in [c.lower() for c in srn_channels]:
            takeaways.append({
                "element": "Channel Fit (TikTok)",
                "signal": "TikTok lÃ  short-form video feed â€” creative cáº§n thumb-stop trong 1-2 giÃ¢y Ä‘áº§u.",
                "strength": "TikTok cho phÃ©p creative phong phÃº: UGC, sound, motion, storytelling.",
                "weakness": "Náº¿u creative quÃ¡ giá»‘ng banner hoáº·c khÃ´ng cÃ³ hook máº¡nh, sáº½ bá»‹ skip ngay.",
                "insight": "Hook/first frame lÃ  yáº¿u tá»‘ quan trá»ng nháº¥t. Creative pháº£i cáº¡nh tranh vá»›i organic content trong feed.",
                "action": "Test hook styles:\n1. Offer-first: Æ°u Ä‘Ã£i ngay giÃ¢y Ä‘áº§u\n2. Problem-first: pain point rá»“i solution\n3. Testimonial-first: ngÆ°á»i dÃ¹ng tháº­t\n4. Visual-shock: unexpected visual",
            })

    # 7. Use Case Clarity
    uc_keywords = ["grab", "billing", "scan", "game", "insurance", "data", "voucher", "discount", "topup", "transfer"]
    uc_entities = [r for r in valid if any(kw in r["entity"].lower() for kw in uc_keywords)]
    if uc_entities:
        best_uc = max(uc_entities, key=lambda r: r["cvr_pct"])
        takeaways.append({
            "element": "Use Case Clarity",
            "signal": f"CÃ³ {len(uc_entities)} creative cÃ³ use case rÃµ trong naming. Best: {best_uc['entity'][:30]} (CVR {best_uc['cvr_pct']:.1f}%).",
            "strength": "Use case cá»¥ thá»ƒ giÃºp user hÃ¬nh dung giÃ¡ trá»‹ ngay láº­p tá»©c.",
            "weakness": "Náº¿u use case khÃ´ng phá»• biáº¿n hoáº·c quÃ¡ niched, cÃ³ thá»ƒ giá»›i háº¡n reach.",
            "insight": f"Creative cÃ³ use case rÃµ thÆ°á»ng convert tá»‘t hÆ¡n creative generic. Má»—i use case nÃªn lÃ  1 creative concept riÃªng.",
            "action": f"Scale use case tá»‘t nháº¥t vÃ  test thÃªm:\n- Thanh toÃ¡n Ä‘iá»‡n/nÆ°á»›c\n- Náº¡p Ä‘iá»‡n thoáº¡i\n- Chuyá»ƒn tiá»n\n- Mua sáº¯m online\nMá»—i use case = 1 creative concept riÃªng cho {product}.",
        })

    # 8. Audience Fit
    segment = cfg.get("segment", "")
    if segment:
        age_range = f"{cfg.get('age_min', '18')}-{cfg.get('age_max', '35')}"
        takeaways.append({
            "element": "Audience Fit",
            "signal": f"Target: {segment}, {age_range}, {cfg.get('location', 'Vietnam')}.",
            "strength": f"CÃ³ segment rÃµ rÃ ng giÃºp creative cÃ³ thá»ƒ personalize messaging.",
            "weakness": "ChÆ°a kiá»ƒm tra Ä‘Æ°á»£c creative cÃ³ thá»±c sá»± resonate vá»›i segment nÃ y hay khÃ´ng (cáº§n A/B test).",
            "insight": f"Creative cần phù hợp với ngôn ngữ, context và nhu cầu của segment đó. Generic message sẽ không tạo được connection.",
            "action": f"Test creative nói trực tiếp đến {segment}:\n- Dùng scenario của họ\n- Ngôn ngữ của họ\n- Nhu cầu cụ thể của họ với {product}",
        })

    # 9. Cost Efficiency
    if len(cpas) >= 3:
        best_cpa_r = min(valid, key=lambda r: r["cpa_vnd"] if r["cpa_vnd"] > 0 else float("inf"))
        worst_cpa_r = max(valid, key=lambda r: r["cpa_vnd"])
        if worst_cpa_r["cpa_vnd"] > best_cpa_r["cpa_vnd"] * 2:
            gap = worst_cpa_r["cpa_vnd"] / max(best_cpa_r["cpa_vnd"], 1)
            takeaways.append({
                "element": "Cost Efficiency",
                "signal": f"CPA range: {best_cpa_r['cpa_vnd']:,}{ccy} (best) — {worst_cpa_r['cpa_vnd']:,}{ccy} (worst) — chênh {gap:.1f}x.",
                "strength": "Peer set có đủ variance để justify việc chuyển budget.",
                "weakness": "Nhóm high-CPA đang tiêu budget mà không tạo conversion hiệu quả.",
                "insight": f"Chuyển budget từ nhóm CPA > {median_cpa*1.5:,.0f}{ccy} sang creative dựa trên pattern của nhóm low-CPA có thể giảm CPA trung bình đáng kể.",
                "action": f"Pause nhóm CPA > {median_cpa*1.5:,.0f}{ccy}. Tăng budget cho nhóm CPA < {median_cpa:,.0f}{ccy}. Tạo variant từ best-CPA creative.",
            })

    # 10. Cross-Channel Learning
    if has_moloco and has_srn:
        takeaways.append({
            "element": "Cross-Channel Learning",
            "signal": "File có cả SRN (social feed) và Moloco (programmatic banner).",
            "strength": "Có thể so sánh performance cùng concept trên nhiều channel.",
            "weakness": "Không nên dùng cùng framework phân tích cho mọi channel.",
            "insight": "SRN cần ưu tiên: hook, talent, sound, first 3s, UGC fit. Moloco cần ưu tiên: size, placement, CTA visibility, text density, offer clarity.",
            "action": "Tách learning theo channel trước:\n- SRN: phân tích hook, video pacing, creative concept\n- Moloco: phân tích size, placement, banner readability\nSau đó tìm common winning pattern.",
        })

    return takeaways



def _build_key_learning(takeaways, results, cfg, ccy="đ", variance_check=None, dim_priority=None) -> dict:
    """Build insight-driven learning: connects winning signal → root cause → channel mechanic → actionable hypothesis."""
    import re as _re
    valid = [r for r in results if r["actions"] > 0]
    product = cfg.get("product", "App")
    has_variance = bool(variance_check)

    if not valid:
        return {
            "learning": "Chưa có đủ conversion data để rút key learning.",
            "bottleneck": "Bottleneck chính: thiếu conversion signal.",
            "next_step": "Verify event tracking cho tất cả creative. Sau đó re-analyze với đủ data.",
            "winning": None, "trigger": None, "barrier": None,
        }

    best = max(valid, key=lambda r: r["quality_score"])
    worst = min(valid, key=lambda r: r["quality_score"])
    best_channel = best.get("channel", "") or _guess_channel(best["entity"])
    worst_channel = worst.get("channel", "") or _guess_channel(worst["entity"])
    pattern = best.get("pattern", "balanced")
    iterate_count = sum(1 for r in valid if r["decision"] == "ITERATE HOOK")
    investigate_count = sum(1 for r in valid if r["decision"] == "INVESTIGATE FUNNEL")

    def _offer_hint(entity):
        money = _re.findall(r'(\d+)[Kk]', entity)
        label = f"offer {money[0]}K" if money else ""
        for sig, lbl in [("TIKTOK","TikTok Shop"),("SHOP","shop"),("GRAB","Grab"),
                          ("BILL","hóa đơn"),("SCAN","QR/scan"),("TRANSFER","chuyển khoản")]:
            if sig in entity.upper():
                label = (label + " + " + lbl) if label else lbl
                break
        return label or "creative"

    def _ch_bottleneck(channel, pat):
        ch = channel.lower()
        if "tiktok" in ch:
            return ("first frame chưa isolate offer value proposition đủ nhanh cho TikTok scroll feed"
                    if pat == "low_ctr_high_cvr" else
                    "hook đang trigger curiosity click nhưng chưa pre-qualify đúng intent")
        if any(k in ch for k in ("moloco","in-app","dsp","programmatic")):
            return ("banner size/placement chưa đủ visibility trong in-app inventory"
                    if pat == "low_ctr_high_cvr" else
                    "DSP targeting và creative format cần align để tăng qualified impression")
        if "google" in ch:
            return ("asset combination chưa đủ mạnh để trigger strong ad assembly trong UAC"
                    if pat == "low_ctr_high_cvr" else
                    "audience signal và asset score cần tối ưu đồng thời")
        if any(k in ch for k in ("facebook","meta")):
            return ("first frame/thumbnail chưa stop scroll trong news feed"
                    if pat == "low_ctr_high_cvr" else
                    "format và audience targeting cần align hơn")
        return "packaging và delivery dimension cần được tối ưu đồng thời"

    ch_bottleneck = _ch_bottleneck(best_channel, pattern)
    resolved_primary = cfg.get("_resolved_primary_metric") or cfg.get("primary_metric", "")
    rate_label = _rate_metric_label(resolved_primary)
    cost_label = _cost_metric_label(resolved_primary)
    action_skill = cfg.get("_action_skill") or {}
    action_label = action_skill.get("action_label", "selected action") if action_skill else "selected action"

    # ── INSIGHT-DRIVEN LEARNING ──────────────────────────────────────────────
    if has_variance and variance_check:
        top_var = variance_check[0]
        learning = (
            f"Phát hiện variance quan trọng trong concept «{top_var['concept']}»: "
            f"CTR chênh {top_var['ctr_spread_pp']}pp và {rate_label} chênh {top_var['cvr_spread_pp']}pp giữa các variant cùng message. "
            f"Insight chính: cùng một concept có thể thắng/thua khác nhau vì delivery context, nên chưa thể kết luận concept chỉ từ một asset."
        )
    elif pattern == "low_ctr_high_cvr":
        offer = _offer_hint(best["entity"])
        learning = (
            f"{best_channel} creative với {offer} tạo selected action tốt: {rate_label} {best['cvr_pct']:.1f}%, trong khi CTR chỉ {best['ctr_pct']:.2f}%. "
            f"Nghĩa là offer/message đang lọc đúng user sau click cho mục tiêu {action_label}, nhưng chưa đủ mạnh để kéo volume đầu phễu."
        )
    elif pattern == "high_ctr_low_cvr":
        learning = (
            f"{best_channel} creative kéo được attention: CTR {best['ctr_pct']:.2f}%, nhưng {rate_label} chỉ {best['cvr_pct']:.1f}%. "
            f"Insight chính: hook/visual đang tạo click, nhưng chưa pre-qualify đúng user cho mục tiêu {action_label}."
        )
    else:
        offer_tk = next((t for t in takeaways if t.get("element","").startswith("Offer")), None)
        if offer_tk and "cao hơn" in (offer_tk.get("signal") or ""):
            learning = (
                f"Offer/promotion là conversion driver chính: {offer_tk['signal']}. "
                f"{best_channel} creative với offer cụ thể đang convert tốt hơn nhóm non-promo. "
                f"Đây là product-market fit signal — user {product} respond với value proposition rõ ràng. "
                f"Cơ hội: scale offer-based creative và test offer framing mới (số tiền + use case cụ thể)."
            )
        else:
            learning = (
                f"{best_channel} creative đang balanced (CTR {best['ctr_pct']:.2f}%, "
                f"{rate_label} {best['cvr_pct']:.1f}%, QS {best['quality_score']}). "
                f"Insight chính: chưa có một driver đơn lẻ áp đảo; cần test có kiểm soát để tìm performance ceiling."
            )

    # ── BOTTLENECK ─────────────────────────────────────────────────────────
    if has_variance and variance_check:
        top_var = variance_check[0]
        dims = ", ".join(top_var.get("different_dimensions", ["OS/size/placement"]))
        bottleneck = (
            f"Delivery dimension ({dims}) đang confound creative insight. "
            f"Không nên kết luận creative element nào thắng/thua cho đến khi dimension gap được isolate."
        )
    elif iterate_count > 0:
        bottleneck = (
            f"Vướng ở attention/visibility: {ch_bottleneck}. "
            f"Đây là vấn đề packaging/delivery, không phải concept; {iterate_count} creative vẫn có {rate_label} tốt nhưng CTR thấp nên {product} đang bỏ lỡ click volume."
        )
    elif investigate_count > 0:
        bottleneck = (
            f"Vướng ở post-click/action fit: {investigate_count} creative có CTR cao nhưng {rate_label} thấp. "
            f"Creative đang tạo false efficiency: nhiều click nhưng ít selected action có giá trị."
        )
    else:
        bottleneck = (
            f"Không có bottleneck dominant. Pool {len(valid)} creative đang ở mức performance tương đương. "
            f"Cần diversify creative direction để tìm outlier signal."
        )

    # ── NEXT STEP (actionable steps, không list entity name) ────────────────
    next_parts = []
    step = 1
    if has_variance and variance_check:
        top_var = variance_check[0]
        dims = ", ".join(top_var.get("different_dimensions", ["OS/size/placement"]))
        next_parts.append(
            f"BƯỚC {step} — Isolate delivery dimension: "
            f"Breakdown concept «{top_var['concept']}» theo {dims}. "
            f"Mục tiêu: xác nhận dimension nào gây CTR gap {top_var['ctr_spread_pp']}pp "
            f"trước khi quyết định sửa creative element."
        )
        step += 1

    if pattern == "low_ctr_high_cvr":
        next_parts.append(
            f"BƯỚC {step} — Giữ offer/message core. "
            f"Test 3 visual variant trên {best_channel}: "
            f"(1) offer lớn hơn, "
            f"(2) CTA rõ hơn, "
            f"(3) hierarchy sạch hơn. "
            f"Target: CTR tăng từ {best['ctr_pct']:.2f}% → {min(best['ctr_pct']*2.5, 5.0):.1f}%."
        )
    elif pattern == "high_ctr_low_cvr":
        next_parts.append(
            f"BƯỚC {step} — Message narrowing trên {best_channel}: "
            f"CTR {best['ctr_pct']:.2f}% tốt nhưng {rate_label} {best['cvr_pct']:.1f}% thấp. "
            f"Thêm qualifying message vào hook/thumbnail: "
            f"đề cập rõ target use case ngay từ đầu để pre-filter unqualified click."
        )
    else:
        next_parts.append(
            f"BƯỚC {step} — Creative iteration: "
            f"Từ signal QS {best['quality_score']} ({best_channel}), "
            f"tạo 2-3 variant — mỗi variant chỉ thay 1 yếu tố "
            f"(offer framing / hook / CTA) để isolate conversion driver."
        )
    step += 1

    if worst and worst["entity"] != best["entity"]:
        next_parts.append(
            f"BƯỚC {step} — Xử lý creative kém (QS {worst['quality_score']}, "
            f"{worst.get('decision','PAUSE')}): "
            f"Không sửa nhỏ — rebuild từ best signal direction "
            f"hoặc pause để tránh kéo tụt campaign average."
        )

    next_step = "\n".join(next_parts)

    # ── CHANNEL SKILL ───────────────────────────────────────────────────────
    channel_skill = _channel_skill_analysis(best, valid) if best else None

    # ── WINNING BLOCK ──────────────────────────────────────────────────────
    winning = None
    if best:
        if pattern == "low_ctr_high_cvr":
            key_metric = f"{rate_label} {best['cvr_pct']:.1f}% — selected action signal tốt, cần rebuild hook"
        elif pattern == "high_ctr_low_cvr":
            key_metric = f"CTR {best['ctr_pct']:.2f}% — attention tốt, cần qualify intent"
        else:
            key_metric = f"CTR {best['ctr_pct']:.2f}% & {rate_label} {best['cvr_pct']:.1f}% — balanced signal"
        winning = {
            "entity": best["entity"], "qs": best["quality_score"],
            "ctr": best["ctr_pct"], "cvr": best["cvr_pct"],
            "cpa": best["cpa_vnd"], "decision": best["decision"],
            "channel": best_channel, "os": best.get("os", ""),
            "pattern": pattern, "key_metric": key_metric,
        }

    # ── BARRIER BLOCK ──────────────────────────────────────────────────────
    barrier = None
    if worst:
        barrier = {
            "entity": worst["entity"], "qs": worst["quality_score"],
            "ctr": worst["ctr_pct"], "cvr": worst["cvr_pct"],
            "cpa": worst["cpa_vnd"], "decision": worst["decision"],
            "channel": worst_channel,
            "bottleneck": bottleneck,
            "avoid": (
                "Creative này đang tạo unqualified traffic. "
                "Tránh tương tự: hook quá generic, offer không rõ, format không phù hợp channel. "
                "Rebuild hoàn toàn từ best signal thay vì sửa nhỏ."
            ),
        }

    return {
        "learning": learning,
        "bottleneck": bottleneck,
        "next_step": next_step,
        "winning": winning,
        "trigger": {"channel_skill": channel_skill},
        "barrier": barrier,
    }


def _build_recommendations(results, cfg, all_channels, ccy="đ", has_variance=False, dim_priority=None) -> list:
    recs = []
    product = cfg.get("product", "App")
    valid = [r for r in results if r["actions"] > 0]

    if has_variance:
        recs.append({
            "priority": "Cao nhất",
            "learning": "Phát hiện variance trong cùng concept — delivery dimension có thể là driver chính.",
            "action": "Breakdown cùng concept theo dimension (OS, size, placement, date). Xác nhận dimension nào gây chênh lệch TRƯỚC khi tạo creative variant mới.",
            "owner": "UA",
            "output": "Variance breakdown table: concept × dimension → metric delta.",
        })

    if dim_priority:
        for dp in dim_priority[:2]:
            recs.append({
                "priority": "Cao",
                "learning": f"{dp['channel']}: {dp.get('reason', '')}",
                "action": f"Phân tích theo thứ tự: {' → '.join(dp['order'][:4])}. Không kết luận element phía sau trước khi check element phía trước.",
                "owner": "UA + Creative",
                "output": f"Performance breakdown theo {dp['order'][0]} cho {dp['channel']}",
            })

    iterate_hook = [r for r in results if r.get("decision") == "ITERATE HOOK"]
    if iterate_hook:
        prefix = "Sau khi confirm variance: " if has_variance else ""
        recs.append({
            "priority": "Cao",
            "learning": f"Offer/message convert được user có intent nhưng thiếu click volume ({len(iterate_hook)} creative).",
            "action": f"{prefix}Tạo 3 variant giữ nguyên offer nhưng đổi first frame:\n- Offer-led: ưu đãi nổi bật\n- Use-case-led: scenario thật\n- Human-context-led: người dùng + bối cảnh",
            "owner": "Creative",
            "output": "3 mockup: offer-led, use-case-led, human-context-led",
        })

    investigate = [r for r in results if r.get("decision") == "INVESTIGATE FUNNEL"]
    if investigate:
        prefix = "Sau khi confirm variance: " if has_variance else ""
        recs.append({
            "priority": "Cao",
            "learning": f"Một số creative CTR cao nhưng CVR thấp ({len(investigate)} creative).",
            "action": f"{prefix}Audit promise vs post-click flow. Đổi CTA từ generic sang specific.",
            "owner": "UA + Product",
            "output": "1 checklist mismatch + đề xuất sửa CTA/landing",
        })

    no_conv = [r for r in results if r.get("warning")]
    if no_conv:
        recs.append({
            "priority": "Cao",
            "learning": f"Không có conversion signal ({len(no_conv)} creative).",
            "action": "Verify event tracking/pixel setup. Kiểm tra mapping event và attribution window.",
            "owner": "UA",
            "output": "Tracking check result + pause/continue decision",
        })

    pause = [r for r in results if r.get("decision") == "PAUSE"]
    if pause:
        waste = sum(r["cost_vnd"] for r in pause)
        recs.append({
            "priority": "Trung bình",
            "learning": f"CTR và CVR yếu ({len(pause)} creative). Chi phí ước tính: {waste:,}{ccy}.",
            "action": "Pause và dùng winning signal lậm direction mới. Không sửa nhỏ — rebuild từ best signal.",
            "owner": "UA + Creative",
            "output": "Paused spend + replacement concepts",
        })

    scale = [r for r in results if r.get("decision") == "SCALE"]
    if scale:
        recs.append({
            "priority": "Cao nhất",
            "learning": f"{len(scale)} creative đạt SCALE — performance vượt plan vạ chất lượng tốt.",
            "action": "Tăng budget vào nhóm này. Test 2-3 variant để find ceiling trước khi scale lớn.",
            "owner": "UA",
            "output": "Budget reallocation plan + scale variant brief",
        })

    if not recs:
        recs.append({
            "priority": "Trung bình",
            "learning": "Chưa có tín hiệu nổi bật. Toàn bộ creative ở mức performance tương đương.",
            "action": "Diversify creative direction: test cả offer, hook và format mới để tìm outlier signal.",
            "owner": "Creative",
            "output": "3 new creative brief theo 3 hướng khác nhau",
        })

    def _rank(rec):
        p = str(rec.get("priority", "")).strip().lower()
        if "cao" in p and "nh" in p:
            return 0
        if "cao" in p:
            return 1
        if "trung" in p:
            return 2
        return 9

    return sorted(recs, key=_rank)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
