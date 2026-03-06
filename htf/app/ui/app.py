import streamlit as st
import plotly.graph_objects as go
import json
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from src.db_init import init_database, seed_data
from src.db_service import get_full_supply_chain_snapshot, get_past_disruptions
from src.graph_algorithms import (
    bfs_disruption_propagation,
    analyze_cascade_risk,
    calculate_graph_centrality,
    detect_spofs,
)
from supply_chain_agent.tools.visualization_tools import get_graph_viz_data
from supply_chain_agent.tools.risk_tools import compute_weighted_risk_score

# ---------- Page Config ----------
st.set_page_config(
    page_title="Supply Chain Resilience Agent",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Init Database ----------
engine = init_database()
seed_data(engine)

# ---------- Sidebar ----------
st.sidebar.title("Supply Chain Resilience")
st.sidebar.caption("AI-Powered Disruption Analysis")

mode = st.sidebar.radio(
    "Mode",
    ["Dashboard", "Run AI Agent", "What-If Scenario", "Data Ingestion"],
    index=0,
)

# ---------- Helper: Build Plotly Network Graph ----------
def build_network_graph(disrupted_id: int = 0):
    """Build an interactive Plotly network graph of the supply chain."""
    viz_data = json.loads(get_graph_viz_data(disrupted_id))
    nodes = viz_data["nodes"]
    edges = viz_data["edges"]

    # Build node position lookup
    pos = {n["id"]: (n["x"], n["y"]) for n in nodes}

    # Edge traces
    edge_x, edge_y = [], []
    affected_edge_x, affected_edge_y = [], []

    for e in edges:
        if e["source"] in pos and e["target"] in pos:
            x0, y0 = pos[e["source"]]
            x1, y1 = pos[e["target"]]
            if e.get("is_affected"):
                affected_edge_x += [x0, x1, None]
                affected_edge_y += [y0, y1, None]
            else:
                edge_x += [x0, x1, None]
                edge_y += [y0, y1, None]

    fig = go.Figure()

    # Normal edges
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=1.5, color="#888"),
        hoverinfo="none", showlegend=False,
    ))

    # Affected edges (red)
    if affected_edge_x:
        fig.add_trace(go.Scatter(
            x=affected_edge_x, y=affected_edge_y, mode="lines",
            line=dict(width=3, color="red", dash="dot"),
            hoverinfo="none", name="Disruption Path",
        ))

    # Tier labels
    tier_labels = {0: "Manufacturer", 1: "Tier 1\n(Direct)", 2: "Tier 2\n(Sub)", 3: "Tier 3\n(Raw)"}
    tier_x_pos = {0: 1.0, 1: 0.8, 2: 0.4, 3: 0.0}
    for tier, label in tier_labels.items():
        fig.add_annotation(
            x=tier_x_pos[tier], y=1.05, text=f"<b>{label}</b>",
            showarrow=False, font=dict(size=11, color="#555"),
        )

    # Node traces (by category)
    for category, filter_fn, color_default in [
        ("Manufacturer", lambda n: n["tier"] == 0, "#FF5722"),
        ("Tier 1", lambda n: n["tier"] == 1, "#4CAF50"),
        ("Tier 2", lambda n: n["tier"] == 2, "#2196F3"),
        ("Tier 3", lambda n: n["tier"] == 3, "#9C27B0"),
    ]:
        cat_nodes = [n for n in nodes if filter_fn(n)]
        if not cat_nodes:
            continue

        fig.add_trace(go.Scatter(
            x=[n["x"] for n in cat_nodes],
            y=[n["y"] for n in cat_nodes],
            mode="markers+text",
            marker=dict(
                size=[n["size"] for n in cat_nodes],
                color=[n["color"] for n in cat_nodes],
                line=dict(width=2, color="white"),
            ),
            text=[n["label"].split()[0] for n in cat_nodes],  # Short label
            textposition="top center",
            textfont=dict(size=9),
            hovertext=[
                f"<b>{n['label']}</b><br>"
                f"Tier: {n['tier']}<br>"
                f"Region: {n['region']}<br>"
                f"Centrality: {n['centrality']:.3f}<br>"
                f"{'Impact: ' + str(round(n['impact_score'], 2)) if n['is_disrupted'] else 'Not affected'}"
                for n in cat_nodes
            ],
            hoverinfo="text",
            name=category,
        ))

    fig.update_layout(
        title=dict(
            text="Supply Chain Network Graph" + (
                f" (Disruption from Supplier #{disrupted_id})" if disrupted_id > 0 else ""
            ),
            font=dict(size=16),
        ),
        showlegend=True,
        hovermode="closest",
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.1, 1.15]),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.05, 1.15]),
        height=500,
        margin=dict(l=20, r=20, t=60, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5),
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig


