import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.db_service import (
    get_full_supply_chain_snapshot as _snapshot,
    create_purchase_order,
    log_decision,
    record_disruption_event,
    update_supplier_from_disruption,
    adjust_inventory,
)


def draft_supplier_email(
    supplier_id: int,
    subject: str,
    urgency: str = "normal",
    context: str = "",
) -> str:
    """Draft a professional email to a supplier regarding supply chain concerns.

    Args:
        supplier_id: The supplier to contact.
        subject: Email subject line.
        urgency: Email urgency: 'low', 'normal', 'high', 'critical'.
        context: Additional context about the situation to include.

    Returns:
        JSON with drafted email (to, subject, body) ready for human review.
    """
    snapshot = _snapshot()
    supplier_map = {s["id"]: s for s in snapshot["suppliers"]}
    supplier = supplier_map.get(supplier_id)
    mfg = snapshot["manufacturer"]

    if not supplier:
        return json.dumps({"error": f"Supplier {supplier_id} not found"})

    urgency_prefix = {
        "critical": "[URGENT] ",
        "high": "[HIGH PRIORITY] ",
        "normal": "",
        "low": "",
    }

    body = f"""Dear {supplier['name']} Team,

I am writing on behalf of {mfg.get('name', 'our company')} regarding {subject.lower()}.

{context}

Given the current situation, we would like to:
1. Confirm your current production capacity and lead time estimates
2. Discuss any potential supply disruptions we should be aware of
3. Explore options for securing our supply requirements

Please respond at your earliest convenience{' - this is time-critical' if urgency in ('high', 'critical') else ''}.

Best regards,
Supply Chain Management Team
{mfg.get('name', '')}"""

    return json.dumps({
        "status": "drafted",
        "email": {
            "to": f"procurement@{supplier['name'].lower().replace(' ', '')}.com",
            "subject": f"{urgency_prefix.get(urgency, '')}{subject}",
            "body": body,
            "urgency": urgency,
        },
        "requires_human_review": True,
    })


def generate_po_adjustment(
    product_id: int,
    supplier_id: int,
    quantity: int,
    reason: str,
) -> str:
    """Generate a purchase order adjustment recommendation.

    Args:
        product_id: The product to order.
        supplier_id: The supplier to order from.
        quantity: Number of units to order.
        reason: Business justification for the order.

    Returns:
        JSON with PO details. Note: PO is NOT executed until human approval.
    """
    snapshot = _snapshot()
    supplier_map = {s["id"]: s for s in snapshot["suppliers"]}
    product_map = {p["id"]: p for p in snapshot["products"]}

    supplier = supplier_map.get(supplier_id)
    product = product_map.get(product_id)

    if not supplier or not product:
        return json.dumps({"error": "Invalid supplier_id or product_id"})

    # Estimate cost from existing POs or default
    unit_cost = 50.0
    for po in snapshot["purchase_orders"]:
        if po["product_id"] == product_id and po["unit_cost"] > 0:
            unit_cost = po["unit_cost"]
            break

    total_cost = quantity * unit_cost
    lead_time = supplier["lead_time_days"]

    return json.dumps({
        "status": "pending_approval",
        "po_recommendation": {
            "product": product["name"],
            "product_id": product_id,
            "supplier": supplier["name"],
            "supplier_id": supplier_id,
            "quantity": quantity,
            "estimated_unit_cost": unit_cost,
            "estimated_total_cost": total_cost,
            "lead_time_days": lead_time,
            "reason": reason,
        },
        "requires_human_approval": total_cost > 10000 or quantity > 500,
    })


