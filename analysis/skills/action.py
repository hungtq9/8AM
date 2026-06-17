"""
Action-aware conversion diagnosis.

This layer explains the selected Primary Metric(s). Channel skills explain
attention mechanics; action skills explain what can block the post-click action.
"""

from __future__ import annotations


def get_action_skill(metric_kind: str, goal: str = "ua", segment: str = "", ctr: float = 0.0, action_rate: float = 0.0) -> dict:
    kind = (metric_kind or "generic").lower()
    goal = (goal or "ua").lower()
    has_segment = bool(str(segment or "").strip())

    profiles = {
        "install": {
            "action_label": "Install",
            "rate_label": "Install Rate",
            "post_click_factors": ["store friction", "app size/compatibility", "install intent", "store listing trust"],
            "tests": ["So sánh store landing path", "Kiểm tra install friction theo OS/device", "Test creative promise khớp store listing"],
            "audience_dependency": "medium",
        },
        "login": {
            "action_label": "Login",
            "rate_label": "Login Rate",
            "post_click_factors": ["onboarding clarity", "OTP/login friction", "trust cue", "first-session value"],
            "tests": ["Audit login/OTP step", "Test message nêu rõ lợi ích sau login", "Kiểm tra deeplink vào đúng onboarding screen"],
            "audience_dependency": "medium",
        },
        "payment": {
            "action_label": "Payment/NPU",
            "rate_label": "Action Rate",
            "post_click_factors": ["offer economics", "use-case urgency", "funding/payment flow", "merchant/app destination"],
            "tests": ["Audit payment destination", "Test offer điều kiện rõ hơn", "Breakdown theo use case và payment readiness"],
            "audience_dependency": "high",
        },
        "lead": {
            "action_label": "Lead",
            "rate_label": "Action Rate",
            "post_click_factors": ["form friction", "perceived value", "qualification question", "follow-up expectation"],
            "tests": ["Giảm field form", "Nêu rõ user nhận gì sau submit", "Test qualified vs broad lead form"],
            "audience_dependency": "high",
        },
        "qualified_lead": {
            "action_label": "Qualified Lead",
            "rate_label": "Action Rate",
            "post_click_factors": ["qualification criteria", "audience fit", "sales readiness", "downstream validation"],
            "tests": ["Define qualified event", "So sánh source quality", "Thêm validation event vào report"],
            "audience_dependency": "very high",
        },
        "generic": {
            "action_label": "Selected Action",
            "rate_label": "Action Rate",
            "post_click_factors": ["event definition", "post-click path", "offer-message match", "audience fit"],
            "tests": ["Định nghĩa Primary Metric(s)", "Audit post-click path", "Breakdown theo segment nếu có"],
            "audience_dependency": "unknown",
        },
    }

    profile = profiles.get(kind, profiles["generic"]).copy()
    profile["metric_kind"] = kind
    profile["goal"] = goal if goal in ("ua", "retargeting", "other") else "other"
    profile["segment_note"] = (
        "Có segment input, có thể đánh giá audience-fit sâu hơn."
        if has_segment
        else "Chưa có segment input nên chưa đánh giá được audience-fit đầy đủ."
    )

    if ctr <= 0 and action_rate <= 0:
        bottleneck = "Thiếu signal để tách attention và action bottleneck."
    elif ctr < 1 and action_rate >= 1:
        bottleneck = "Attention bottleneck: action signal có nhưng chưa kéo đủ click volume."
    elif ctr >= 1 and action_rate < 1:
        bottleneck = "Action bottleneck: attention có nhưng post-click/action path chưa đủ mạnh."
    elif ctr < 1 and action_rate < 1:
        bottleneck = "Audience/offer-fit bottleneck: cả attention và selected action đều yếu."
    else:
        bottleneck = "Balanced signal: tối ưu từng yếu tố để tìm performance ceiling."

    if profile["goal"] == "retargeting":
        goal_note = "Retargeting cần đọc theo recency, reason-to-return, offer comeback, frequency cap và incrementality."
    elif profile["goal"] == "other":
        goal_note = "Other dùng cho lead, qualified lead hoặc action đặc thù; Primary Metric(s) quyết định action skill."
    else:
        goal_note = "UA cần đọc theo acquisition path: attention -> click -> first meaningful action."

    profile["bottleneck_attribution"] = bottleneck
    profile["goal_note"] = goal_note
    return profile