# ---------- Helper: Risk Gauge Chart ----------
def build_risk_gauge(risk_score: float, classification: str):
    """Build a gauge chart for risk score visualization."""
    color = {"HIGH": "red", "MEDIUM": "orange", "LOW": "green"}.get(classification, "gray")

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=risk_score * 100,
        domain=dict(x=[0, 1], y=[0, 1]),
        title=dict(text=f"Risk Score ({classification})", font=dict(size=16)),
        number=dict(suffix="%"),
        gauge=dict(
            axis=dict(range=[None, 100]),
            bar=dict(color=color),
            steps=[
                dict(range=[0, 45], color="#e8f5e9"),
                dict(range=[45, 60], color="#fff3e0"),
                dict(range=[60, 100], color="#ffebee"),
            ],
            threshold=dict(line=dict(color="black", width=2), thickness=0.75, value=risk_score * 100),
        ),
    ))
    fig.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=20))
    return fig


# ---------- Helper: Risk Breakdown Bar Chart ----------
def build_risk_breakdown(breakdown: dict):
    """Build a horizontal bar chart showing the 5-factor risk breakdown."""
    factors = ["Breadth", "Dependency", "Criticality", "Centrality", "Depth"]
    weights = [0.35, 0.25, 0.20, 0.10, 0.10]
    values = [
        breakdown.get("breadth", 0),
        breakdown.get("dependency", 0),
        breakdown.get("criticality", 0),
        breakdown.get("centrality", 0),
        breakdown.get("depth", 0),
    ]
    weighted = [v * w for v, w in zip(values, weights)]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=factors, x=weighted, orientation="h",
        marker_color=["#ef5350", "#ff7043", "#ffa726", "#66bb6a", "#42a5f5"],
        text=[f"{v:.2f} x {w:.0%} = {wv:.3f}" for v, w, wv in zip(values, weights, weighted)],
        textposition="auto",
    ))
    fig.update_layout(
        title="Risk Factor Breakdown (weighted contribution)",
        xaxis_title="Weighted Score",
        height=300, margin=dict(l=100, r=20, t=40, b=40),
    )
    return fig


