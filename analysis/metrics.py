"""
Metrics Calculator
- Quality Score = weighted composite of CTR, login_rate, CP Login efficiency
- CP Login, CTR, %Login (install→login)
- FX: 1 USD = 26,300 VND; TikTok +5% FCT
"""

from dataclasses import dataclass
from typing import List, Optional
import pandas as pd

FX = 26_300
FCT_TIKTOK = 1.05

# Plan benchmarks (fallback if no plan file uploaded)
# Segment: channel → CP Login plan (VND)
DEFAULT_PLAN = {
    "Google":   {"Android": 24_000, "iOS": 30_000},
    "TikTok":   {"Android": 40_000, "iOS": 40_000},
    "Facebook": {"Android": 35_000, "iOS": 38_000},
    "Moloco":   {"Android": 32_000, "iOS": 36_000},
    "Unknown":  {"Android": 35_000, "iOS": 35_000},
}


@dataclass
class CreativeMetrics:
    entity_name: str
    channel: str
    os: str
    creative_source: str
    use_case: str
    scheme: Optional[str]
    # Raw aggregates
    spend_usd: float
    spend_vnd: float
    impressions: int
    clicks: int
    installs: int
    logins: int
    npu: int
    # Derived
    ctr: float           # clicks / impressions
    login_rate: float    # logins / installs
    cpi_vnd: float       # spend / installs
    cp_login_vnd: float  # spend / logins
    cp_npu_vnd: float    # spend / npu (may be 0)
    plan_cp_login: float
    vs_plan_pct: float   # (cp_login - plan) / plan * 100
    quality_score: float
    decision: str        # SCALE / MAINTAIN / PAUSE


def aggregate_metrics(df: pd.DataFrame, plan: dict = None) -> List[CreativeMetrics]:
    """Aggregate raw rows → per-entity metrics."""
    if plan is None:
        plan = DEFAULT_PLAN

    results = []

    for (entity_name, channel, os_, creative_source, use_case, scheme), grp in df.groupby(
        ["analysis_entity_name", "channel", "os", "creative_source", "use_case", "scheme"],
        dropna=False
    ):
        spend_usd = grp["cost_usd"].sum()
        impressions = int(grp["impressions"].sum())
        clicks = int(grp["clicks"].sum())
        installs = int(grp["installs"].sum())
        logins = int(grp["logins"].sum())
        npu = int(grp["npu"].sum())

        # Apply FCT for TikTok
        fct = FCT_TIKTOK if channel == "TikTok" else 1.0
        spend_vnd = spend_usd * FX * fct

        ctr = clicks / impressions if impressions > 0 else 0
        login_rate = logins / installs if installs > 0 else 0
        cpi_vnd = spend_vnd / installs if installs > 0 else 0
        cp_login_vnd = spend_vnd / logins if logins > 0 else 0
        cp_npu_vnd = spend_vnd / npu if npu > 0 else 0

        # Plan benchmark
        os_key = "iOS" if os_ in ("iOS", "IOS", "ios") else "Android"
        plan_cp = plan.get(channel, {}).get(os_key, 35_000)

        vs_plan = ((cp_login_vnd - plan_cp) / plan_cp * 100) if plan_cp > 0 else 0

        qs = _quality_score(ctr, login_rate, cp_login_vnd, plan_cp)
        decision = _decision(vs_plan, qs)

        results.append(CreativeMetrics(
            entity_name=entity_name,
            channel=channel,
            os=os_key,
            creative_source=creative_source,
            use_case=use_case if pd.notna(use_case) else "Unknown",
            scheme=scheme if pd.notna(scheme) else None,
            spend_usd=round(spend_usd, 2),
            spend_vnd=round(spend_vnd),
            impressions=impressions,
            clicks=clicks,
            installs=installs,
            logins=logins,
            npu=npu,
            ctr=round(ctr * 100, 2),
            login_rate=round(login_rate * 100, 2),
            cpi_vnd=round(cpi_vnd),
            cp_login_vnd=round(cp_login_vnd),
            cp_npu_vnd=round(cp_npu_vnd),
            plan_cp_login=plan_cp,
            vs_plan_pct=round(vs_plan, 1),
            quality_score=qs,
            decision=decision,
        ))

    return sorted(results, key=lambda x: x.quality_score, reverse=True)


def _quality_score(ctr: float, login_rate: float, cp_login: float, plan_cp: float) -> float:
    """
    Quality Score (0–10): weighted composite
    - CTR efficiency (30%): normalized against 5% benchmark
    - Login rate (40%): normalized against 30% benchmark
    - CP Login vs plan (30%): inverted (lower is better)
    """
    ctr_score = min(ctr / 0.05, 1.0) * 10 * 0.30
    lr_score = min(login_rate / 0.30, 1.0) * 10 * 0.40
    plan_ratio = plan_cp / cp_login if cp_login > 0 else 0
    cost_score = min(plan_ratio, 1.5) / 1.5 * 10 * 0.30
    return round(ctr_score + lr_score + cost_score, 1)


def _decision(vs_plan_pct: float, quality_score: float) -> str:
    if quality_score >= 7.5 and vs_plan_pct <= 10:
        return "SCALE"
    elif quality_score >= 6.0 and vs_plan_pct <= 30:
        return "MAINTAIN"
    else:
        return "PAUSE"
