"""
Tools for Agent 4: Network Visualizer.
Provides data structures for Plotly graph visualization.
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.db_service import get_full_supply_chain_snapshot as _snapshot
from src.graph_algorithms import (
    bfs_disruption_propagation as _bfs,
    calculate_graph_centrality as _centrality,
)


def get_graph_viz_data(disrupted_supplier_id: int = 0) -> str:
    """Get supply chain graph data formatted for network visualization.

    Returns nodes (suppliers) and edges (supply relationships) with positions,
    colors, and sizes suitable for Plotly network graph rendering.
    If a disrupted_supplier_id is provided, overlays BFS propagation data.

    Args:
        disrupted_supplier_id: Optional. If set, highlights disruption propagation path.

    Returns:
        JSON with nodes (id, label, tier, x, y, color, size) and
        edges (source, target) for graph visualization.
    """
    snapshot = _snapshot()
    suppliers = snapshot["suppliers"]
    centrality = _centrality(suppliers)
    centrality_map = {c["supplier_id"]: c["combined_centrality"] for c in centrality}

    # BFS overlay if disruption specified
    affected_map = {}
    if disrupted_supplier_id > 0:
        affected = _bfs(suppliers, disrupted_supplier_id)
        affected_map = {a["supplier_id"]: a["impact_score"] for a in affected}

    # Layout: tier-based horizontal positioning
    tier_x = {1: 0.8, 2: 0.4, 3: 0.0}
    tier_counts = {1: 0, 2: 0, 3: 0}

    nodes = []
    for s in suppliers:
        tier = s["tier"]
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        idx = tier_counts[tier]

        # Spread nodes vertically within their tier
        tier_total = sum(1 for sup in suppliers if sup["tier"] == tier)
        y = (idx / (tier_total + 1))

        # Color based on disruption status
        if s["id"] in affected_map:
            impact = affected_map[s["id"]]
            if impact >= 0.8:
                color = "red"
            elif impact >= 0.5:
                color = "orange"
            else:
                color = "yellow"
        else:
            color = {"1": "#4CAF50", "2": "#2196F3", "3": "#9C27B0"}.get(str(tier), "gray")

        # Size based on centrality
        cent = centrality_map.get(s["id"], 0)
        size = 15 + cent * 100

        nodes.append({
            "id": s["id"],
            "label": s["name"],
            "tier": tier,
            "region": s["region"],
            "x": tier_x.get(tier, 0.5),
            "y": y,
            "color": color,
            "size": round(size, 1),
            "centrality": round(cent, 4),
            "impact_score": affected_map.get(s["id"], 0),
            "is_disrupted": s["id"] in affected_map,
        })

    edges = []
    for s in suppliers:
        if s["parent_supplier_id"] is not None:
            edges.append({
                "source": s["id"],
                "target": s["parent_supplier_id"],
                "is_affected": (
                    s["id"] in affected_map and s["parent_supplier_id"] in affected_map
                ),
            })

    # Add manufacturer node
    mfg = snapshot["manufacturer"]
    nodes.append({
        "id": 0,
        "label": mfg.get("name", "Manufacturer"),
        "tier": 0,
        "region": mfg.get("region", ""),
        "x": 1.0,
        "y": 0.5,
        "color": "#FF5722",
        "size": 30,
        "centrality": 1.0,
        "impact_score": 0,
        "is_disrupted": False,
    })

    # Add edges from Tier 1 to manufacturer
    for s in suppliers:
        if s["tier"] == 1:
            edges.append({
                "source": s["id"],
                "target": 0,
                "is_affected": s["id"] in affected_map,
            })

    return json.dumps({
        "nodes": nodes,
        "edges": edges,
        "disrupted_supplier_id": disrupted_supplier_id,
        "num_affected": len(affected_map),
    })
