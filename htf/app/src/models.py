from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime


class Base(DeclarativeBase):
    pass


class Manufacturer(Base):
    __tablename__ = "manufacturers"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    industry = Column(String, nullable=False)
    region = Column(String, nullable=False)
    risk_appetite = Column(String, default="moderate")  # conservative, moderate, aggressive
    products = relationship("Product", back_populates="manufacturer")


class Supplier(Base):
    """
    Self-referential FK creates the supply chain graph.
    parent_supplier_id points to the DOWNSTREAM supplier this one feeds into.
    Tier 1 suppliers have parent_supplier_id = NULL (they supply directly to manufacturer).
    """
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    parent_supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    tier = Column(Integer, nullable=False)  # 1, 2, or 3
    region = Column(String, nullable=False)
    industry = Column(String, nullable=False)
    reliability_score = Column(Float, default=0.9)
    lead_time_days = Column(Integer, default=7)
    capacity_utilization = Column(Float, default=0.7)  # 0.0 - 1.0
    revenue_impact = Column(Float, default=0.0)  # annual $ at risk if this supplier fails
    is_single_source = Column(Boolean, default=False)  # SPOF flag

    # Self-referential relationship
    children = relationship("Supplier", backref="parent", remote_side=[id])
    products = relationship("SupplierProduct", back_populates="supplier")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sku = Column(String, unique=True, nullable=False)
    manufacturer_id = Column(Integer, ForeignKey("manufacturers.id"), nullable=False)
    criticality = Column(String, default="medium")  # low, medium, high, critical
    annual_revenue = Column(Float, default=0.0)

    manufacturer = relationship("Manufacturer", back_populates="products")
    suppliers = relationship("SupplierProduct", back_populates="product")


class SupplierProduct(Base):
    """Many-to-many: which suppliers provide components for which products."""
    __tablename__ = "supplier_products"

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    component_name = Column(String, nullable=False)
    is_critical = Column(Boolean, default=False)

    supplier = relationship("Supplier", back_populates="products")
    product = relationship("Product", back_populates="suppliers")


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, default=0)
    reorder_point = Column(Integer, default=100)
    safety_stock_days = Column(Integer, default=14)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_cost = Column(Float, default=0.0)
    status = Column(String, default="pending")  # pending, confirmed, shipped, delivered, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    expected_delivery = Column(DateTime, nullable=True)


class DisruptionLog(Base):
    """Records of past and current disruption events for memory/learning."""
    __tablename__ = "disruption_log"

    id = Column(Integer, primary_key=True)
    event_type = Column(String, nullable=False)  # geopolitical, natural_disaster, supplier_failure, shipping, cyber
    severity = Column(String, default="medium")  # low, medium, high, critical
    affected_region = Column(String, nullable=True)
    affected_supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    description = Column(Text, nullable=False)
    source = Column(String, nullable=True)  # news_api, erp_signal, manual
    mitigation_taken = Column(Text, nullable=True)
    mitigation_effectiveness = Column(Float, nullable=True)  # 0.0 - 1.0
    revenue_impact = Column(Float, nullable=True)
    occurred_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class DecisionLog(Base):
    """Audit trail of all agent decisions."""
    __tablename__ = "decision_log"

    id = Column(Integer, primary_key=True)
    agent_name = Column(String, nullable=False)
    decision = Column(String, nullable=False)
    reasoning = Column(Text, nullable=True)
    risk_score = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
