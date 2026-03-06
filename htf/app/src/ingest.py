"""
Data ingestion module for the Supply Chain Resilience Agent.

Supports importing supplier networks, products, ERP signals (inventory, POs),
and disruption history from CSV/JSON files or raw dicts.

Reference: AlMahri et al. (2025) "Automating Supply Chain Disruption Monitoring
via an Agentic AI Approach" — the extended supply chain network is a prerequisite
for framework operation and can be sourced from provider databases, internal
supplier records, or procurement data.
"""

import csv
import io
import json
from datetime import datetime
from sqlalchemy.orm import sessionmaker

from src.models import (
    Base, Manufacturer, Supplier, Product, SupplierProduct,
    Inventory, PurchaseOrder, DisruptionLog,
)


def _get_session(engine):
    return sessionmaker(bind=engine)()


def clear_all_data(engine):
    """Drop and recreate all tables. Use before a full re-import."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return {"status": "ok", "message": "All tables cleared and recreated."}


def _parse_csv(file_content: str) -> list[dict]:
    """Parse CSV string into list of dicts."""
    reader = csv.DictReader(io.StringIO(file_content))
    return [row for row in reader]


def _parse_input(data) -> list[dict]:
    """Accept CSV string, JSON string, list of dicts, or file-like object."""
    if isinstance(data, list):
        return data
    if isinstance(data, str):
        data = data.strip()
        if data.startswith("[") or data.startswith("{"):
            parsed = json.loads(data)
            return parsed if isinstance(parsed, list) else [parsed]
        return _parse_csv(data)
    # File-like object (e.g., Streamlit UploadedFile)
    content = data.read()
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    return _parse_input(content)


def _coerce(val, typ, default=None):
    """Safely coerce a value to a type."""
    if val is None or val == "":
        return default
    try:
        if typ == bool:
            if isinstance(val, str):
                return val.lower() in ("true", "1", "yes")
            return bool(val)
        return typ(val)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Manufacturer
# ---------------------------------------------------------------------------

def ingest_manufacturer(engine, data: dict) -> dict:
    """Import or update the manufacturer (focal company).

    data keys: name, industry, region, risk_appetite (optional)
    """
    session = _get_session(engine)
    try:
        existing = session.query(Manufacturer).first()
        if existing:
            existing.name = data.get("name", existing.name)
            existing.industry = data.get("industry", existing.industry)
            existing.region = data.get("region", existing.region)
            existing.risk_appetite = data.get("risk_appetite", existing.risk_appetite)
        else:
            session.add(Manufacturer(
                name=data["name"],
                industry=data["industry"],
                region=data["region"],
                risk_appetite=data.get("risk_appetite", "moderate"),
            ))
        session.commit()
        return {"status": "ok", "manufacturer": data.get("name")}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

def ingest_suppliers(engine, data, clear_existing=False) -> dict:
    """Import supplier network from CSV/JSON.

    Each row/object:
        name (required), tier (required), region (required), industry (required),
        parent_supplier_name (optional — resolved to ID after all suppliers loaded),
        reliability_score, lead_time_days, capacity_utilization,
        revenue_impact, is_single_source

    The parent_supplier_name field links to another supplier's name to build
    the graph edges (Tier 3 -> Tier 2 -> Tier 1 -> Manufacturer).
    """
    rows = _parse_input(data)
    session = _get_session(engine)
    try:
        if clear_existing:
            session.query(SupplierProduct).delete()
            session.query(PurchaseOrder).delete()
            session.query(Inventory).delete()
            session.query(DisruptionLog).filter(
                DisruptionLog.affected_supplier_id.isnot(None)
            ).update({DisruptionLog.affected_supplier_id: None})
            session.query(Supplier).delete()
            session.flush()

        # First pass: create all suppliers without parent links
        name_to_obj = {}
        for row in rows:
            sup = Supplier(
                name=row["name"],
                tier=_coerce(row.get("tier"), int, 1),
                region=row.get("region", "Unknown"),
                industry=row.get("industry", "general"),
                reliability_score=_coerce(row.get("reliability_score"), float, 0.9),
                lead_time_days=_coerce(row.get("lead_time_days"), int, 7),
                capacity_utilization=_coerce(row.get("capacity_utilization"), float, 0.7),
                revenue_impact=_coerce(row.get("revenue_impact"), float, 0.0),
                is_single_source=_coerce(row.get("is_single_source"), bool, False),
            )
            session.add(sup)
            session.flush()  # get ID
            name_to_obj[sup.name] = sup

        # Second pass: resolve parent links by name
        linked = 0
        for row in rows:
            parent_name = row.get("parent_supplier_name", "").strip()
            if parent_name and parent_name in name_to_obj:
                name_to_obj[row["name"]].parent_supplier_id = name_to_obj[parent_name].id
                linked += 1

        session.commit()
        return {
            "status": "ok",
            "suppliers_imported": len(rows),
            "graph_edges_linked": linked,
        }
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

def ingest_products(engine, data, clear_existing=False) -> dict:
    """Import products from CSV/JSON.

    Each row: name, sku, criticality (low/medium/high/critical), annual_revenue
    """
    rows = _parse_input(data)
    session = _get_session(engine)
    try:
        mfg = session.query(Manufacturer).first()
        if not mfg:
            return {"status": "error", "message": "Import manufacturer first."}

        if clear_existing:
            session.query(SupplierProduct).delete()
            session.query(Inventory).delete()
            session.query(Product).delete()
            session.flush()

        count = 0
        for row in rows:
            session.add(Product(
                name=row["name"],
                sku=row.get("sku", f"SKU-{count+1:03d}"),
                manufacturer_id=mfg.id,
                criticality=row.get("criticality", "medium"),
                annual_revenue=_coerce(row.get("annual_revenue"), float, 0.0),
            ))
            count += 1
        session.commit()
        return {"status": "ok", "products_imported": count}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Supplier-Product Links
# ---------------------------------------------------------------------------

def ingest_supplier_product_links(engine, data, clear_existing=False) -> dict:
    """Import supplier-product mappings from CSV/JSON.

    Each row: supplier_name, product_name, component_name, is_critical
    """
    rows = _parse_input(data)
    session = _get_session(engine)
    try:
        if clear_existing:
            session.query(SupplierProduct).delete()
            session.flush()

        # Build lookup maps
        suppliers = {s.name: s.id for s in session.query(Supplier).all()}
        products = {p.name: p.id for p in session.query(Product).all()}

        count = 0
        skipped = []
        for row in rows:
            s_name = row["supplier_name"]
            p_name = row["product_name"]
            if s_name not in suppliers:
                skipped.append(f"supplier not found: {s_name}")
                continue
            if p_name not in products:
                skipped.append(f"product not found: {p_name}")
                continue
            session.add(SupplierProduct(
                supplier_id=suppliers[s_name],
                product_id=products[p_name],
                component_name=row.get("component_name", "Component"),
                is_critical=_coerce(row.get("is_critical"), bool, False),
            ))
            count += 1
        session.commit()
        result = {"status": "ok", "links_imported": count}
        if skipped:
            result["warnings"] = skipped[:10]
        return result
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# ERP Signals: Inventory
# ---------------------------------------------------------------------------

def ingest_inventory(engine, data) -> dict:
    """Import or update inventory levels from ERP signals.

    Each row: product_name, quantity, reorder_point, safety_stock_days
    Updates existing rows or creates new ones.
    """
    rows = _parse_input(data)
    session = _get_session(engine)
    try:
        products = {p.name: p.id for p in session.query(Product).all()}
        updated = 0
        created = 0
        for row in rows:
            p_name = row["product_name"]
            if p_name not in products:
                continue
            pid = products[p_name]
            existing = session.query(Inventory).filter_by(product_id=pid).first()
            if existing:
                existing.quantity = _coerce(row.get("quantity"), int, existing.quantity)
                existing.reorder_point = _coerce(row.get("reorder_point"), int, existing.reorder_point)
                existing.safety_stock_days = _coerce(row.get("safety_stock_days"), int, existing.safety_stock_days)
                updated += 1
            else:
                session.add(Inventory(
                    product_id=pid,
                    quantity=_coerce(row.get("quantity"), int, 0),
                    reorder_point=_coerce(row.get("reorder_point"), int, 100),
                    safety_stock_days=_coerce(row.get("safety_stock_days"), int, 14),
                ))
                created += 1
        session.commit()
        return {"status": "ok", "updated": updated, "created": created}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# ERP Signals: Purchase Orders
# ---------------------------------------------------------------------------

def ingest_purchase_orders(engine, data) -> dict:
    """Import purchase orders from ERP system.

    Each row: supplier_name, product_name, quantity, unit_cost,
              status (pending/confirmed/shipped/delivered/cancelled),
              expected_delivery (ISO date string)
    """
    rows = _parse_input(data)
    session = _get_session(engine)
    try:
        suppliers = {s.name: s.id for s in session.query(Supplier).all()}
        products = {p.name: p.id for p in session.query(Product).all()}

        count = 0
        for row in rows:
            s_name = row.get("supplier_name", "")
            p_name = row.get("product_name", "")
            if s_name not in suppliers or p_name not in products:
                continue
            exp_del = None
            if row.get("expected_delivery"):
                try:
                    exp_del = datetime.fromisoformat(row["expected_delivery"])
                except ValueError:
                    pass
            session.add(PurchaseOrder(
                supplier_id=suppliers[s_name],
                product_id=products[p_name],
                quantity=_coerce(row.get("quantity"), int, 0),
                unit_cost=_coerce(row.get("unit_cost"), float, 0.0),
                status=row.get("status", "pending"),
                expected_delivery=exp_del,
            ))
            count += 1
        session.commit()
        return {"status": "ok", "orders_imported": count}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Disruption History
# ---------------------------------------------------------------------------

def ingest_disruption_history(engine, data) -> dict:
    """Import historical disruption events for the memory agent.

    Each row: event_type, severity, affected_region, affected_supplier_name,
              description, source, mitigation_taken, mitigation_effectiveness,
              revenue_impact, occurred_at (ISO), resolved_at (ISO)
    """
    rows = _parse_input(data)
    session = _get_session(engine)
    try:
        suppliers = {s.name: s.id for s in session.query(Supplier).all()}
        count = 0
        for row in rows:
            sup_id = None
            s_name = row.get("affected_supplier_name", "")
            if s_name in suppliers:
                sup_id = suppliers[s_name]

            occurred = None
            if row.get("occurred_at"):
                try:
                    occurred = datetime.fromisoformat(row["occurred_at"])
                except ValueError:
                    pass

            resolved = None
            if row.get("resolved_at"):
                try:
                    resolved = datetime.fromisoformat(row["resolved_at"])
                except ValueError:
                    pass

            session.add(DisruptionLog(
                event_type=row.get("event_type", "unknown"),
                severity=row.get("severity", "medium"),
                affected_region=row.get("affected_region"),
                affected_supplier_id=sup_id,
                description=row.get("description", ""),
                source=row.get("source", "imported"),
                mitigation_taken=row.get("mitigation_taken"),
                mitigation_effectiveness=_coerce(row.get("mitigation_effectiveness"), float),
                revenue_impact=_coerce(row.get("revenue_impact"), float),
                occurred_at=occurred,
                resolved_at=resolved,
            ))
            count += 1
        session.commit()
        return {"status": "ok", "disruptions_imported": count}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Full import from a single JSON bundle
# ---------------------------------------------------------------------------

def ingest_full_bundle(engine, bundle: dict, clear=True) -> dict:
    """Import a complete supply chain dataset from a single JSON object.

    Expected keys (all optional):
        manufacturer: {...}
        suppliers: [...]
        products: [...]
        supplier_product_links: [...]
        inventory: [...]
        purchase_orders: [...]
        disruption_history: [...]
    """
    results = {}

    if clear:
        results["clear"] = clear_all_data(engine)
        Base.metadata.create_all(engine)

    if "manufacturer" in bundle:
        results["manufacturer"] = ingest_manufacturer(engine, bundle["manufacturer"])

    if "suppliers" in bundle:
        results["suppliers"] = ingest_suppliers(engine, bundle["suppliers"])

    if "products" in bundle:
        results["products"] = ingest_products(engine, bundle["products"])

    if "supplier_product_links" in bundle:
        results["links"] = ingest_supplier_product_links(engine, bundle["supplier_product_links"])

    if "inventory" in bundle:
        results["inventory"] = ingest_inventory(engine, bundle["inventory"])

    if "purchase_orders" in bundle:
        results["purchase_orders"] = ingest_purchase_orders(engine, bundle["purchase_orders"])

    if "disruption_history" in bundle:
        results["disruptions"] = ingest_disruption_history(engine, bundle["disruption_history"])

    return results