# ====================================================================
# DASHBOARD MODE
# ====================================================================
if mode == "Dashboard":
    st.title("Supply Chain Resilience Dashboard")

    snapshot = get_full_supply_chain_snapshot()

    # Key metrics row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Suppliers", len(snapshot["suppliers"]))
    col2.metric("Products", len(snapshot["products"]))
    col3.metric("Active POs", len(snapshot["purchase_orders"]))

    spofs = detect_spofs(snapshot["suppliers"])
    col4.metric("SPOFs Detected", len(spofs), delta=f"{len(spofs)} critical", delta_color="inverse")

    # Network Graph
    st.subheader("Supply Chain Network")
    disrupted_id = st.selectbox(
        "Simulate disruption at supplier:",
        options=[0] + [s["id"] for s in snapshot["suppliers"]],
        format_func=lambda x: "None (show full network)" if x == 0 else
            f"#{x} - {next((s['name'] for s in snapshot['suppliers'] if s['id'] == x), 'Unknown')}",
    )
    fig = build_network_graph(disrupted_id)
    st.plotly_chart(fig, use_container_width=True)

    # Two columns: Cascade Analysis + Centrality
    if disrupted_id > 0:
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("Cascade Analysis")
            cascade = analyze_cascade_risk(
                snapshot["suppliers"], disrupted_id,
                snapshot["supplier_product_links"], snapshot["products"],
            )
            st.metric("Suppliers Affected", cascade["num_suppliers_affected"])
            st.metric("Products Affected", cascade["num_products_affected"])
            st.metric("Revenue at Risk", f"${cascade['total_revenue_at_risk']:,.0f}")
            st.metric("Cascade Depth", f"{cascade['cascade_depth']} tiers")

            if cascade["affected_products"]:
                st.write("**Affected Products:**")
                for p in cascade["affected_products"]:
                    icon = {"critical": "", "high": "", "medium": "", "low": ""}.get(p["criticality"], "")
                    st.write(f"  {icon} **{p['product_name']}** - impact: {p['supply_chain_impact']:.2f}, "
                             f"via {p['component']} ({'critical' if p['is_critical_component'] else 'non-critical'})")

        with col_right:
            st.subheader("Risk Score")
            risk_data = json.loads(compute_weighted_risk_score(disrupted_id, "high"))
            st.plotly_chart(
                build_risk_gauge(risk_data["risk_score"], risk_data["classification"]),
                use_container_width=True,
            )
            st.plotly_chart(
                build_risk_breakdown(risk_data["component_breakdown"]),
                use_container_width=True,
            )

            if risk_data["board_notification_required"]:
                st.error("Board notification required (revenue at risk > $5M)")
            st.info(f"Recommended action: {risk_data['recommended_action']}")

    # Bottlenecks and SPOFs
    st.subheader("Bottleneck Analysis")
    col_b1, col_b2 = st.columns(2)

    with col_b1:
        st.write("**Top Suppliers by Centrality:**")
        centrality = calculate_graph_centrality(snapshot["suppliers"])
        for i, c in enumerate(centrality[:6]):
            st.write(f"{i+1}. **{c['supplier_name']}** (T{c['tier']}) - "
                     f"centrality: {c['combined_centrality']:.3f}, "
                     f"in-degree: {c['in_degree']}, out-degree: {c['out_degree']}")

    with col_b2:
        st.write("**Single Points of Failure:**")
        for sp in spofs:
            sev_color = "red" if sp["severity"] == "critical" else "orange"
            st.markdown(f":{sev_color}[**{sp['supplier_name']}** ({sp['severity'].upper()})]")
            for reason in sp["reasons"]:
                st.write(f"  - {reason}")

    # Inventory Status
    st.subheader("Inventory Status")
    inv_cols = st.columns(len(snapshot["products"]))
    products_map = {p["id"]: p for p in snapshot["products"]}
    for i, inv in enumerate(snapshot["inventory"]):
        prod = products_map.get(inv["product_id"], {})
        with inv_cols[i]:
            pct = inv["quantity"] / inv["reorder_point"] * 100 if inv["reorder_point"] > 0 else 100
            st.metric(
                prod.get("name", f"Product {inv['product_id']}"),
                f"{inv['quantity']} units",
                delta=f"{pct - 100:+.0f}% vs reorder",
                delta_color="normal" if pct >= 100 else "inverse",
            )

    # Past Disruptions
    st.subheader("Disruption History")
    disruptions = get_past_disruptions(limit=5)
    for d in disruptions:
        with st.expander(f"[{d['severity'].upper()}] {d['event_type']} - {d['affected_region'] or 'Global'}"):
            st.write(d["description"])
            if d["mitigation_taken"]:
                st.write(f"**Mitigation:** {d['mitigation_taken']}")
            if d["mitigation_effectiveness"]:
                st.progress(d["mitigation_effectiveness"], text=f"Effectiveness: {d['mitigation_effectiveness']:.0%}")
            if d["revenue_impact"]:
                st.write(f"**Revenue Impact:** ${d['revenue_impact']:,.0f}")


