"""
Tools for Agent 2: Knowledge Graph Query.
Wraps graph_algorithms for use as Google ADK agent tools.
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import src.db_service as _db
from src.graph_algorithms import (
    bfs_disruption_propagation as _bfs,
    analyze_cascade_risk as _cascade,
    calculate_graph_centrality as _centrality,
    detect_spofs as _spofs,
    trace_disruption_paths as _trace,
    bfs_upstream_from as _upstream,
)


def bfs_disruption_propagation(disrupted_supplier_id: int) -> str:
    """Run BFS from a disrupted supplier downstream toward the manufacturer.

    Traces how a disruption at one supplier cascades through the supply chain
    network. Each tier hop attenuates the impact by 30%.

    Args:
        disrupted_supplier_id: The ID of the supplier where the disruption originates.

    Returns:
        JSON with list of affected suppliers, their impact scores, and hop distance.
    """
    snapshot = _db.get_full_supply_chain_snapshot()
    result = _bfs(snapshot["suppliers"], disrupted_supplier_id)
    return json.dumps({"affected_nodes": result, "count": len(result)})


def analyze_cascade_risk(disrupted_supplier_id: int) -> str:
    """Perform full cascade analysis: disruption propagation + product impact.

    Traces how a disruption propagates downstream AND identifies which finished
    products are affected and the total revenue at risk.

    Args:
        disrupted_supplier_id: The ID of the supplier where the disruption originates.

    Returns:
        JSON with affected suppliers, affected products, revenue at risk, and cascade depth.
    """
    snapshot = _db.get_full_supply_chain_snapshot()
    result = _cascade(
        snapshot["suppliers"],
        disrupted_supplier_id,
        snapshot["supplier_product_links"],
        snapshot["products"],
    )
    return json.dumps(result)


def calculate_graph_centrality() -> str:
    """Calculate degree, betweenness, and PageRank centrality for all suppliers.

    Identifies the most critical nodes (bottlenecks) in the supply chain graph.
    Higher centrality = more paths depend on this supplier = higher risk if disrupted.
    PageRank (damping=0.85) captures recursive importance from the directed graph
    structure (per AlMahri et al. 2025).

    Returns:
        JSON with list of suppliers sorted by combined centrality score (highest first).
        Each entry includes degree_centrality, betweenness_centrality, and pagerank.
    """
    snapshot = _db.get_full_supply_chain_snapshot()
    result = _centrality(snapshot["suppliers"])
    return json.dumps({"centrality_rankings": result[:10]})  # Top 10


def trace_disruption_paths(from_supplier_id: int) -> str:
    """Trace all downstream paths from a supplier to the manufacturer boundary.

    Shows the exact chain of suppliers a disruption would flow through.

    Args:
        from_supplier_id: Starting supplier ID to trace from.

    Returns:
        JSON with list of paths, where each path is an ordered list of suppliers.
    """
    snapshot = _db.get_full_supply_chain_snapshot()
    result = _trace(snapshot["suppliers"], from_supplier_id)
    return json.dumps({"paths": result, "num_paths": len(result)})


def get_full_supply_chain_snapshot() -> str:
    """Get a complete snapshot of the current supply chain state.

    Includes manufacturer info, all suppliers (with graph edges), products,
    inventory levels, active purchase orders, and supplier-product links.

    Returns:
        JSON with the full supply chain state.
    """
    snapshot = _db.get_full_supply_chain_snapshot()
    # Trim to keep token count manageable
    return json.dumps({
        "manufacturer": snapshot["manufacturer"],
        "num_suppliers": len(snapshot["suppliers"]),
        "suppliers_summary": [
            {
                "id": s["id"], "name": s["name"], "tier": s["tier"],
                "parent_id": s["parent_supplier_id"], "region": s["region"],
                "reliability": s["reliability_score"],
            }
            for s in snapshot["suppliers"]
        ],
        "products": snapshot["products"],
        "inventory": snapshot["inventory"],
        "active_purchase_orders": len(snapshot["purchase_orders"]),
    })


def detect_bottlenecks_and_spofs() -> str:
    """Detect Single Points of Failure (SPOFs) and bottleneck suppliers.

    Identifies suppliers that are sole sources, critical hubs, or whose failure
    would disconnect parts of the supply network.

    Returns:
        JSON with list of SPOF suppliers and their risk reasons.
    """
    snapshot = _db.get_full_supply_chain_snapshot()
    spofs = _spofs(snapshot["suppliers"])
    return json.dumps({"spofs": spofs, "count": len(spofs)})
