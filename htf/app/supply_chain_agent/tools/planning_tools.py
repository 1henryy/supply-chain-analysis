"""
Tools for Agent 6: CSCO Agent (planning/mitigation).
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.db_service import get_full_supply_chain_snapshot as _snapshot, get_past_disruptions


def find_alternative_suppliers(disrupted_supplier_id: int) -> str:
    """Find potential alternative suppliers that could replace a disrupted supplier.

    Looks for other suppliers in the same industry/tier that are not currently
    at capacity and have acceptable reliability scores.

    Args:
        disrupted_supplier_id: The ID of the supplier to find replacements for.

    Returns:
        JSON with list of alternative suppliers ranked by suitability.
    """
    snapshot = _snapshot()
    supplier_map = {s["id"]: s for s in snapshot["suppliers"]}
    disrupted = supplier_map.get(disrupted_supplier_id)

    if not disrupted:
        return json.dumps({"error": f"Supplier {disrupted_supplier_id} not found"})

    target_industry = disrupted["industry"]
    target_tier = disrupted["tier"]

    alternatives = []
    for s in snapshot["suppliers"]:
        if s["id"] == disrupted_supplier_id:
            continue
        if s["industry"] != target_industry:
            continue

        # Score: higher reliability + lower capacity utilization = better
        available_capacity = 1.0 - s["capacity_utilization"]
        suitability = (s["reliability_score"] * 0.6 + available_capacity * 0.4)

        alternatives.append({
            "supplier_id": s["id"],
            "supplier_name": s["name"],
            "tier": s["tier"],
            "region": s["region"],
            "reliability_score": s["reliability_score"],
            "capacity_utilization": s["capacity_utilization"],
            "available_capacity": round(available_capacity, 2),
            "lead_time_days": s["lead_time_days"],
            "suitability_score": round(suitability, 3),
            "same_tier": s["tier"] == target_tier,
        })

    alternatives.sort(key=lambda x: x["suitability_score"], reverse=True)

    return json.dumps({
        "disrupted_supplier": {
            "id": disrupted["id"],
            "name": disrupted["name"],
            "industry": target_industry,
            "tier": target_tier,
        },
        "alternatives": alternatives[:5],
        "gaps": "No alternatives found" if not alternatives else None,
    })


def simulate_mitigation_tradeoffs(
    strategy: str,
    disrupted_supplier_id: int,
    alternative_supplier_id: int = 0,
) -> str:
    """Simulate the cost/benefit tradeoffs of a mitigation strategy.

    Args:
        strategy: One of 'reroute' (switch supplier), 'buffer' (increase safety stock),
                  'expedite' (rush existing orders), 'dual_source' (split between two suppliers).
        disrupted_supplier_id: The supplier being mitigated.
        alternative_supplier_id: For reroute/dual_source strategies, the replacement supplier ID.

    Returns:
        JSON with estimated cost, time impact, risk reduction, and recommendation.
    """
    snapshot = _snapshot()
    supplier_map = {s["id"]: s for s in snapshot["suppliers"]}
    disrupted = supplier_map.get(disrupted_supplier_id, {})
    alternative = supplier_map.get(alternative_supplier_id, {})

    base_lead_time = disrupted.get("lead_time_days", 14)
    base_cost = 1.0  # normalized

    if strategy == "reroute":
        alt_lead = alternative.get("lead_time_days", base_lead_time * 1.5)
        alt_reliability = alternative.get("reliability_score", 0.8)
        result = {
            "strategy": "reroute",
            "description": f"Switch from {disrupted.get('name', 'N/A')} to {alternative.get('name', 'N/A')}",
            "estimated_cost_increase": "15-25%",
            "lead_time_change_days": alt_lead - base_lead_time,
            "new_lead_time_days": alt_lead,
            "reliability_change": round(alt_reliability - disrupted.get("reliability_score", 0.9), 2),
            "risk_reduction": 0.6,
            "implementation_time_days": 7,
            "recommendation": "Good" if alt_reliability > 0.85 else "Acceptable with monitoring",
        }
    elif strategy == "buffer":
        result = {
            "strategy": "buffer",
            "description": "Increase safety stock by 50% for affected products",
            "estimated_cost_increase": "8-12% (working capital)",
            "lead_time_change_days": 0,
            "risk_reduction": 0.4,
            "implementation_time_days": base_lead_time,
            "recommendation": "Good for medium-term protection, high capital cost",
            "capital_required_estimate": f"${disrupted.get('revenue_impact', 0) * 0.15:,.0f}",
        }
    elif strategy == "expedite":
        result = {
            "strategy": "expedite",
            "description": "Rush existing orders with premium shipping",
            "estimated_cost_increase": "30-50%",
            "lead_time_change_days": -max(base_lead_time // 3, 2),
            "risk_reduction": 0.3,
            "implementation_time_days": 1,
            "recommendation": "Quick fix, expensive, doesn't solve root cause",
        }
    elif strategy == "dual_source":
        result = {
            "strategy": "dual_source",
            "description": f"Split orders 60/40 between {disrupted.get('name', 'primary')} and {alternative.get('name', 'secondary')}",
            "estimated_cost_increase": "5-10%",
            "lead_time_change_days": 2,
            "risk_reduction": 0.7,
            "implementation_time_days": 14,
            "recommendation": "Best long-term strategy for critical components",
        }
    else:
        result = {"error": f"Unknown strategy: {strategy}. Use: reroute, buffer, expedite, dual_source."}

    return json.dumps(result)


def model_buffer_stock_strategy(product_id: int, target_safety_days: int = 30) -> str:
    """Model the cost and impact of increasing buffer stock for a product.

    Args:
        product_id: The product to model buffer stock for.
        target_safety_days: Target number of days of safety stock.

    Returns:
        JSON with current vs proposed stock levels, cost estimate, and benefit analysis.
    """
    snapshot = _snapshot()
    products = {p["id"]: p for p in snapshot["products"]}
    inventories = {inv["product_id"]: inv for inv in snapshot["inventory"]}

    prod = products.get(product_id)
    inv = inventories.get(product_id)

    if not prod or not inv:
        return json.dumps({"error": f"Product {product_id} not found"})

    daily_usage = {"critical": 25, "high": 15, "medium": 10, "low": 5}
    usage = daily_usage.get(prod["criticality"], 10)

    current_qty = inv["quantity"]
    current_days = current_qty / usage if usage > 0 else 999
    target_qty = usage * target_safety_days
    additional_needed = max(target_qty - current_qty, 0)

    # Estimate unit cost from active POs
    avg_unit_cost = 50.0  # default
    for po in snapshot["purchase_orders"]:
        if po["product_id"] == product_id and po["unit_cost"] > 0:
            avg_unit_cost = po["unit_cost"]
            break

    investment = additional_needed * avg_unit_cost

    return json.dumps({
        "product": prod["name"],
        "criticality": prod["criticality"],
        "current_stock": current_qty,
        "current_days_of_supply": round(current_days, 1),
        "target_safety_days": target_safety_days,
        "target_stock_level": target_qty,
        "additional_units_needed": additional_needed,
        "estimated_unit_cost": avg_unit_cost,
        "total_investment": round(investment, 2),
        "annual_revenue_protected": prod["annual_revenue"],
        "roi_ratio": round(prod["annual_revenue"] / investment, 1) if investment > 0 else "N/A",
    })