# ====================================================================
# AI AGENT MODE
# ====================================================================
elif mode == "Run AI Agent":
    st.title("AI Agent - Disruption Analysis")
    st.caption("Run the 7-agent pipeline to analyze supply chain risks")

    # Query input
    default_queries = [
        "Run a full disruption analysis",
        "What happens if our Taiwan semiconductor suppliers are disrupted?",
        "Analyze the risk if RareEarth Mining Co (supplier #13) fails",
        "Check for current supply chain risks in the shipping sector",
        "What did we learn from past disruptions?",
    ]

    selected_query = st.selectbox("Quick queries:", ["Custom..."] + default_queries)
    if selected_query == "Custom...":
        user_query = st.text_area("Enter your query:", height=80)
    else:
        user_query = selected_query

    if st.button("Run Agent Pipeline", type="primary", use_container_width=True):
        if not user_query or user_query == "Custom...":
            st.warning("Please enter a query.")
        else:
            with st.spinner("Running 7-agent analysis pipeline... (this may take 30-60 seconds)"):
                try:
                    from main import run_agent
                    response = asyncio.run(run_agent(user_query))
                    st.session_state["agent_response"] = response
                    st.session_state["agent_query"] = user_query
                    st.success("Analysis complete!")
                except Exception as e:
                    st.error(f"Agent pipeline failed: {str(e)}")
                    import traceback
                    st.code(traceback.format_exc())

    # Display results
    if "agent_response" in st.session_state:
        st.subheader(f"Query: {st.session_state.get('agent_query', '')}")
        st.markdown("---")
        st.markdown(st.session_state["agent_response"])


