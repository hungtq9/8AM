"""
Campaign & Ad Name Parser
Rules: UA_ENTITY_PARSER.md
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedEntity:
    raw_campaign: str
    raw_ad: Optional[str]
    channel: str
    os: str
    optimization_event: str
    use_case: str
    creative_type: str
    creative_source: str          # TTO / Freelance / Moloco-scheme
    analysis_entity_type: str     # Campaign / Ad/Creative
    analysis_entity_name: str
    scheme: Optional[str] = None  # Moloco only
    usp: Optional[str] = None     # Moloco only
    creative_format: Optional[str] = None
    script_id: Optional[str] = None
    data_confidence: str = "Medium"
    is_valid_zpi: bool = False


CHANNEL_MAP = {
    "GG UA": "Google", "Google": "Google", "UAC": "Google",
    "Tiktok UA": "TikTok", "TikTok UA": "TikTok", "Tiktok FS": "TikTok",
    "TikTok FS": "TikTok", "TT UA": "TikTok",
    "Facebook": "Facebook", "Meta": "Facebook", "FB": "Facebook",
    "Moloco": "Moloco", "MOLOCO": "Moloco",
}


def parse_campaign(campaign_name: str, ad_name: Optional[str] = None) -> ParsedEntity:
    """Parse a campaign name into structured fields per UA_ENTITY_PARSER rules."""
    tokens = campaign_name.split("_")

    # Validate ZPI_ prefix (Step 1 filter)
    is_valid = len(tokens) >= 8 and tokens[0] == "ZPI"

    if not is_valid:
        return ParsedEntity(
            raw_campaign=campaign_name, raw_ad=ad_name,
            channel="Unknown", os="Unknown", optimization_event="Unknown",
            use_case="Unknown", creative_type="Unknown",
            creative_source="Unknown", analysis_entity_type="Campaign",
            analysis_entity_name=campaign_name,
            data_confidence="Low", is_valid_zpi=False,
        )

    # Step 2: optimization event must start with AEO-
    opt_event = tokens[3] if len(tokens) > 3 else ""
    if not opt_event.startswith("AEO-"):
        return ParsedEntity(
            raw_campaign=campaign_name, raw_ad=ad_name,
            channel="Unknown", os="Unknown", optimization_event=opt_event,
            use_case="Unknown", creative_type="Unknown",
            creative_source="Unknown", analysis_entity_type="Campaign",
            analysis_entity_name=campaign_name,
            data_confidence="Low", is_valid_zpi=False,
        )

    use_case = tokens[4] if len(tokens) > 4 else "Unknown"
    os_raw = tokens[5] if len(tokens) > 5 else "Unknown"
    os_parsed = "iOS" if os_raw.upper() in ("IOS", "iOS") else "Android" if os_raw.upper() == "ANDROID" else os_raw
    channel_token = "_".join(tokens[7:8]) if len(tokens) > 7 else ""

    # Handle multi-word channel tokens like "GG UA", "Tiktok UA"
    channel_raw = tokens[7] if len(tokens) > 7 else ""
    if len(tokens) > 8:
        two_token = f"{tokens[7]} {tokens[8]}"
        channel_parsed = CHANNEL_MAP.get(two_token) or CHANNEL_MAP.get(channel_raw, "Unknown")
    else:
        channel_parsed = CHANNEL_MAP.get(channel_raw, "Unknown")

    creative_type_raw = tokens[-1] if tokens else "Unknown"

    # Creative source identification (Lens 7)
    creative_source = _identify_creative_source(campaign_name, channel_parsed)

    # Moloco: use ad name as primary entity
    if channel_parsed == "Moloco":
        if ad_name:
            moloco = _parse_moloco_ad(ad_name)
            return ParsedEntity(
                raw_campaign=campaign_name, raw_ad=ad_name,
                channel="Moloco", os=os_parsed,
                optimization_event=opt_event, use_case=use_case,
                creative_type=creative_type_raw, creative_source="Moloco",
                analysis_entity_type="Ad/Creative",
                analysis_entity_name=ad_name,
                scheme=moloco.get("scheme"),
                usp=moloco.get("usp"),
                creative_format=moloco.get("format"),
                script_id=moloco.get("script_id"),
                data_confidence="High", is_valid_zpi=True,
            )
        else:
            return ParsedEntity(
                raw_campaign=campaign_name, raw_ad=None,
                channel="Moloco", os=os_parsed,
                optimization_event=opt_event, use_case=use_case,
                creative_type=creative_type_raw, creative_source="Moloco",
                analysis_entity_type="Campaign",
                analysis_entity_name=campaign_name,
                data_confidence="Low", is_valid_zpi=True,
            )

    return ParsedEntity(
        raw_campaign=campaign_name, raw_ad=ad_name,
        channel=channel_parsed, os=os_parsed,
        optimization_event=opt_event, use_case=use_case,
        creative_type=creative_type_raw, creative_source=creative_source,
        analysis_entity_type="Campaign",
        analysis_entity_name=campaign_name,
        data_confidence="High" if channel_parsed != "Unknown" else "Low",
        is_valid_zpi=True,
    )


def _identify_creative_source(campaign_name: str, channel: str) -> str:
    """TTO vs Freelance for TikTok. Field 5 check for 'Tiktok One'."""
    if channel != "TikTok":
        return channel  # Google, Facebook etc
    tokens = campaign_name.split("_")
    use_case_field = tokens[4] if len(tokens) > 4 else ""
    if "Tiktok One" in use_case_field or "TikTok One" in use_case_field:
        return "TTO"
    return "Freelance"


def _parse_moloco_ad(ad_name: str) -> dict:
    """Parse Moloco creative name: Scheme_USP_Team_Format_ContentID_ScriptID_V_Size_Date"""
    # Remove extension
    name = ad_name.rsplit(".", 1)[0]
    tokens = name.split("_")
    return {
        "scheme": tokens[0] if len(tokens) > 0 else None,
        "usp": tokens[1] if len(tokens) > 1 else None,
        "team": tokens[2] if len(tokens) > 2 else None,
        "format": tokens[3] if len(tokens) > 3 else None,
        "content_id": tokens[4] if len(tokens) > 4 else None,
        "script_id": tokens[5] if len(tokens) > 5 else None,
        "version": tokens[6] if len(tokens) > 6 else None,
        "size": tokens[7] if len(tokens) > 7 else None,
    }