def create_escalation_alert(
    severity: str,
    title: str,
    description: str,
    recommended_action: str,
    revenue_at_risk: float = 0.0,
) -> str:
    """Create an escalation alert for supply chain leadership.

    Args:
        severity: Alert severity: 'low', 'medium', 'high', 'critical'.
        title: Short title for the alert.
        description: Detailed description of the situation.
        recommended_action: What action should be taken.
        revenue_at_risk: Estimated revenue at risk in dollars.

    Returns:
        JSON with the alert details and routing information.
    """
    routing = {
        "low": "Supply Chain Analyst",
        "medium": "Supply Chain Manager",
        "high": "VP Supply Chain",
        "critical": "CFO + VP Supply Chain + Board Notification",
    }

    alert = {
        "alert_id": f"ESC-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        "severity": severity,
        "title": title,
        "description": description,
        "recommended_action": recommended_action,
        "revenue_at_risk": revenue_at_risk,
        "routed_to": routing.get(severity, "Supply Chain Manager"),
        "board_notification": revenue_at_risk > 5_000_000,
        "created_at": datetime.utcnow().isoformat(),
        "status": "open",
    }

    # Log the alert
    log_decision(
        agent_name="escalation_system",
        decision=f"ALERT: {severity.upper()} - {title}",
        reasoning=description,
        risk_score={"low": 0.2, "medium": 0.5, "high": 0.7, "critical": 0.9}.get(severity, 0.5),
    )

    return json.dumps(alert)


def record_disruption(
    event_type: str,
    description: str,
    severity: str = "medium",
    affected_region: str = "",
    affected_supplier_id: int = 0,
) -> str:
    """Record a new disruption event in the system for future memory/learning.

    Args:
        event_type: Type: 'geopolitical', 'natural_disaster', 'supplier_failure', 'shipping', 'cyber'.
        description: Description of the disruption event.
        severity: Severity: 'low', 'medium', 'high', 'critical'.
        affected_region: Geographic region affected.
        affected_supplier_id: Specific supplier affected (0 if none).

    Returns:
        JSON confirmation with the recorded event ID.
    """
    event_id = record_disruption_event(
        event_type=event_type,
        description=description,
        severity=severity,
        affected_region=affected_region or None,
        affected_supplier_id=affected_supplier_id or None,
        source="agent_detected",
    )

    return json.dumps({
        "status": "recorded",
        "event_id": event_id,
        "event_type": event_type,
        "severity": severity,
    })


