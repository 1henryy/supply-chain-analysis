import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.db_service import (
    get_full_supply_chain_snapshot as _snapshot,
    get_suppliers_by_industry,
)


def query_suppliers_by_industry(industry: str) -> str:
    """Find all suppliers in a specific industry sector.

    Args:
        industry: Industry to filter by. Options: semiconductor, pcb_assembly, pcb_raw,
                  passive_components, battery, battery_materials, sensors, optics,
                  mining, chemicals.

    Returns:
        JSON with list of matching suppliers including reliability and region.
    """
    result = get_suppliers_by_industry(industry)
    return json.dumps({"industry": industry, "suppliers": result, "count": len(result)})


def assess_inventory_risk() -> str:
    """Assess inventory risk for all products by comparing stock levels to reorder points.

    Returns:
        JSON with per-product risk assessment including days of supply remaining,
        whether stock is below reorder point, and risk classification.
    """
    snapshot = _snapshot()
    products = {p["id"]: p for p in snapshot["products"]}
    inventories = {inv["product_id"]: inv for inv in snapshot["inventory"]}

    # Average daily usage estimate (based on annual revenue / avg unit price)
    # Simplified: assume ~20 units/day consumption for critical products
    daily_usage_estimates = {"critical": 25, "high": 15, "medium": 10, "low": 5}

    risk_assessment = []
    for pid, prod in products.items():
        inv = inventories.get(pid, {})
        qty = inv.get("quantity", 0)
        reorder = inv.get("reorder_point", 0)
        safety_days = inv.get("safety_stock_days", 14)

        daily_usage = daily_usage_estimates.get(prod["criticality"], 10)
        days_of_supply = qty / daily_usage if daily_usage > 0 else 999

        if qty < reorder * 0.5:
            risk_level = "critical"
        elif qty < reorder:
            risk_level = "high"
        elif days_of_supply < safety_days:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Check if there's an active PO for this product
        active_pos = [
            po for po in snapshot["purchase_orders"]
            if po["product_id"] == pid
        ]

        risk_assessment.append({
            "product_id": pid,
            "product_name": prod["name"],
            "criticality": prod["criticality"],
            "current_stock": qty,
            "reorder_point": reorder,
            "days_of_supply": round(days_of_supply, 1),
            "safety_stock_days": safety_days,
            "risk_level": risk_level,
            "active_purchase_orders": len(active_pos),
            "annual_revenue": prod["annual_revenue"],
        })

    risk_assessment.sort(key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}[x["risk_level"]])

    return json.dumps({"inventory_risk": risk_assessment})


def map_suppliers_to_products(supplier_ids: str) -> str:
    """Map a set of disrupted supplier IDs to the products they affect.

    Args:
        supplier_ids: Comma-separated list of supplier IDs (e.g. "1,5,13").

    Returns:
        JSON with affected products and their supply chain dependencies.
    """
    try:
        ids = [int(x.strip()) for x in supplier_ids.split(",")]
    except ValueError:
        return json.dumps({"error": "Invalid supplier_ids format. Use comma-separated integers."})

    snapshot = _snapshot()
    id_set = set(ids)

    affected = []
    products = {p["id"]: p for p in snapshot["products"]}

    for link in snapshot["supplier_product_links"]:
        if link["supplier_id"] in id_set:
            pid = link["product_id"]
            prod = products.get(pid, {})
            affected.append({
                "product_id": pid, 
                "product_name": prod.get("name", "Unknown"),
                "criticality": prod.get("criticality", "unknown"),
                "affected_by_supplier_id": link["supplier_id"],
                "component": link["component_name"],
                "is_critical_component": link["is_critical"],
                "annual_revenue": prod.get("annual_revenue", 0),
            })

    return json.dumps({
        "queried_supplier_ids": ids,
        "affected_products": affected,
        "num_affected": len(affected),
    })
