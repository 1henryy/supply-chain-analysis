"""
Seed database with a realistic multi-tier supplier network for an
automotive electronics manufacturer.

Graph structure (16 suppliers, 3 tiers):

  Manufacturer: TechDrive Motors
        |
  Tier 1 (direct suppliers):
    [1] ChipFlow Semiconductors   -- semiconductor modules
    [2] CircuitPro Assembly        -- PCB assemblies
    [3] PowerCell Systems          -- battery management units
    [4] SensorTech Solutions       -- ADAS sensor modules
        |
  Tier 2 (supply to Tier 1):
    [5] SiliconBase Foundry        -> ChipFlow (#1)
    [6] WaferTech Inc              -> ChipFlow (#1)
    [7] CopperLine PCB             -> CircuitPro (#2)
    [8] ResistorWorld              -> CircuitPro (#2)
    [9] LithiumCore                -> PowerCell (#3)
    [10] CellChem Materials        -> PowerCell (#3)
    [11] OpticsFirst               -> SensorTech (#4)
    [12] MicroLens Corp            -> SensorTech (#4)
        |
  Tier 3 (supply to Tier 2):
    [13] RareEarth Mining Co       -> SiliconBase (#5)  ** single source **
    [14] PureGas Supplies          -> WaferTech (#6)
    [15] CopperMine Ltd            -> CopperLine (#7)
    [16] ChemReagent Corp          -> LithiumCore (#9)

Products (4):
  AutoPilot ECU         -- ChipFlow + CircuitPro
  BatteryGuard BMS      -- ChipFlow + PowerCell
  SafeView ADAS         -- SensorTech + CircuitPro
  DriveCore Processor   -- ChipFlow (single-supplier dependency)
"""

import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.models import (
    Base, Manufacturer, Supplier, Product, SupplierProduct,
    Inventory, PurchaseOrder, DisruptionLog,
)


def init_database(db_url: str | None = None) -> "Engine":
    os.makedirs("data", exist_ok=True)
    url = db_url or os.getenv("DATABASE_URL", "sqlite:///data/supply_chain.db")
    eng = create_engine(url, echo=False)
    Base.metadata.create_all(eng)
    return eng


