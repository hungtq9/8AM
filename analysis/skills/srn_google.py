"""Skill: Google UAC (SRN/Paid Social)."""


def analyze(r: dict, all_results: list) -> dict:
    ctr, cvr = r.get("ctr_pct", 0), r.get("cvr_pct", 0)
    findings = [
        {
            "dim": "Asset Score & Combination",
            "icon": "📊",
            "finding": f"CTR {ctr:.2f}%. UAC chọn combination tự động — asset score quyết định frequency.",
            "signal": "warn" if ctr < 0.5 else "ok",
            "action": (
                "Upload đủ 5 hình, 5 video, 5 headline, 5 description để UAC có room test. "
                "Xem Asset Score trong Google Ads: 'Low' → cần replace. "
                "Headline phải chứa offer cụ thể (không chỉ brand name)."
            ),
        },
        {
            "dim": "Headline & Offer Clarity",
            "icon": "📝",
            "finding": f"CVR {cvr:.1f}%. Headline là element có highest weight trong UAC.",
            "signal": "ok" if cvr > 3 else "warn",
            "action": (
                "Test headline: (1) Offer-first: 'Nhận 15K khi tải Zalopay'; "
                "(2) Use-case: 'Thanh toán TikTok Shop – Giảm 15K'; "
                "(3) Problem: 'Không cần tiền mặt – Zalopay'. "
                "Mỗi headline ≤30 ký tự, không truncate trên mobile."
            ),
        },
        {
            "dim": "Image & Video Asset",
            "icon": "🖼️",
            "finding": "UAC sử dụng cả image và video trong cùng campaign — asset nào weak sẽ kéo tụt.",
            "signal": "warn",
            "action": (
                "Image: 1:1 (1200×1200) và 1.91:1 (1200×628) là priority. "
                "Video: ≥10 giây, offer trong 5 giây đầu. "
                "Pause assets với 'Low' score sau 2 tuần."
            ),
        },
        {
            "dim": "Audience Signal",
            "icon": "🎯",
            "finding": "UAC học từ conversion signal — audience quality ảnh hưởng trực tiếp đến creative performance.",
            "signal": "ok" if cvr > 3 else "warn",
            "action": (
                "Upload custom audience: past converters, similar users. "
                "Nếu CVR thấp dù creative tốt, kiểm tra audience signal quality. "
                "Không nên edit campaign trong 2 tuần đầu — để machine learning ổn định."
            ),
        },
    ]
    gap_note = ""
    if ctr < 0.5 and cvr > 5:
        gap_note = "Low CTR + High CVR: creative qualify tốt nhưng UAC không serve đủ volume. Check asset score và budget."
    elif ctr > 1 and cvr < 2:
        gap_note = "High CTR + Low CVR: click nhiều nhưng không convert. Kiểm tra deeplink và onboarding flow."
    return {
        "channel": "Google UAC",
        "format": r.get("format", "Mixed"),
        "dimensions": ["Asset Score", "Headline & Offer", "Image & Video", "Audience Signal"],
        "analysis_order": "Asset Score → Headline → Image/Video → Audience Signal",
        "key_insight": "UAC: headline + asset quality quyết định CTR. Machine learning cần ≥50 conversions/tuần để optimize tốt.",
        "gap_note": gap_note,
        "specific_analysis": findings,
    }
