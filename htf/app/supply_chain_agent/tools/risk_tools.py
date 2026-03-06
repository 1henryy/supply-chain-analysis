"""
Tools for Agent 5: Risk Manager.
Weighted risk formula with graph centrality component.
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.db_service import get_full_supply_chain_snapshot as _snapshot
from src.graph_algorithms import (
    bfs_disruption_propagation,
    calculate_graph_centrality,
    analyze_cascade_risk,
    aggregate_risk_to_tier1,
)


def compute_weighted_risk_score(
    disrupted_supplier_id: int,
    disruption_severity: str = "medium",
) -> str:
    """Compute a weighted risk score for a disruption using the 5-factor formula.

    RISK = 0.35*Breadth + 0.25*Dependency + 0.20*Criticality + 0.10*Centrality + 0.10*Depth

    - Breadth: fraction of products affected
    - Dependency: average supply chain impact on affected products
    - Criticality: weighted criticality of affected products
    - Centrality: graph centrality of the disrupted supplier (betweenness + degree)
    - Depth: how deep in the supply chain the disruption originates

    Args:
        disrupted_supplier_id: The supplier where disruption originates.
        disruption_severity: Severity level: 'low', 'medium', 'high', 'critical'.

    Returns:
        JSON with overall risk score (0-1), component breakdown, and risk classification.
    """
    snapshot = _snapshot()
    suppliers = snapshot["suppliers"]
    products = snapshot["products"]
    links = snapshot["supplier_product_links"]

    # Cascade analysis
    cascade = analyze_cascade_risk(suppliers, disrupted_supplier_id, links, products)

    # Centrality
    centrality_list = calculate_graph_centrality(suppliers)
    centrality_map = {c["supplier_id"]: c for c in centrality_list}
    sup_centrality = centrality_map.get(disrupted_supplier_id, {})

    total_products = len(products)
    affected_products = cascade["affected_products"]

    # Factor 1: Breadth (0-1) -- fraction of products affected
    breadth = len(affected_products) / total_products if total_products > 0 else 0

    # Factor 2: Dependency (0-1) -- avg impact score on affected products
    if affected_products:
        dependency = sum(p["supply_chain_impact"] for p in affected_products) / len(affected_products)
    else:
        dependency = 0

    # Factor 3: Criticality (0-1) -- weighted by product criticality
    crit_weights = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
    if affected_products:
        criticality = sum(
            crit_weights.get(p["criticality"], 0.5) for p in affected_products
        ) / len(affected_products)
    else:
        criticality = 0

    # Factor 4: Centrality (0-1) -- combined centrality of disrupted supplier
    centrality = sup_centrality.get("combined_centrality", 0)
    # Normalize: typical max is ~0.3, scale to 0-1
    centrality = min(centrality / 0.3, 1.0)

    # Factor 5: Depth (0-1) -- cascade depth normalized
    max_possible_depth = 3  # 3-tier network
    depth = cascade["cascade_depth"] / max_possible_depth

    # Severity multiplier
    sev_mult = {"low": 0.6, "medium": 0.8, "high": 1.0, "critical": 1.2}
    multiplier = sev_mult.get(disruption_severity, 0.8)

    # Weighted risk score
    raw_score = (
        0.35 * breadth
        + 0.25 * dependency
        + 0.20 * criticality
        + 0.10 * centrality
        + 0.10 * depth
    )
    final_score = min(raw_score * multiplier, 1.0)

    # Classification
    if final_score >= 0.6:
        classification = "HIGH"
        action = "VP/CFO approval required"
    elif final_score >= 0.45:
        classification = "MEDIUM"
        action = "Auto-execute with notification"
    else:
        classification = "LOW"
        action = "Auto-execute silently"

    # Revenue at risk
    revenue_at_risk = cascade["total_revenue_at_risk"]
    board_notify = revenue_at_risk > 5_000_000

    return json.dumps({
        "risk_score": round(final_score, 4),
        "classification": classification,
        "recommended_action": action,
        "board_notification_required": board_notify,
        "revenue_at_risk": revenue_at_risk,
        "component_breakdown": {
            "breadth": round(breadth, 4),
            "dependency": round(dependency, 4),
            "criticality": round(criticality, 4),
            "centrality": round(centrality, 4),
            "depth": round(depth, 4),
        },
        "severity_multiplier": multiplier,
        "num_products_affected": len(affected_products),
        "num_suppliers_affected": cascade["num_suppliers_affected"],
    })


def compute_tier1_risk_aggregation(disrupted_supplier_id: int) -> str:
    """Aggregate upstream disruption risk to Tier-1 suppliers (per AlMahri et al. 2025).

    Maps a disruption at any tier to its impact on controllable Tier-1 suppliers.
    Companies have direct operational control only over Tier-1, so upstream risks
    must be expressed as Tier-1 exposure to be actionable.

    Args:
        disrupted_supplier_id: The upstream supplier where disruption originates.

    Returns:
        JSON with per-Tier-1 aggregated risk scores and component breakdown.
    """
    snapshot = _snapshot()
    result = aggregate_risk_to_tier1(
        snapshot["suppliers"],
        disrupted_supplier_id,
        snapshot["supplier_product_links"],
        snapshot["products"],
    )
    return json.dumps({
        "tier1_risk_aggregation": result,
        "num_tier1_affected": len(result),
        "source_supplier_id": disrupted_supplier_id,
    })


def get_risk_summary_all_suppliers() -> str:
    """Get a risk summary for every Tier 1 supplier showing what happens if each is disrupted.

    Returns:
        JSON with per-supplier risk scores and affected product counts.
    """
    snapshot = _snapshot()
    tier1 = [s for s in snapshot["suppliers"] if s["tier"] == 1]

    summaries = []
    for s in tier1:
        cascade = analyze_cascade_risk(
            snapshot["suppliers"], s["id"],
            snapshot["supplier_product_links"], snapshot["products"],
        )
        summaries.append({
            "supplier_id": s["id"],
            "supplier_name": s["name"],
            "region": s["region"],
            "reliability": s["reliability_score"],
            "products_affected": cascade["num_products_affected"],
            "revenue_at_risk": cascade["total_revenue_at_risk"],
        })

    summaries.sort(key=lambda x: x["revenue_at_risk"], reverse=True)
    return json.dumps({"tier1_risk_summary": summaries})
