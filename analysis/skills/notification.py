"""Skill: Owned / Lifecycle — Push Notification & In-app Message."""


def analyze(r: dict, all_results: list) -> dict:
    """Notification creative skill: title, body, send time, CTA deeplink."""
    channel = (r.get("channel") or "").lower()
    is_push = "push" in channel or channel == "notification"
    is_inapp = "in-app message" in channel or "inapp" in channel

    ctr, cvr = r.get("ctr_pct", 0), r.get("cvr_pct", 0)
    entity = r.get("entity", "")

    if is_inapp:
        return _analyze_inapp(r, all_results, ctr, cvr)
    return _analyze_push(r, all_results, ctr, cvr)


def _analyze_push(r, all_results, ctr, cvr):
    findings = [
        {
            "dim": "Title (First Hook)",
            "icon": "📌",
            "finding": (
                f"CTR {ctr:.2f}%. Title là element đầu tiên user đọc — "
                f"{'chưa đủ compelling để trigger open' if ctr < 5 else 'title đang tạo được open rate tốt'}."
            ),
            "signal": "warn" if ctr < 5 else "ok",
            "action": (
                "Title ≤50 ký tự (không bị truncate trên lock screen). "
                "Test 3 angle: (1) Offer-first: 'Nhận offer ngay hôm nay'; "
                "(2) Urgency: 'Còn 2 giờ — voucher của bạn sắp hết'; "
                "(3) Personalized: '[Tên], ưu đãi dành riêng cho bạn'."
            ),
        },
        {
            "dim": "Body Copy",
            "icon": "📝",
            "finding": (
                f"CVR {cvr:.1f}%. Body phải reinforce title và add specific detail "
                f"— không repeat title, không vague."
            ),
            "signal": "ok" if cvr > 3 else "warn",
            "action": (
                "Body ≤100 ký tự. Nêu cụ thể: số tiền, use case, điều kiện đơn giản. "
                "VD: 'Thanh toán use case bằng app — áp dụng đến 23:59 hôm nay'. "
                "Tránh: 'Khám phá ưu đãi hấp dẫn tại app'."
            ),
        },
        {
            "dim": "Send Time & Frequency",
            "icon": "⏰",
            "finding": "Send time ảnh hưởng trực tiếp đến open rate — cùng content, sai giờ = CTR giảm 50%.",
            "signal": "warn",
            "action": (
                "Peak open time: 8-9h sáng, 12-13h trưa, 20-22h tối. "
                "Tránh 0-7h và >23h. "
                "Frequency: max 1 push/ngày, max 5/tuần để tránh opt-out. "
                "Test A/B send time: sáng vs tối với cùng content."
            ),
        },
        {
            "dim": "CTA Deeplink",
            "icon": "👆",
            "finding": (
                f"CVR {cvr:.1f}%. Click → đúng destination quyết định conversion. "
                f"{'CVR thấp dù CTR không tệ: kiểm tra deeplink.' if cvr < 3 and ctr > 5 else ''}"
            ),
            "signal": "ok" if cvr > 5 else "warn",
            "action": (
                "Deeplink phải đưa thẳng vào screen liên quan (không về home). "
                "VD: push về voucher → deeplink vào voucher detail screen, không vào wallet. "
                "Test deeplink trên cả Android và iOS trước khi push live."
            ),
        },
    ]
    gap_note = ""
    if ctr < 5 and cvr > 10:
        gap_note = "Low open rate + High CVR: notification content qualify tốt nhưng title chưa compelling. Test title mới với urgency hoặc personalization."
    elif ctr > 10 and cvr < 3:
        gap_note = "High open rate + Low CVR: title tốt nhưng deeplink/screen destination không match. Audit post-click journey."
    return {
        "channel": "Push Notification",
        "format": "Push",
        "dimensions": ["Title", "Body Copy", "Send Time", "CTA Deeplink"],
        "analysis_order": "Title → Send Time → Body → Deeplink",
        "key_insight": "Push notification: title là hook duy nhất trên lock screen. Send time và deeplink accuracy quyết định CVR sau open.",
        "gap_note": gap_note,
        "specific_analysis": findings,
    }


def _analyze_inapp(r, all_results, ctr, cvr):
    findings = [
        {
            "dim": "Visual & Offer Hierarchy",
            "icon": "🎨",
            "finding": (
                f"CTR {ctr:.2f}%. In-app message: user đã trong app — attention cao hơn push "
                f"nhưng cũng có intent để làm việc khác."
            ),
            "signal": "ok" if ctr > 5 else "warn",
            "action": (
                "Offer phải là visual dominant. "
                "Không dùng text-only — add image/illustration để tăng perceived value. "
                "Layout: Offer visual → Offer text → CTA button → Dismiss."
            ),
        },
        {
            "dim": "Title & Body",
            "icon": "📝",
            "finding": f"CVR {cvr:.1f}%. Title phải immediate value, body reinforces với specifics.",
            "signal": "ok" if cvr > 5 else "warn",
            "action": (
                "Title ≤40 ký tự, benefit-first. "
                "Body: 1 câu, nêu điều kiện và deadline nếu có. "
                "Avoid: modal title = 'Thông báo' → không nói lên được gì."
            ),
        },
        {
            "dim": "Trigger Context",
            "icon": "⚡",
            "finding": "In-app message hiệu quả nhất khi trigger đúng lúc user có relevant intent.",
            "signal": "warn",
            "action": (
                "Trigger rules: (1) User vừa add item to cart → show payment offer; "
                "(2) User vào scan screen → show scan promo; "
                "(3) User idle >30s trên home → show general offer. "
                "Tránh trigger ngay lúc app open — user chưa kịp có context."
            ),
        },
        {
            "dim": "CTA & Dismiss",
            "icon": "👆",
            "finding": f"CVR {cvr:.1f}%. CTA button phải primary action, dismiss phải accessible.",
            "signal": "ok" if cvr > 5 else "warn",
            "action": (
                "Primary CTA: 1 button, màu brand, text cụ thể. "
                "Secondary/Dismiss: text link 'Để sau', không button — "
                "để avoid split attention. "
                "Không dùng X icon ở corner nếu có dismiss text button."
            ),
        },
    ]
    gap_note = ""
    if ctr < 5 and cvr > 10:
        gap_note = "Low tap rate + High CVR: message qualify tốt nhưng layout/visual chưa compelling. Test với richer visual."
    return {
        "channel": "In-app Message",
        "format": "In-app",
        "dimensions": ["Visual & Offer", "Title & Body", "Trigger Context", "CTA & Dismiss"],
        "analysis_order": "Trigger Context → Visual → Title/Body → CTA",
        "key_insight": "In-app message: trigger context quyết định relevance, visual hierarchy quyết định CVR. User đã có intent — đừng interrupt sai lúc.",
        "gap_note": gap_note,
        "specific_analysis": findings,
    }