# ====================================================================
# WHAT-IF SCENARIO MODE
# ====================================================================
elif mode == "What-If Scenario":
    st.title("What-If Scenario Analysis")

    snapshot = get_full_supply_chain_snapshot()

    st.write("Select a disruption scenario to simulate:")

    scenario_type = st.selectbox("Scenario Type:", [
        "Supplier Disruption",
        "Regional Crisis",
        "Industry-Wide Shortage",
    ])

    if scenario_type == "Supplier Disruption":
        supplier_id = st.selectbox(
            "Select supplier to disrupt:",
            [s["id"] for s in snapshot["suppliers"]],
            format_func=lambda x: f"#{x} - {next((s['name'] for s in snapshot['suppliers'] if s['id'] == x), '')} "
                                  f"(T{next((s['tier'] for s in snapshot['suppliers'] if s['id'] == x), '?')}, "
                                  f"{next((s['region'] for s in snapshot['suppliers'] if s['id'] == x), '')})",
        )
        severity = st.select_slider("Severity:", ["low", "medium", "high", "critical"], value="high")

        if st.button("Run Scenario", type="primary"):
            col1, col2 = st.columns([2, 1])

            with col1:
                st.subheader("Network Impact")
                fig = build_network_graph(supplier_id)
                st.plotly_chart(fig, use_container_width=True)

            with col2:
                st.subheader("Risk Assessment")
                risk_data = json.loads(compute_weighted_risk_score(supplier_id, severity))
                st.plotly_chart(
                    build_risk_gauge(risk_data["risk_score"], risk_data["classification"]),
                    use_container_width=True,
                )

            # Cascade details
            cascade = analyze_cascade_risk(
                snapshot["suppliers"], supplier_id,
                snapshot["supplier_product_links"], snapshot["products"],
            )

            st.subheader("Cascade Impact")
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Suppliers Affected", cascade["num_suppliers_affected"])
            mc2.metric("Products Affected", cascade["num_products_affected"])
            mc3.metric("Revenue at Risk", f"${cascade['total_revenue_at_risk']:,.0f}")
            mc4.metric("Risk Score", f"{risk_data['risk_score']:.2f}")

            st.plotly_chart(build_risk_breakdown(risk_data["component_breakdown"]), use_container_width=True)

            # Human-in-the-loop gate
            st.subheader("Decision Gate")
            if risk_data["classification"] == "HIGH":
                st.error(f"HIGH RISK - VP/CFO approval required")
                if risk_data["board_notification_required"]:
                    st.error("Board notification required (revenue > $5M)")

                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("Approve Mitigation Actions", type="primary"):
                        st.success("Approved - mitigation actions would be executed")
                with col_b:
                    if st.button("Reject / Request Review"):
                        st.warning("Rejected - escalating for manual review")

            elif risk_data["classification"] == "MEDIUM":
                st.warning("MEDIUM RISK - Auto-executing with notification")
            else:
                st.success("LOW RISK - Auto-executing silently")

    elif scenario_type == "Regional Crisis":
        region = st.selectbox("Select region:", [
            "Taiwan", "China", "South Korea", "Japan", "USA",
            "Germany", "Chile", "Peru", "Malaysia", "India", "Red Sea",
        ])

        affected_suppliers = [s for s in snapshot["suppliers"] if s["region"] == region]
        st.write(f"**{len(affected_suppliers)} suppliers in {region}:**")
        for s in affected_suppliers:
            st.write(f"  - #{s['id']} {s['name']} (T{s['tier']}, {s['industry']})")

        if st.button("Simulate Regional Crisis", type="primary") and affected_suppliers:
            st.subheader(f"Impact of {region} Crisis")

            # Analyze cascade for each affected supplier
            total_rev = 0
            all_affected_products = set()
            for s in affected_suppliers:
                cascade = analyze_cascade_risk(
                    snapshot["suppliers"], s["id"],
                    snapshot["supplier_product_links"], snapshot["products"],
                )
                total_rev += cascade["total_revenue_at_risk"]
                for p in cascade["affected_products"]:
                    all_affected_products.add(p["product_name"])

            st.metric("Total Revenue at Risk", f"${total_rev:,.0f}")
            st.metric("Products Affected", len(all_affected_products))

            # Show network with first affected supplier highlighted
            fig = build_network_graph(affected_suppliers[0]["id"])
            st.plotly_chart(fig, use_container_width=True)

    elif scenario_type == "Industry-Wide Shortage":
        industry = st.selectbox("Select industry:", [
            "semiconductor", "pcb_assembly", "pcb_raw", "passive_components",
            "battery", "battery_materials", "sensors", "optics", "mining", "chemicals",
        ])

        affected = [s for s in snapshot["suppliers"] if s["industry"] == industry]
        st.write(f"**{len(affected)} suppliers in {industry}:**")
        for s in affected:
            st.write(f"  - #{s['id']} {s['name']} (T{s['tier']}, {s['region']})")

        if st.button("Simulate Industry Shortage", type="primary") and affected:
            total_rev = 0
            for s in affected:
                cascade = analyze_cascade_risk(
                    snapshot["suppliers"], s["id"],
                    snapshot["supplier_product_links"], snapshot["products"],
                )
                total_rev += cascade["total_revenue_at_risk"]

            st.metric("Total Revenue at Risk", f"${total_rev:,.0f}")
            fig = build_network_graph(affected[0]["id"])
            st.plotly_chart(fig, use_container_width=True)