def seed_data(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        if session.query(Manufacturer).count() > 0:
            print("Database already seeded.")
            return

        # ── Manufacturer ──────────────────────────────────────────────
        mfg = Manufacturer(
            id=1, name="TechDrive Motors",
            industry="automotive_electronics", region="Germany",
            risk_appetite="moderate",
        )
        session.add(mfg)

        # ── Suppliers (3-tier graph) ──────────────────────────────────
        suppliers = [
            # Tier 1 - direct to manufacturer
            Supplier(id=1,  name="ChipFlow Semiconductors", parent_supplier_id=None, tier=1,
                     region="Taiwan", industry="semiconductor",
                     reliability_score=0.92, lead_time_days=14,
                     capacity_utilization=0.85, revenue_impact=12_000_000,
                     is_single_source=False),
            Supplier(id=2,  name="CircuitPro Assembly", parent_supplier_id=None, tier=1,
                     region="South Korea", industry="pcb_assembly",
                     reliability_score=0.95, lead_time_days=10,
                     capacity_utilization=0.70, revenue_impact=8_000_000,
                     is_single_source=False),
            Supplier(id=3,  name="PowerCell Systems", parent_supplier_id=None, tier=1,
                     region="China", industry="battery",
                     reliability_score=0.88, lead_time_days=21,
                     capacity_utilization=0.90, revenue_impact=6_000_000,
                     is_single_source=False),
            Supplier(id=4,  name="SensorTech Solutions", parent_supplier_id=None, tier=1,
                     region="Japan", industry="sensors",
                     reliability_score=0.96, lead_time_days=12,
                     capacity_utilization=0.65, revenue_impact=5_000_000,
                     is_single_source=False),

            # Tier 2 - supply to Tier 1
            Supplier(id=5,  name="SiliconBase Foundry", parent_supplier_id=1, tier=2,
                     region="Taiwan", industry="semiconductor",
                     reliability_score=0.90, lead_time_days=28,
                     capacity_utilization=0.92, revenue_impact=4_000_000,
                     is_single_source=False),
            Supplier(id=6,  name="WaferTech Inc", parent_supplier_id=1, tier=2,
                     region="USA", industry="semiconductor",
                     reliability_score=0.93, lead_time_days=21,
                     capacity_utilization=0.75, revenue_impact=3_500_000,
                     is_single_source=False),
            Supplier(id=7,  name="CopperLine PCB", parent_supplier_id=2, tier=2,
                     region="China", industry="pcb_raw",
                     reliability_score=0.87, lead_time_days=18,
                     capacity_utilization=0.80, revenue_impact=2_500_000,
                     is_single_source=False),
            Supplier(id=8,  name="ResistorWorld", parent_supplier_id=2, tier=2,
                     region="Malaysia", industry="passive_components",
                     reliability_score=0.94, lead_time_days=10,
                     capacity_utilization=0.60, revenue_impact=1_000_000,
                     is_single_source=False),
            Supplier(id=9,  name="LithiumCore", parent_supplier_id=3, tier=2,
                     region="Chile", industry="battery_materials",
                     reliability_score=0.85, lead_time_days=30,
                     capacity_utilization=0.88, revenue_impact=3_000_000,
                     is_single_source=False),
            Supplier(id=10, name="CellChem Materials", parent_supplier_id=3, tier=2,
                     region="China", industry="battery_materials",
                     reliability_score=0.82, lead_time_days=25,
                     capacity_utilization=0.95, revenue_impact=2_000_000,
                     is_single_source=False),
            Supplier(id=11, name="OpticsFirst", parent_supplier_id=4, tier=2,
                     region="Japan", industry="optics",
                     reliability_score=0.97, lead_time_days=14,
                     capacity_utilization=0.55, revenue_impact=1_500_000,
                     is_single_source=False),
            Supplier(id=12, name="MicroLens Corp", parent_supplier_id=4, tier=2,
                     region="Germany", industry="optics",
                     reliability_score=0.91, lead_time_days=12,
                     capacity_utilization=0.70, revenue_impact=1_200_000,
                     is_single_source=False),

            # Tier 3 - supply to Tier 2
            Supplier(id=13, name="RareEarth Mining Co", parent_supplier_id=5, tier=3,
                     region="China", industry="mining",
                     reliability_score=0.78, lead_time_days=45,
                     capacity_utilization=0.95, revenue_impact=5_000_000,
                     is_single_source=True),  # SPOF!
            Supplier(id=14, name="PureGas Supplies", parent_supplier_id=6, tier=3,
                     region="USA", industry="chemicals",
                     reliability_score=0.95, lead_time_days=7,
                     capacity_utilization=0.50, revenue_impact=800_000,
                     is_single_source=False),
            Supplier(id=15, name="CopperMine Ltd", parent_supplier_id=7, tier=3,
                     region="Peru", industry="mining",
                     reliability_score=0.80, lead_time_days=35,
                     capacity_utilization=0.85, revenue_impact=1_500_000,
                     is_single_source=True),  # SPOF!
            Supplier(id=16, name="ChemReagent Corp", parent_supplier_id=9, tier=3,
                     region="India", industry="chemicals",
                     reliability_score=0.86, lead_time_days=20,
                     capacity_utilization=0.72, revenue_impact=900_000,
                     is_single_source=False),
        ]
        session.add_all(suppliers)

        # ── Products ──────────────────────────────────────────────────
        products = [
            Product(id=1, name="AutoPilot ECU", sku="AP-ECU-001",
                    manufacturer_id=1, criticality="critical", annual_revenue=15_000_000),
            Product(id=2, name="BatteryGuard BMS", sku="BG-BMS-002",
                    manufacturer_id=1, criticality="high", annual_revenue=10_000_000),
            Product(id=3, name="SafeView ADAS", sku="SV-ADAS-003",
                    manufacturer_id=1, criticality="high", annual_revenue=8_000_000),
            Product(id=4, name="DriveCore Processor", sku="DC-PROC-004",
                    manufacturer_id=1, criticality="critical", annual_revenue=20_000_000),
        ]
        session.add_all(products)

        # ── Supplier-Product links ────────────────────────────────────
        sp_links = [
            # AutoPilot ECU needs chips + PCBs
            SupplierProduct(supplier_id=1, product_id=1, component_name="MCU Chip Module", is_critical=True),
            SupplierProduct(supplier_id=2, product_id=1, component_name="Main PCB Assembly", is_critical=True),
            # BatteryGuard BMS needs chips + battery mgmt
            SupplierProduct(supplier_id=1, product_id=2, component_name="BMS Controller Chip", is_critical=True),
            SupplierProduct(supplier_id=3, product_id=2, component_name="Battery Cell Module", is_critical=True),
            # SafeView ADAS needs sensors + PCBs
            SupplierProduct(supplier_id=4, product_id=3, component_name="LiDAR Sensor Array", is_critical=True),
            SupplierProduct(supplier_id=2, product_id=3, component_name="Sensor PCB Board", is_critical=False),
            # DriveCore Processor -- single supplier dependency on ChipFlow
            SupplierProduct(supplier_id=1, product_id=4, component_name="SoC Processor Die", is_critical=True),
        ]
        session.add_all(sp_links)

        # ── Inventory ─────────────────────────────────────────────────
        inventories = [
            Inventory(product_id=1, quantity=320,  reorder_point=200, safety_stock_days=14),
            Inventory(product_id=2, quantity=85,   reorder_point=150, safety_stock_days=21),
            Inventory(product_id=3, quantity=200,  reorder_point=120, safety_stock_days=14),
            Inventory(product_id=4, quantity=40,   reorder_point=100, safety_stock_days=30),
        ]
        session.add_all(inventories)

        # ── Purchase Orders ───────────────────────────────────────────
        now = datetime.utcnow()
        pos = [
            PurchaseOrder(supplier_id=1, product_id=1, quantity=200, unit_cost=45.0,
                          status="confirmed",
                          created_at=now - timedelta(days=5),
                          expected_delivery=now + timedelta(days=9)),
            PurchaseOrder(supplier_id=3, product_id=2, quantity=150, unit_cost=120.0,
                          status="shipped",
                          created_at=now - timedelta(days=10),
                          expected_delivery=now + timedelta(days=18)),
            PurchaseOrder(supplier_id=1, product_id=4, quantity=100, unit_cost=85.0,
                          status="pending",
                          created_at=now - timedelta(days=2),
                          expected_delivery=now + timedelta(days=12)),
        ]
        session.add_all(pos)

        # ── Historical Disruptions (for memory agent) ─────────────────
        disruptions = [
            DisruptionLog(
                event_type="natural_disaster", severity="critical",
                affected_region="Taiwan", affected_supplier_id=1,
                description="Magnitude 7.2 earthquake in Hualien County disrupted semiconductor fabs. ChipFlow production halted for 3 weeks.",
                source="historical", mitigation_taken="Emergency sourcing from WaferTech (US) + 2-week buffer stock drawdown",
                mitigation_effectiveness=0.7, revenue_impact=2_400_000,
                occurred_at=now - timedelta(days=180), resolved_at=now - timedelta(days=159)),
            DisruptionLog(
                event_type="geopolitical", severity="high",
                affected_region="China", affected_supplier_id=13,
                description="Export restrictions on rare earth minerals from China impacted SiliconBase Foundry raw material supply.",
                source="historical", mitigation_taken="Pre-negotiated 6-month stockpile agreement with RareEarth Mining + diversification study initiated",
                mitigation_effectiveness=0.6, revenue_impact=1_800_000,
                occurred_at=now - timedelta(days=365), resolved_at=now - timedelta(days=320)),
            DisruptionLog(
                event_type="shipping", severity="medium",
                affected_region="Red Sea", affected_supplier_id=None,
                description="Houthi attacks on Red Sea shipping routes caused 2-week delays for components from Asia to Europe.",
                source="historical", mitigation_taken="Rerouted shipments via Cape of Good Hope, accepted 12-day delay and 18% cost increase",
                mitigation_effectiveness=0.5, revenue_impact=600_000,
                occurred_at=now - timedelta(days=90), resolved_at=now - timedelta(days=76)),
            DisruptionLog(
                event_type="supplier_failure", severity="high",
                affected_region="China", affected_supplier_id=10,
                description="CellChem Materials failed quality audit. Batch of cathode material contaminated. Recalled 2000 units.",
                source="erp_signal", mitigation_taken="Temporary shift to LithiumCore as sole battery material source + expedited quality re-certification",
                mitigation_effectiveness=0.8, revenue_impact=400_000,
                occurred_at=now - timedelta(days=45), resolved_at=now - timedelta(days=30)),
        ]
        session.add_all(disruptions)

        session.commit()
        print("=" * 70)
        print("Database seeded successfully")
        print("=" * 70)
        print(f"\n  Manufacturer: TechDrive Motors (Germany)")
        print(f"  Suppliers:    16 across 3 tiers")
        print(f"  Products:     4 (2 critical, 2 high)")
        print(f"  SPOFs:        RareEarth Mining (#13), CopperMine Ltd (#15)")
        print(f"  Bottleneck:   ChipFlow Semiconductors (supplies 3/4 products)")
        print("=" * 70)

    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    engine = init_database()
    seed_data(engine)
