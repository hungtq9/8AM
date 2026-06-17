"""Fallback skill — used when channel/mode cannot be determined."""

def analyze(r: dict, all_results: list) -> dict:
    ctr, cvr = r.get("ctr_pct", 0), r.get("cvr_pct", 0)
    findings = [
        {
            "dim": "Offer / Message Clarity",
            "icon": "💬",
            "finding": f"CTR {ctr:.2f}%, CVR {cvr:.1f}%. Creative cần offer rõ ràng và message nhất quán từ hook đến CTA.",
            "signal": "ok" if ctr > 0.5 and cvr > 3 else "warn",
            "action": "Kiểm tra: user biết họ nhận gì sau khi click không? Offer phải visible không cần đọc kỹ.",
        },
        {
            "dim": "CTA Effectiveness",
            "icon": "👆",
            "finding": f"CVR {cvr:.1f}% — CTA cần cụ thể và gắn với offer, không generic.",
            "signal": "ok" if cvr > 5 else "warn",
            "action": "Test CTA: 'Nhận 15K ngay' vs 'Tải về' — cụ thể luôn tốt hơn generic.",
        },
        {
            "dim": "Visual Hierarchy",
            "icon": "🎨",
            "finding": "Message phải readable ngay lần đầu tiên user thấy — không cần đọc lại.",
            "signal": "warn",
            "action": "Eye path: Offer → CTA → Brand. Loại bỏ elements không contribute vào action.",
        },
    ]
    gap_note = ""
    if ctr < 0.5 and cvr > 5:
        gap_note = "Low CTR + High CVR: message qualify tốt nhưng creative chưa đủ visible/appealing. Test packaging mới."
    elif ctr > 1 and cvr < 2:
        gap_note = "High CTR + Low CVR: creative hấp dẫn nhưng post-click không match. Kiểm tra landing/deeplink."
    return {
        "channel": r.get("channel", "Unknown"),
        "format": r.get("format", "Unknown"),
        "dimensions": ["Offer Clarity", "CTA", "Visual Hierarchy"],
        "analysis_order": "Offer → CTA → Visual",
        "key_insight": "Phân tích chung: offer clarity và CTA specificity là 2 lever quan trọng nhất.",
        "gap_note": gap_note,
        "specific_analysis": findings,
    }