# ====================================================================
# DATA INGESTION MODE
# ====================================================================
elif mode == "Data Ingestion":
    from src.ingest import (
        ingest_manufacturer,
        ingest_suppliers,
        ingest_products,
        ingest_supplier_product_links,
        ingest_inventory,
        ingest_purchase_orders,
        ingest_disruption_history,
        ingest_full_bundle,
        clear_all_data,
    )

    st.title("Data Ingestion")
    st.caption("Upload supplier networks, products, ERP signals, and disruption history")

    # ------------------------------------------------------------------
    # CSV template column references
    # ------------------------------------------------------------------
    CSV_TEMPLATES = {
        "Suppliers": "name,tier,parent_supplier_name,region,industry,reliability_score,lead_time_days,capacity_utilization,revenue_impact,is_single_source",
        "Products": "name,sku,criticality,annual_revenue",
        "Supplier-Product Links": "supplier_name,product_name,component_name,is_critical",
        "Inventory": "product_name,quantity,reorder_point,safety_stock_days",
        "Purchase Orders": "supplier_name,product_name,quantity,unit_cost,status,expected_delivery",
        "Disruptions": "event_type,severity,affected_region,affected_supplier_name,description,source,mitigation_taken,mitigation_effectiveness,revenue_impact,occurred_at,resolved_at",
    }

    TEMPLATE_FILES = {
        "Suppliers": "suppliers.csv",
        "Products": "products.csv",
        "Supplier-Product Links": "supplier_product_links.csv",
        "Inventory": "inventory.csv",
        "Purchase Orders": "purchase_orders.csv",
        "Disruptions": "disruption_history.csv",
    }

    def _show_result(result: dict, label: str):
        """Display import result as success or error."""
        if isinstance(result, dict) and result.get("status") == "error":
            st.error(f"{label} failed: {result.get('message', 'Unknown error')}")
        else:
            st.success(f"{label} complete")
            st.json(result)

    # ------------------------------------------------------------------
    # Section 1: Full Bundle (JSON) Upload
    # ------------------------------------------------------------------
    st.subheader("1. Full Bundle Import (JSON)")
    st.write(
        "Upload a single JSON file containing all data: manufacturer, suppliers, "
        "products, supplier_product_links, inventory, purchase_orders, and disruption_history."
    )

    bundle_file = st.file_uploader(
        "Upload full bundle JSON",
        type=["json"],
        key="bundle_uploader",
    )
    bundle_clear = st.checkbox("Clear existing data before import", value=True, key="bundle_clear")

    if bundle_file is not None:
        if st.button("Import Full Bundle", type="primary", key="btn_bundle"):
            with st.spinner("Importing full bundle..."):
                try:
                    raw = bundle_file.read().decode("utf-8")
                    bundle_dict = json.loads(raw)
                    result = ingest_full_bundle(engine, bundle_dict, clear=bundle_clear)
                    st.success("Full bundle import complete!")
                    st.json(result)
                except Exception as e:
                    st.error(f"Bundle import failed: {e}")

    with st.expander("View example bundle structure"):
        st.code(
            '{\n'
            '  "manufacturer": {"name": "...", "industry": "...", "region": "...", "risk_appetite": "moderate"},\n'
            '  "suppliers": [{"name": "...", "tier": 1, "region": "...", "industry": "...", ...}],\n'
            '  "products": [{"name": "...", "sku": "...", "criticality": "high", "annual_revenue": 1000000}],\n'
            '  "supplier_product_links": [{"supplier_name": "...", "product_name": "...", "component_name": "...", "is_critical": true}],\n'
            '  "inventory": [{"product_name": "...", "quantity": 100, "reorder_point": 50, "safety_stock_days": 14}],\n'
            '  "purchase_orders": [{"supplier_name": "...", "product_name": "...", "quantity": 200, "unit_cost": 45.0, "status": "pending", "expected_delivery": "2026-04-01"}],\n'
            '  "disruption_history": [{"event_type": "...", "severity": "high", "affected_region": "...", ...}]\n'
            '}',
            language="json",
        )

    st.markdown("---")

    # ------------------------------------------------------------------
    # Section 2: Individual CSV Uploaders
    # ------------------------------------------------------------------
    st.subheader("2. Individual CSV Uploads")
    st.write(
        "Upload CSV files for each data type individually. Import order matters: "
        "Manufacturer and Suppliers should be imported before Products, Links, Inventory, and POs."
    )

    INGEST_MAP = {
        "Suppliers": lambda data, clear: ingest_suppliers(engine, data, clear_existing=clear),
        "Products": lambda data, clear: ingest_products(engine, data, clear_existing=clear),
        "Supplier-Product Links": lambda data, clear: ingest_supplier_product_links(engine, data, clear_existing=clear),
        "Inventory": lambda data, _: ingest_inventory(engine, data),
        "Purchase Orders": lambda data, _: ingest_purchase_orders(engine, data),
        "Disruptions": lambda data, _: ingest_disruption_history(engine, data),
    }

    template_dir = os.path.join(os.path.dirname(__file__), "..", "data", "templates")

    for label in ["Suppliers", "Products", "Supplier-Product Links", "Inventory", "Purchase Orders", "Disruptions"]:
        with st.expander(f"Upload {label}"):
            st.write(f"**Expected CSV columns:** `{CSV_TEMPLATES[label]}`")

            # Provide template download if file exists
            tpl_path = os.path.join(template_dir, TEMPLATE_FILES[label])
            if os.path.exists(tpl_path):
                with open(tpl_path, "r") as f:
                    tpl_content = f.read()
                st.download_button(
                    f"Download {label} template",
                    data=tpl_content,
                    file_name=TEMPLATE_FILES[label],
                    mime="text/csv",
                    key=f"dl_{label}",
                )

            uploaded = st.file_uploader(
                f"Choose {label} CSV",
                type=["csv"],
                key=f"upload_{label}",
            )

            clear_flag = False
            if label in ("Suppliers", "Products", "Supplier-Product Links"):
                clear_flag = st.checkbox(
                    f"Clear existing {label.lower()} before import",
                    value=False,
                    key=f"clear_{label}",
                )

            if uploaded is not None:
                if st.button(f"Import {label}", type="primary", key=f"btn_{label}"):
                    with st.spinner(f"Importing {label}..."):
                        try:
                            csv_text = uploaded.read().decode("utf-8")
                            result = INGEST_MAP[label](csv_text, clear_flag)
                            _show_result(result, label)
                        except Exception as e:
                            st.error(f"{label} import failed: {e}")

    st.markdown("---")

    # ------------------------------------------------------------------
    # Section 3: Manufacturer Configuration Form
    # ------------------------------------------------------------------
    st.subheader("3. Manufacturer Configuration")
    st.write("Set or update the focal manufacturer (the company at the center of the supply chain).")

    with st.form("manufacturer_form"):
        mfg_name = st.text_input("Company Name", value="TechDrive Motors")
        mfg_industry = st.text_input("Industry", value="automotive_electronics")
        mfg_region = st.text_input("Region", value="Germany")
        mfg_risk = st.selectbox(
            "Risk Appetite",
            ["conservative", "moderate", "aggressive"],
            index=1,
        )
        submitted = st.form_submit_button("Save Manufacturer", type="primary")

        if submitted:
            if not mfg_name.strip():
                st.error("Company name is required.")
            else:
                result = ingest_manufacturer(engine, {
                    "name": mfg_name.strip(),
                    "industry": mfg_industry.strip(),
                    "region": mfg_region.strip(),
                    "risk_appetite": mfg_risk,
                })
                _show_result(result, "Manufacturer")

    st.markdown("---")

    # ------------------------------------------------------------------
    # Section 4: Clear All Data
    # ------------------------------------------------------------------
    st.subheader("4. Clear All Data")
    st.write("Remove all data from the database. This cannot be undone.")

    col_clear1, col_clear2 = st.columns([3, 1])
    with col_clear1:
        confirm_clear = st.checkbox(
            "I understand this will delete ALL suppliers, products, inventory, orders, and disruptions.",
            key="confirm_clear",
        )
    with col_clear2:
        if st.button("Clear All Data", type="primary", disabled=not confirm_clear, key="btn_clear"):
            with st.spinner("Clearing all data..."):
                result = clear_all_data(engine)
                _show_result(result, "Clear All Data")

    st.markdown("---")

    # ------------------------------------------------------------------
    # Section 5: Load Demo Data
    # ------------------------------------------------------------------
    st.subheader("5. Load Demo Data")
    st.write(
        "Re-seed the database with the default TechDrive Motors dataset "
        "(16 suppliers across 3 tiers, 4 products, purchase orders, and disruption history)."
    )

    if st.button("Load Demo Data (TechDrive Motors)", type="primary", key="btn_demo"):
        with st.spinner("Clearing and re-seeding demo data..."):
            try:
                clear_all_data(engine)
                from src.db_init import seed_data as _seed_data
                _seed_data(engine)
                st.success(
                    "Demo data loaded successfully! TechDrive Motors: "
                    "16 suppliers, 4 products, 3 purchase orders, 4 historical disruptions."
                )
            except Exception as e:
                st.error(f"Failed to load demo data: {e}")
