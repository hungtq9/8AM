"""Skill: Meta / Facebook (SRN/Paid Social)."""


def analyze(r: dict, all_results: list) -> dict:
    ctr, cvr = r.get("ctr_pct", 0), r.get("cvr_pct", 0)
    findings = [
        {
            "dim": "Format (Static vs Video vs Carousel)",
            "icon": "🖼️",
            "finding": f"CTR {ctr:.2f}%. Format quyết định cách user tiếp nhận message trong feed.",
            "signal": "warn" if ctr < 1 else "ok",
            "action": (
                "Test static (single image) vs carousel vs video. "
                "Static phù hợp offer rõ; carousel phù hợp nhiều use case; "
                "video phù hợp story-telling. "
                "Không mix format trong cùng ad set để tránh confound data."
            ),
        },
        {
            "dim": "Text % & Offer Visibility",
            "icon": "📊",
            "finding": "Meta penalizes text >20% diện tích ảnh. Offer phải visible ngay từ thumbnail.",
            "signal": "warn",
            "action": (
                "Text trên ảnh ≤20% diện tích. "
                "Offer number (VD: 15K) là focal point của image. "
                "Dùng contrast color để offer nổi bật. "
                "Test với Facebook Text Overlay tool."
            ),
        },
        {
            "dim": "Hook / Thumbnail",
            "icon": "🎣",
            "finding": f"CTR {ctr:.2f}%. Thumbnail/first frame quyết định user có dừng scroll không.",
            "signal": "warn" if ctr < 1 else "ok",
            "action": (
                "Test thumbnail: human face > product only > graphic. "
                "Offer in thumbnail > offer chỉ trong caption. "
                "Màu sắc tương phản cao với feed mặc định (trắng/xám)."
            ),
        },
        {
            "dim": "Ad Copy & CTA",
            "icon": "✍️",
            "finding": f"CVR {cvr:.1f}%. Ad copy phải qualify intent trước khi user click.",
            "signal": "ok" if cvr > 5 else "warn",
            "action": (
                "Primary text: nêu benefit trong câu đầu. "
                "CTA: cụ thể ('Nhận 15K') không generic ('Xem thêm'). "
                "Caption phải match với image offer — không tạo cognitive dissonance."
            ),
        },
    ]
    gap_note = ""
    if ctr < 1 and cvr > 5:
        gap_note = "Low CTR + High CVR: message qualify tốt nhưng creative chưa thumb-stop. Test thumbnail mới."
    elif ctr > 2 and cvr < 3:
        gap_note = "High CTR + Low CVR: click nhiều nhưng không convert. Kiểm tra landing page và deeplink mismatch."
    return {
        "channel": "Meta / Facebook",
        "format": r.get("format", "Mixed"),
        "dimensions": ["Format", "Text % & Offer Visibility", "Hook / Thumbnail", "Ad Copy & CTA"],
        "analysis_order": "Format → Hook/Thumbnail → Offer Visibility → CTA",
        "key_insight": "Meta: hook + offer visibility trong thumbnail quyết định CTR. Text% ≤20%. Offer visible không cần đọc caption.",
        "gap_note": gap_note,
        "specific_analysis": findings,
    }