def apply_disruption_impact(
    supplier_id: int,
    severity: str,
    disruption_type: str = "general",
) -> str:
    """Apply a confirmed disruption's impact to a supplier in the database.

    Degrades the supplier's reliability score, increases lead time, and raises
    capacity utilization based on severity. Also reduces inventory for all
    products sourced from this supplier.

    Args:
        supplier_id: The supplier affected by the disruption.
        severity: Disruption severity: 'low', 'medium', 'high', 'critical'.
        disruption_type: Type of disruption for tuning impact factors.
            Options: 'geopolitical', 'natural_disaster', 'supplier_failure',
            'shipping', 'cyber', 'general'.

    Returns:
        JSON with the updated supplier state and any inventory adjustments made.
    """
    severity_factors = {
        "low":      {"reliability": -0.05, "lead_time": 2,  "capacity": 0.05, "inv_pct": 0.05},
        "medium":   {"reliability": -0.10, "lead_time": 5,  "capacity": 0.10, "inv_pct": 0.10},
        "high":     {"reliability": -0.20, "lead_time": 10, "capacity": 0.20, "inv_pct": 0.20},
        "critical": {"reliability": -0.35, "lead_time": 21, "capacity": 0.35, "inv_pct": 0.35},
    }
    factors = severity_factors.get(severity, severity_factors["medium"])

    # Shipping disruptions hit lead time harder; cyber/supplier_failure hit reliability harder
    if disruption_type == "shipping":
        factors["lead_time"] = int(factors["lead_time"] * 1.5)
    elif disruption_type in ("cyber", "supplier_failure"):
        factors["reliability"] *= 1.5

    updated = update_supplier_from_disruption(
        supplier_id,
        reliability_delta=factors["reliability"],
        lead_time_delta=factors["lead_time"],
        capacity_delta=factors["capacity"],
    )

    if not updated:
        return json.dumps({"error": f"Supplier {supplier_id} not found"})

    # Reduce inventory for products sourced from this supplier
    snapshot = _snapshot()
    inv_map = {inv["product_id"]: inv for inv in snapshot["inventory"]}
    inv_adjustments = []

    for link in snapshot["supplier_product_links"]:
        if link["supplier_id"] == supplier_id:
            inv = inv_map.get(link["product_id"])
            if inv:
                reduction = -int(inv["quantity"] * factors["inv_pct"])
                result = adjust_inventory(link["product_id"], reduction)
                if result:
                    inv_adjustments.append({
                        "product_id": link["product_id"],
                        "component": link["component_name"],
                        "units_lost": abs(reduction),
                        "new_quantity": result["new_quantity"],
                    })

    log_decision(
        agent_name="disruption_impact",
        decision=f"Applied {severity} {disruption_type} impact to supplier {supplier_id}",
        reasoning=f"Reliability {factors['reliability']:+.2f}, lead time {factors['lead_time']:+d}d, "
                  f"capacity {factors['capacity']:+.2f}, inventory reduced for {len(inv_adjustments)} products",
        risk_score={"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 0.95}.get(severity, 0.5),
    )

    return json.dumps({
        "status": "applied",
        "supplier_updated": updated,
        "inventory_adjustments": inv_adjustments,
        "severity": severity,
        "disruption_type": disruption_type,
    })


def trigger_emergency_reorder(product_id: int) -> str:
    """Create an emergency purchase order for a product that has fallen below its reorder point.

    Automatically selects the most reliable supplier for the product and creates
    a PO to bring inventory back to the safety stock target.

    Args:
        product_id: The product that needs restocking.

    Returns:
        JSON with the created PO details or an explanation if no action was needed.
    """
    snapshot = _snapshot()
    products = {p["id"]: p for p in snapshot["products"]}
    inv_map = {inv["product_id"]: inv for inv in snapshot["inventory"]}
    supplier_map = {s["id"]: s for s in snapshot["suppliers"]}

    prod = products.get(product_id)
    inv = inv_map.get(product_id)
    if not prod or not inv:
        return json.dumps({"error": f"Product {product_id} not found"})

    if inv["quantity"] >= inv["reorder_point"]:
        return json.dumps({
            "status": "no_action",
            "reason": f"Stock ({inv['quantity']}) is above reorder point ({inv['reorder_point']})",
        })

    # Find the best supplier for this product
    product_suppliers = [
        link for link in snapshot["supplier_product_links"]
        if link["product_id"] == product_id
    ]
    if not product_suppliers:
        return json.dumps({"error": "No suppliers linked to this product"})

    best_link = max(
        product_suppliers,
        key=lambda l: supplier_map.get(l["supplier_id"], {}).get("reliability_score", 0),
    )
    best_supplier = supplier_map.get(best_link["supplier_id"])

    # Order enough to reach safety stock target
    daily_usage = {"critical": 25, "high": 15, "medium": 10, "low": 5}
    usage = daily_usage.get(prod["criticality"], 10)
    target_qty = usage * inv["safety_stock_days"]
    order_qty = max(target_qty - inv["quantity"], usage * 7)  # at least 1 week

    # Estimate unit cost
    unit_cost = 50.0
    for po in snapshot["purchase_orders"]:
        if po["product_id"] == product_id and po["unit_cost"] > 0:
            unit_cost = po["unit_cost"]
            break

    from datetime import timedelta
    delivery = datetime.utcnow() + timedelta(days=best_supplier["lead_time_days"])

    po_id = create_purchase_order(
        supplier_id=best_supplier["id"],
        product_id=product_id,
        quantity=order_qty,
        unit_cost=unit_cost,
        expected_delivery=delivery,
    )

    log_decision(
        agent_name="emergency_reorder",
        decision=f"Emergency PO #{po_id} for {order_qty} units of {prod['name']}",
        reasoning=f"Stock ({inv['quantity']}) below reorder point ({inv['reorder_point']}). "
                  f"Ordering from {best_supplier['name']} (reliability {best_supplier['reliability_score']})",
        risk_score=0.7,
    )

    return json.dumps({
        "status": "po_created",
        "po_id": po_id,
        "product": prod["name"],
        "supplier": best_supplier["name"],
        "quantity": order_qty,
        "unit_cost": unit_cost,
        "total_cost": round(order_qty * unit_cost, 2),
        "expected_delivery": delivery.isoformat(),
    })
