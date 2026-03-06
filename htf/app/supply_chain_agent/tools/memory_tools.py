"""
Tools for the Memory Agent.
Recall, search, and evaluate past disruption events.
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.db_service import get_past_disruptions, get_full_supply_chain_snapshot as _snapshot


def recall_past_disruptions(limit: int = 10) -> str:
    """Recall recent past disruption events from the system memory.

    Args:
        limit: Maximum number of past events to retrieve (default 10).

    Returns:
        JSON with list of past disruption events including type, severity,
        affected areas, mitigation taken, and effectiveness.
    """
    disruptions = get_past_disruptions(limit=limit)
    return json.dumps({
        "past_disruptions": disruptions,
        "count": len(disruptions),
    })


def find_similar_past_disruptions(
    event_type: str = "",
    affected_region: str = "",
    affected_industry: str = "",
) -> str:
    """Search for past disruptions similar to a current situation.

    Matches on event type, region, and/or industry to find relevant historical precedents.

    Args:
        event_type: Type of disruption to match (e.g. 'natural_disaster', 'geopolitical').
        affected_region: Region to match (e.g. 'Taiwan', 'China', 'Red Sea').
        affected_industry: Industry to match (e.g. 'semiconductor', 'battery').

    Returns:
        JSON with matching past disruptions and their mitigation outcomes.
    """
    all_disruptions = get_past_disruptions(limit=50)

    matches = []
    for d in all_disruptions:
        score = 0
        if event_type and d.get("event_type", "").lower() == event_type.lower():
            score += 3
        if affected_region and affected_region.lower() in (d.get("affected_region") or "").lower():
            score += 2
        # Check if industry is mentioned in description
        if affected_industry and affected_industry.lower() in (d.get("description") or "").lower():
            score += 1

        if score > 0:
            d["relevance_score"] = score
            matches.append(d)

    matches.sort(key=lambda x: x["relevance_score"], reverse=True)

    return json.dumps({
        "query": {
            "event_type": event_type,
            "affected_region": affected_region,
            "affected_industry": affected_industry,
        },
        "matches": matches[:5],
        "total_matches": len(matches),
    })


def evaluate_mitigation_effectiveness(event_type: str = "") -> str:
    """Evaluate how effective past mitigation strategies have been.

    Analyzes historical disruption data to identify which mitigation approaches
    worked best for different types of disruptions.

    Args:
        event_type: Optional filter by disruption type. Leave empty for all types.

    Returns:
        JSON with effectiveness statistics by disruption type and strategy.
    """
    all_disruptions = get_past_disruptions(limit=50)

    if event_type:
        filtered = [d for d in all_disruptions if d.get("event_type", "").lower() == event_type.lower()]
    else:
        filtered = all_disruptions

    # Group by event type
    by_type = {}
    for d in filtered:
        et = d.get("event_type", "unknown")
        if et not in by_type:
            by_type[et] = []
        by_type[et].append(d)

    analysis = {}
    for et, events in by_type.items():
        mitigated = [e for e in events if e.get("mitigation_effectiveness") is not None]
        avg_effectiveness = (
            sum(e["mitigation_effectiveness"] for e in mitigated) / len(mitigated)
            if mitigated else 0
        )
        total_revenue_impact = sum(e.get("revenue_impact", 0) or 0 for e in events)
        strategies = [e.get("mitigation_taken", "N/A") for e in events if e.get("mitigation_taken")]

        analysis[et] = {
            "total_events": len(events),
            "avg_mitigation_effectiveness": round(avg_effectiveness, 2),
            "total_revenue_impact": total_revenue_impact,
            "strategies_used": strategies,
        }

    return json.dumps({
        "effectiveness_analysis": analysis,
        "recommendation": "Focus on strategies with effectiveness > 0.6 for similar disruption types.",
    })
