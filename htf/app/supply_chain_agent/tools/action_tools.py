"""
Tools for Agent 7: Action Execution.
Draft emails, generate PO adjustments, create alerts, record events.
"""

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
