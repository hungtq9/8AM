"""
Report Generator
- Builds structured insight payload for LLM
- Formats final Markdown report
"""

from typing import List, Optional
from .metrics import CreativeMetrics


def build_llm_prompt(metrics: List[CreativeMetrics], context: str = "") -> str:
    """Build prompt for Qwen to generate narrative creative insight."""

    top = metrics[:5]
    tto = [m for m in metrics if m.creative_source == "TTO"]
    freelance = [m for m in metrics if m.creative_source == "Freelance"]
    moloco = [m for m in metrics if m.channel == "Moloco"]

    tto_avg_cp = _avg_cp(tto)
    fl_avg_cp = _avg_cp(freelance)

    summary_rows = "\n".join([
        f"- {m.entity_name[:60]} | {m.channel} {m.os} | "
        f"CTR {m.ctr}% | Login rate {m.login_rate}% | "
        f"CP Login {m.cp_login_vnd:,.0f} VND (plan {m.plan_cp_login:,.0f}) | "
        f"vs plan {m.vs_plan_pct:+.1f}% | QS {m.quality_score} | {m.decision}"
        for m in top
    ])

    tto_section = ""
    if tto or freelance:
        tto_section = f"""
TTO vs Freelance (TikTok):
- TTO ({len(tto)} entities): avg CP Login {tto_avg_cp:,.0f} VND
- Freelance ({len(freelance)} entities): avg CP Login {fl_avg_cp:,.0f} VND
"""

    moloco_section = ""
    if moloco:
        moloco_rows = "\n".join([
            f"  - Scheme {m.scheme or 'N/A'} | USP {m.use_case} | "
            f"CP Login {m.cp_login_vnd:,.0f} VND | {m.decision}"
            for m in moloco[:4]
        ])
        moloco_section = f"\nMoloco creative clusters:\n{moloco_rows}"

    prompt = f"""Bạn là Senior UA Performance Analyst của Zalopay.
Hãy viết creative performance insight report theo cấu trúc sau, bằng tiếng Việt (giữ nguyên technical terms tiếng Anh):

{context}

DỮ LIỆU ĐẦU VÀO:

Top creatives (by Quality Score):
{summary_rows}
{tto_section}{moloco_section}

YÊU CẦU OUTPUT (STRICT):
1. ## TL;DR — 2–3 dòng tóm tắt câu chuyện chính
2. ## Creative Signals — 3–4 bullets: pattern nổi bật nhất
3. ## TTO vs Freelance Analysis — so sánh 2 nguồn, kết luận rõ (nếu có TikTok data)
4. ## Moloco Scheme Breakdown — creative cluster tốt/kém (nếu có Moloco data)
5. ## Top Decisions — bảng: Entity | Decision | Lý do ngắn
6. ## Next Action — 2–3 action cụ thể với priority

RULES:
- Insight-first, không liệt kê số liệu thô
- Mỗi insight: Observation → Why it matters → Action
- KHÔNG đề xuất cut toàn channel nếu chỉ 1 creative source drag
- KHÔNG kết luận creative fatigue chỉ từ CTR
- Tone: Senior analyst report cho Head of Growth
"""
    return prompt


def format_markdown_report(metrics: List[CreativeMetrics], llm_narrative: str) -> str:
    """Combine LLM narrative + data table into final Markdown report."""

    scale = [m for m in metrics if m.decision == "SCALE"]
    maintain = [m for m in metrics if m.decision == "MAINTAIN"]
    pause = [m for m in metrics if m.decision == "PAUSE"]

    table_rows = "\n".join([
        f"| {m.entity_name[:55]} | {m.channel} | {m.os} | "
        f"{m.creative_source} | {m.ctr}% | {m.login_rate}% | "
        f"{m.cp_login_vnd:,.0f} | {m.vs_plan_pct:+.1f}% | {m.quality_score} | **{m.decision}** |"
        for m in metrics[:10]
    ])

    report = f"""# Creative Performance Insight Report

{llm_narrative}

---

## Performance Table (Top 10 by Quality Score)

| Creative / Ad Entity | Channel | OS | Source | CTR% | Login Rate% | CP Login (VND) | vs Plan | QS | Decision |
|---|---|---|---|---|---|---|---|---|---|
{table_rows}

---

## Summary
- **SCALE** ({len(scale)}): {', '.join(m.creative_source for m in scale[:3])} creatives
- **MAINTAIN** ({len(maintain)}): holding position
- **PAUSE** ({len(pause)}): needs review

*Data: mock synthetic data for demo purposes. FX = 26,300 VND/USD. TikTok +5% FCT.*
"""
    return report


def _avg_cp(items: List[CreativeMetrics]) -> float:
    if not items:
        return 0
    total_spend = sum(m.spend_vnd for m in items)
    total_login = sum(m.logins for m in items)
    return total_spend / total_login if total_login > 0 else 0
