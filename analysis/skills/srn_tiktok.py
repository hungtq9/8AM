"""Skill: TikTok (SRN/Paid Social). Format-aware: Video (default) vs Static Image."""


def _extract_format(entity: str) -> str:
    e_lower = entity.lower()
    if any(e_lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
        return "Image"
    if any(e_lower.endswith(ext) for ext in (".mp4", ".mov")):
        return "Video"
    for p in entity.split("_"):
        pu = p.upper().rstrip("0123456789")
        if pu in ("IMAGE", "IMG", "STATIC"):
            return "Image"
        if pu in ("VIDEO", "VID"):
            return "Video"
    return "Video"   # TikTok default: video


def analyze(r: dict, all_results: list) -> dict:
    ctr, cvr = r.get("ctr_pct", 0), r.get("cvr_pct", 0)
    fmt = (r.get("format") or _extract_format(r.get("entity", ""))).lower()
    is_image = "image" in fmt

    if is_image:
        return _analyze_image(r, all_results, ctr, cvr)
    return _analyze_video(r, all_results, ctr, cvr)


def _analyze_video(r, all_results, ctr, cvr):
    findings = [
        {
            "dim": "Hook / First 3s",
            "icon": "🎣",
            "finding": (
                f"CTR {ctr:.2f}% — "
                f"{'hook chưa đủ mạnh để thumb-stop trong scroll feed' if ctr < 1.5 else 'hook đang tạo click volume tốt'}."
            ),
            "signal": "warn" if ctr < 1.5 else "ok",
            "action": (
                "Test 3 hook direction: "
                "(1) Offer-dominant — số tiền lớn, contrast cao ngay frame 0; "
                "(2) Human-context — người dùng thật đang checkout; "
                "(3) Problem-first — show pain point trước khi reveal solution."
            ),
        },
        {
            "dim": "Offer Framing trong Hook",
            "icon": "💸",
            "finding": (
                f"CVR {cvr:.1f}% — "
                f"{'offer resonates sau click — giữ nguyên message' if cvr > 5 else 'offer chưa translate thành action sau click'}."
            ),
            "signal": "ok" if cvr > 5 else "warn",
            "action": (
                "Offer phải xuất hiện trong 3 giây đầu, không đợi mid-video. "
                "User TikTok không kiên nhẫn. Overlay text offer ngay frame 0-2."
            ),
        },
        {
            "dim": "Video Pacing & Length",
            "icon": "⏱️",
            "finding": "TikTok cạnh tranh với organic content — video chậm mất attention trước khi truyền đủ message.",
            "signal": "warn" if ctr < 1 else "ok",
            "action": (
                "Optimal: 7-15 giây cho UA. "
                "Mỗi 3 giây có một hook/reveal mới để giữ retention. "
                "Tránh slow intro."
            ),
        },
        {
            "dim": "CTA & Text Overlay",
            "icon": "✍️",
            "finding": (
                "Text overlay và CTA phải cụ thể — "
                "'Tải Zalopay nhận 15K' tốt hơn 'Tải ngay'."
            ),
            "signal": "ok" if cvr > 5 else "warn",
            "action": (
                "CTA gắn với offer + action trong app. "
                "Text overlay: bold + màu tương phản cao. "
                "Audio-off safe: toàn bộ message readable qua visual."
            ),
        },
    ]
    gap_note = ""
    if ctr < 1.5 and cvr > 5:
        gap_note = "Low CTR + High CVR: offer tốt nhưng hook chưa thumb-stop. Giữ nguyên offer, rebuild hook."
    elif ctr > 2 and cvr < 3:
        gap_note = "High CTR + Low CVR: hook hấp dẫn nhưng promise không match post-click. Audit deeplink."
    return {
        "channel": "TikTok",
        "format": "Video",
        "dimensions": ["Hook / First 3s", "Offer Framing", "Video Pacing", "CTA & Text Overlay"],
        "analysis_order": "Hook/First 3s → Video Pacing → Offer Framing → CTA",
        "key_insight": "TikTok: hook 3 giây đầu quyết định CTR. Concept chỉ phát huy khi hook đủ mạnh. Offer visible trong 3s đầu.",
        "gap_note": gap_note,
        "specific_analysis": findings,
    }


def _analyze_image(r, all_results, ctr, cvr):
    findings = [
        {
            "dim": "Visual Hook (Static)",
            "icon": "🎨",
            "finding": f"CTR {ctr:.2f}%. TikTok image cạnh tranh với video feed — phải cực kỳ bold để thumb-stop.",
            "signal": "warn" if ctr < 1 else "ok",
            "action": "High contrast, bold offer text, human element nếu có. Tránh muted colors và complex composition.",
        },
        {
            "dim": "Offer Prominence",
            "icon": "💰",
            "finding": f"CVR {cvr:.1f}%. TikTok user expect value upfront — offer chiếm ≥40% visual space.",
            "signal": "ok" if cvr > 5 else "warn",
            "action": "Số tiền/offer là focal point. Màu contrast mạnh (đỏ/vàng). Test: remove mọi thứ ngoài offer + CTA — vẫn meaningful?",
        },
        {
            "dim": "CTA Clarity",
            "icon": "✍️",
            "finding": "Static: không có movement dẫn dắt attention — CTA phải self-evident.",
            "signal": "ok" if ctr > 1 else "warn",
            "action": "CTA button shape + action text cụ thể. 'Nhận 15K ngay' tốt hơn 'Tìm hiểu thêm'. Position: bottom center.",
        },
    ]
    gap_note = "Low CTR + High CVR trên TikTok static: image chưa đủ bold để stop scroll, message tốt. Test bolder visual." if ctr < 1 and cvr > 5 else ""
    return {
        "channel": "TikTok",
        "format": "Static Image",
        "dimensions": ["Visual Hook", "Offer Prominence", "CTA Clarity"],
        "analysis_order": "Visual Hook → Offer Prominence → CTA",
        "key_insight": "TikTok image cần bold hơn bình thường vì cạnh tranh với video. Offer dominant, contrast cao.",
        "gap_note": gap_note,
        "specific_analysis": findings,
    }
