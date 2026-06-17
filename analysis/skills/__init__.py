"""
analysis/skills/__init__.py
===========================
Skill router: maps (channel, mode, format) → correct skill module.

Rule hierarchy (highest priority first):
  1. mode  — user-selected mode (srn / programmatic / notification)
  2. channel — resolved channel from user selection + entity name
  3. format  — Image / Video (for format-aware skills)

Usage:
    from analysis.skills import get_channel_skill
    skill = get_channel_skill(entity_result, all_results)
"""

from __future__ import annotations


# ── Mode classification helpers ───────────────────────────────────────────────

_SRN_KEYWORDS = ("tiktok", "google", "facebook", "meta", "apple", "snap", "twitter",
                  "paid social", "srn", "social")
_PROGRAMMATIC_KEYWORDS = ("moloco", "in-app display", "in-app banner", "dsp",
                           "programmatic", "display", "other network", "inapp")
_NOTIFICATION_KEYWORDS = ("push", "notification", "in-app message", "email",
                           "lifecycle", "owned", "crm")


def _classify_mode(channel: str) -> str:
    """Return 'srn' | 'programmatic' | 'notification' | 'unknown'."""
    c = channel.lower()
    if any(k in c for k in _NOTIFICATION_KEYWORDS):
        return "notification"
    if any(k in c for k in _PROGRAMMATIC_KEYWORDS):
        return "programmatic"
    if any(k in c for k in _SRN_KEYWORDS):
        return "srn"
    return "unknown"


def _classify_srn_channel(channel: str) -> str:
    """Within SRN, identify the specific platform."""
    c = channel.lower()
    if "tiktok" in c:
        return "tiktok"
    if "google" in c or "uac" in c:
        return "google"
    if "facebook" in c or "meta" in c:
        return "facebook"
    if "apple" in c:
        return "apple"
    return "general"


# ── Main router ───────────────────────────────────────────────────────────────

def get_channel_skill(entity_result: dict, all_results: list) -> dict:
    """
    Route entity_result to the correct skill module and return skill analysis dict.

    Priority:
      1. Notification channel → notification skill
      2. Programmatic/In-app channel → programmatic skill (format-aware: Image vs Video)
      3. SRN channel → platform-specific skill (TikTok / Google / Facebook / general)
      4. Unknown → general fallback
    """
    channel = (entity_result.get("channel") or "").strip()
    mode = _classify_mode(channel)

    if mode == "notification":
        from .notification import analyze
        return analyze(entity_result, all_results)

    if mode == "programmatic":
        from .programmatic import analyze
        return analyze(entity_result, all_results)

    if mode == "srn":
        platform = _classify_srn_channel(channel)
        if platform == "tiktok":
            from .srn_tiktok import analyze
        elif platform == "google":
            from .srn_google import analyze
        elif platform == "facebook":
            from .srn_facebook import analyze
        else:
            from .general import analyze
        return analyze(entity_result, all_results)

    # Unknown / fallback
    from .general import analyze
    return analyze(entity_result, all_results)


# ── Convenience: list available skills ───────────────────────────────────────

SKILL_REGISTRY = {
    "srn": {
        "tiktok":   "srn_tiktok   — Hook/3s, Offer Framing, Video Pacing, CTA (format-aware: Image/Video)",
        "google":   "srn_google   — Asset Score, Headline, Image/Video Asset, Audience Signal",
        "facebook": "srn_facebook — Format, Text%, Hook/Thumbnail, Ad Copy & CTA",
    },
    "programmatic": {
        "image": "programmatic — Size/Placement, Offer Visibility, Visual Hierarchy, CTA Button",
        "video": "programmatic — First Frame, Video Length, Offer Overlay, Size Fit",
    },
    "notification": {
        "push":   "notification — Title, Body Copy, Send Time, CTA Deeplink",
        "inapp":  "notification — Visual & Offer, Title/Body, Trigger Context, CTA & Dismiss",
    },
}
