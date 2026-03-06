import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

from src.models import (
    Base, Manufacturer, Supplier, SupplierProduct, Product,
    Inventory, PurchaseOrder, DisruptionLog, DecisionLog,
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/supply_chain.db")
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# READ helpers (used by agent tools -- agents ONLY read)
# ---------------------------------------------------------------------------

def get_full_supply_chain_snapshot() -> dict:
    """Complete snapshot of the supply chain state for agents."""
    with get_session() as s:
        manufacturer = s.query(Manufacturer).first()
        suppliers = s.query(Supplier).all()
        products = s.query(Product).all()
        inventories = s.query(Inventory).all()
        pos = s.query(PurchaseOrder).filter(
            PurchaseOrder.status.in_(["pending", "confirmed", "shipped"])
        ).all()
        sp_links = s.query(SupplierProduct).all()

        return {
            "manufacturer": {
                "id": manufacturer.id,
                "name": manufacturer.name,
                "industry": manufacturer.industry,
                "region": manufacturer.region,
                "risk_appetite": manufacturer.risk_appetite,
            } if manufacturer else {},
            "suppliers": [
                {
                    "id": sup.id,
                    "name": sup.name,
                    "parent_supplier_id": sup.parent_supplier_id,
                    "tier": sup.tier,
                    "region": sup.region,
                    "industry": sup.industry,
                    "reliability_score": sup.reliability_score,
                    "lead_time_days": sup.lead_time_days,
                    "capacity_utilization": sup.capacity_utilization,
                    "revenue_impact": sup.revenue_impact,
                    "is_single_source": sup.is_single_source,
                }
                for sup in suppliers
            ],
            "products": [
                {
                    "id": p.id,
                    "name": p.name,
                    "sku": p.sku,
                    "criticality": p.criticality,
                    "annual_revenue": p.annual_revenue,
                }
                for p in products
            ],
            "inventory": [
                {
                    "product_id": inv.product_id,
                    "quantity": inv.quantity,
                    "reorder_point": inv.reorder_point,
                    "safety_stock_days": inv.safety_stock_days,
                }
                for inv in inventories
            ],
            "purchase_orders": [
                {
                    "id": po.id,
                    "supplier_id": po.supplier_id,
                    "product_id": po.product_id,
                    "quantity": po.quantity,
                    "unit_cost": po.unit_cost,
                    "status": po.status,
                    "created_at": po.created_at.isoformat() if po.created_at else None,
                    "expected_delivery": po.expected_delivery.isoformat() if po.expected_delivery else None,
                }
                for po in pos
            ],
            "supplier_product_links": [
                {
                    "supplier_id": sp.supplier_id,
                    "product_id": sp.product_id,
                    "component_name": sp.component_name,
                    "is_critical": sp.is_critical,
                }
                for sp in sp_links
            ],
        }


def get_supplier_graph_edges() -> list[dict]:
    """Return list of edges {child_id, parent_id} for graph algorithms."""
    with get_session() as s:
        suppliers = s.query(Supplier).filter(Supplier.parent_supplier_id.isnot(None)).all()
        return [
            {"child_id": sup.id, "parent_id": sup.parent_supplier_id}
            for sup in suppliers
        ]


def get_suppliers_by_region(region: str) -> list[dict]:
    with get_session() as s:
        suppliers = s.query(Supplier).filter(Supplier.region == region).all()
        return [
            {"id": sup.id, "name": sup.name, "tier": sup.tier, "industry": sup.industry}
            for sup in suppliers
        ]


def get_suppliers_by_industry(industry: str) -> list[dict]:
    with get_session() as s:
        suppliers = s.query(Supplier).filter(Supplier.industry == industry).all()
        return [
            {"id": sup.id, "name": sup.name, "tier": sup.tier, "region": sup.region,
             "reliability_score": sup.reliability_score}
            for sup in suppliers
        ]


def get_past_disruptions(limit: int = 20) -> list[dict]:
    with get_session() as s:
        logs = (
            s.query(DisruptionLog)
            .order_by(DisruptionLog.occurred_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": d.id,
                "event_type": d.event_type,
                "severity": d.severity,
                "affected_region": d.affected_region,
                "affected_supplier_id": d.affected_supplier_id,
                "description": d.description,
                "mitigation_taken": d.mitigation_taken,
                "mitigation_effectiveness": d.mitigation_effectiveness,
                "revenue_impact": d.revenue_impact,
                "occurred_at": d.occurred_at.isoformat() if d.occurred_at else None,
                "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
            }
            for d in logs
        ]


def get_recent_decisions(limit: int = 10) -> list[dict]:
    with get_session() as s:
        logs = (
            s.query(DecisionLog)
            .order_by(DecisionLog.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": d.id,
                "agent_name": d.agent_name,
                "decision": d.decision,
                "reasoning": d.reasoning,
                "risk_score": d.risk_score,
                "confidence": d.confidence,
                "timestamp": d.timestamp.isoformat() if d.timestamp else None,
            }
            for d in logs
        ]


# ---------------------------------------------------------------------------
# WRITE helpers (used ONLY by execution layer)
# ---------------------------------------------------------------------------

def create_purchase_order(supplier_id, product_id, quantity, unit_cost=0.0, expected_delivery=None):
    with get_session() as s:
        po = PurchaseOrder(
            supplier_id=supplier_id,
            product_id=product_id,
            quantity=quantity,
            unit_cost=unit_cost,
            status="pending",
            expected_delivery=expected_delivery,
        )
        s.add(po)
        s.flush()
        return po.id


def log_decision(agent_name, decision, reasoning, risk_score=None, confidence=None):
    with get_session() as s:
        entry = DecisionLog(
            agent_name=agent_name,
            decision=decision,
            reasoning=reasoning,
            risk_score=risk_score,
            confidence=confidence,
        )
        s.add(entry)
        s.flush()
        return entry.id


def update_supplier_from_disruption(supplier_id, reliability_delta, lead_time_delta,
                                    capacity_delta):
    """Mutate a supplier's state in response to a confirmed disruption."""
    with get_session() as s:
        sup = s.query(Supplier).filter(Supplier.id == supplier_id).first()
        if not sup:
            return None
        sup.reliability_score = max(0.0, min(1.0, sup.reliability_score + reliability_delta))
        sup.lead_time_days = max(1, sup.lead_time_days + lead_time_delta)
        sup.capacity_utilization = max(0.0, min(1.0, sup.capacity_utilization + capacity_delta))
        s.flush()
        return {
            "id": sup.id,
            "name": sup.name,
            "reliability_score": sup.reliability_score,
            "lead_time_days": sup.lead_time_days,
            "capacity_utilization": sup.capacity_utilization,
        }


def adjust_inventory(product_id, quantity_delta):
    """Adjust inventory quantity for a product (negative to reduce)."""
    with get_session() as s:
        inv = s.query(Inventory).filter(Inventory.product_id == product_id).first()
        if not inv:
            return None
        inv.quantity = max(0, inv.quantity + quantity_delta)
        s.flush()
        return {"product_id": product_id, "new_quantity": inv.quantity}


def record_disruption_event(event_type, description, severity="medium",
                            affected_region=None, affected_supplier_id=None,
                            source="news_api"):
    with get_session() as s:
        entry = DisruptionLog(
            event_type=event_type,
            severity=severity,
            affected_region=affected_region,
            affected_supplier_id=affected_supplier_id,
            description=description,
            source=source,
        )
        s.add(entry)
        s.flush()
        return entry.id
