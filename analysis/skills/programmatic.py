"""Skill: Programmatic / In-app Display (Moloco, DSP, Other Network).
Format-aware: Image Banner vs Video Banner have different dimension priorities."""

import re as _re


def _extract_format(entity: str) -> str:
    e_lower = entity.lower()
    if any(e_lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
        return "Image"
    if any(e_lower.endswith(ext) for ext in (".mp4", ".mov", ".avi", ".m4v")):
        return "Video"
    if e_lower.endswith(".gif"):
        return "GIF"
    for p in entity.split("_"):
        pu = p.upper().rstrip("0123456789")
        if pu in ("IMAGE", "IMG", "STATIC"):
            return "Image"
        if pu in ("VIDEO", "VID"):
            return "Video"
        if pu == "GIF":
            return "GIF"
    return "Unknown"


def _extract_size(entity: str) -> str:
    match = _re.search(r'(\d{2,4})[xX×](\d{2,4})', entity)
    return match.group(0) if match else ""


def _size_tier(size: str) -> str:
    if any(s in size for s in ("320x50", "728x90", "468x60")):
        return "small"
    if any(s in size for s in ("300x250", "320x100", "250x250")):
        return "medium"
    if any(s in size for s in ("320x480", "300x600", "480x320", "336x280")):
        return "large"
    return "unknown"


def analyze(r: dict, all_results: list) -> dict:
    ctr, cvr = r.get("ctr_pct", 0), r.get("cvr_pct", 0)
    entity = r.get("entity", "")
    fmt = (r.get("format") or _extract_format(entity)).lower()
    size = r.get("size") or _extract_size(entity)
    is_image = "image" in fmt or (fmt in ("unknown", "") and "gif" not in fmt and "video" not in fmt)

    if is_image:
        return _analyze_image_banner(r, all_results, ctr, cvr, size)
    else:
        return _analyze_video_banner(r, all_results, ctr, cvr, size)


def _analyze_image_banner(r, all_results, ctr, cvr, size):
    tier = _size_tier(size)
    size_label = size or "unknown size"
    tier_advice = {
        "small":  "Banner nhỏ (≤50px height): chỉ 1 message — offer number + brand. Không text phụ.",
        "medium": "MREC (300×250): cân bằng image + text, test human face vs pure offer graphic.",
        "large":  "Interstitial/Large: có không gian nhưng user muốn đóng nhanh — offer rõ trong 1 giây đầu.",
        "unknown": "Không detect được size — kiểm tra naming convention.",
    }[tier]

    findings = [
        {
            "dim": "Size & Placement Tier",
            "icon": "📐",
            "finding": f"Size: {size_label} ({tier}). CTR {ctr:.2f}%. {tier_advice}",
            "signal": "warn" if ctr < 0.5 else "ok",
            "action": (
                "Breakdown CTR theo size: 320×50 vs 300×250 vs 320×480 vs 728×90. "
                "Cùng creative, size khác nhau có thể CTR chênh 3-5×. "
                "Xác nhận size nào perform trước khi kết luận về concept."
            ),
        },
        {
            "dim": "Offer Visibility",
            "icon": "💰",
            "finding": (
                f"CVR {cvr:.1f}%. Image banner: offer phải readable ở thumb-size "
                f"— user xem banner nhỏ, không zoom."
            ),
            "signal": "ok" if cvr > 3 else "warn",
            "action": (
                "Checklist: (1) Số tiền offer ≥14sp; (2) Contrast text/background ≥4.5:1; "
                "(3) Offer không bị overlap bởi logo hay decoration; "
                "(4) Test: shrink 50% — còn readable không?"
            ),
        },
        {
            "dim": "Visual Hierarchy",
            "icon": "🎨",
            "finding": "Image banner phải truyền message trong <1 giây. Eye path: Offer → CTA → Brand.",
            "signal": "warn" if ctr < 0.5 else "ok",
            "action": (
                "Nguyên tắc: Offer = largest element, CTA = second, Brand = smallest. "
                "Background không cạnh tranh với offer text. "
                "Loại bỏ decorative elements không contribute vào action."
            ),
        },
        {
            "dim": "CTA Button",
            "icon": "👆",
            "finding": (
                f"CTA phải là button riêng biệt, không phải text thường. "
                f"{'CTR thấp có thể do CTA không trông clickable.' if ctr < 0.5 else 'CTA đang tạo được click.'}"
            ),
            "signal": "ok" if ctr > 0.3 else "warn",
            "action": (
                "CTA phải: (1) Có màu nền contrast với background; "
                "(2) Text cụ thể: 'Nhận 15K' không phải 'Tải ngay'; "
                "(3) Min 44px height để tap được trên mobile; "
                "(4) Đặt gần offer, không tách biệt."
            ),
        },
    ]

    gap_note = ""
    if ctr < 0.5 and cvr > 5:
        gap_note = (
            f"Low CTR + High CVR trên image banner {size_label}: "
            "offer qualify đúng intent nhưng banner chưa đủ visible. "
            "Check placement context: banner đang ở vị trí low-visibility không?"
        )
    elif ctr > 1 and cvr < 2:
        gap_note = "High CTR + Low CVR: image hấp dẫn nhưng post-click không match offer. Kiểm tra deeplink."

    return {
        "channel": "In-app Display / Programmatic",
        "format": "Image Banner",
        "size": size,
        "dimensions": ["Size & Placement", "Offer Visibility", "Visual Hierarchy", "CTA Button"],
        "analysis_order": "Size/Placement → Offer Visibility → Visual Hierarchy → CTA",
        "key_insight": (
            f"Image banner {size_label}: user xem <1 giây — offer dominant space, "
            "readable ngay, CTA là button rõ. "
            "Ưu tiên: size/placement → offer visibility → visual hierarchy → CTA."
        ),
        "gap_note": gap_note,
        "specific_analysis": findings,
    }


def _analyze_video_banner(r, all_results, ctr, cvr, size):
    size_label = size or "unknown size"
    findings = [
        {
            "dim": "First Frame (Static Fallback)",
            "icon": "🖼️",
            "finding": (
                f"CTR {ctr:.2f}%. In-app video: nhiều inventory không autoplay — "
                "first frame phải standalone như image banner."
            ),
            "signal": "warn" if ctr < 0.5 else "ok",
            "action": (
                "First frame phải đủ mạnh như image banner độc lập. "
                "Offer visible ngay frame 0 kể cả khi video không play. "
                "Test: screenshot frame 0 → dùng như image banner."
            ),
        },
        {
            "dim": "Video Length & Pacing",
            "icon": "⏱️",
            "finding": "In-app video: user không chủ động tìm content — tolerance thấp hơn social feed.",
            "signal": "warn",
            "action": (
                "Optimal: 6-15 giây. Offer phải xuất hiện trong 2 giây đầu. "
                "Kết thúc bằng CTA rõ ràng + offer recap."
            ),
        },
        {
            "dim": "Offer & CTA Overlay",
            "icon": "💰",
            "finding": f"CVR {cvr:.1f}%. Video cần text overlay persistent — user có thể xem không có audio.",
            "signal": "ok" if cvr > 3 else "warn",
            "action": (
                "Persistent offer overlay suốt video. "
                "CTA button xuất hiện từ giây thứ 3 và giữ đến hết. "
                "Audio-off safe: toàn bộ message phải readable qua visual + text."
            ),
        },
        {
            "dim": "Size & Aspect Ratio Fit",
            "icon": "📐",
            "finding": f"Size: {size_label}. Video cần aspect ratio phù hợp với banner size.",
            "signal": "warn" if not size else "ok",
            "action": (
                "320×480: vertical — dùng 9:16, không letterbox. "
                "300×250: near-square — 1:1 tốt hơn 16:9 bị letterbox. "
                "Verify ratio match để tránh crop quan trọng elements."
            ),
        },
    ]

    gap_note = ""
    if ctr < 0.5 and cvr > 3:
        gap_note = (
            "Low CTR + High CVR trên video banner: content qualify tốt nhưng first frame chưa mạnh. "
            "Fix first frame như image banner trước."
        )

    return {
        "channel": "In-app Display / Programmatic",
        "format": "Video Banner",
        "size": size,
        "dimensions": ["First Frame", "Video Length", "Offer Overlay", "Size Fit"],
        "analysis_order": "First Frame → Size Fit → Offer Overlay → CTA",
        "key_insight": (
            f"Video banner {size_label}: first frame phải standalone, "
            "offer overlay persistent, audio-off safe."
        ),
        "gap_note": gap_note,
        "specific_analysis": findings,
    }
