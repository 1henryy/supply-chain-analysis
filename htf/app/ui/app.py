import streamlit as st
import plotly.graph_objects as go
import json
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from src.db_init import init_database
from src.db_service import get_full_supply_chain_snapshot, get_past_disruptions, get_recent_decisions
from src.graph_algorithms import (
    bfs_disruption_propagation,
    analyze_cascade_risk,
    calculate_graph_centrality,
    detect_spofs,
)
from supply_chain_agent.tools.visualization_tools import get_graph_viz_data
from supply_chain_agent.tools.risk_tools import compute_weighted_risk_score
from supply_chain_agent.tools.perception_tools import (
    fetch_disruption_signals,
    classify_disruption_type,
    extract_affected_entities,
    resolve_entities_to_suppliers,
)
from supply_chain_agent.tools.product_tools import map_suppliers_to_products, assess_inventory_risk
from supply_chain_agent.tools.planning_tools import find_alternative_suppliers, simulate_mitigation_tradeoffs
from supply_chain_agent.tools.action_tools import apply_disruption_impact, trigger_emergency_reorder

# ---------- Page Config ----------
st.set_page_config(
    page_title="Supply Chain Resilience Agent",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Init Database ----------
engine = init_database()

# ---------- Sidebar ----------
st.sidebar.title("Supply Chain Resilience")
st.sidebar.caption("AI-Powered Disruption Analysis")

mode = st.sidebar.radio(
    "Mode",
    ["Dashboard", "Run AI Agent", "Data Ingestion"],
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
    snapshot = get_full_supply_chain_snapshot()
    _dash_mfg = snapshot.get("manufacturer", {})
    _dash_name = _dash_mfg.get("name", "")
    st.title(f"{_dash_name + ' — ' if _dash_name else ''}Supply Chain Resilience Dashboard")

    if not snapshot["suppliers"]:
        st.info("No supply chain data loaded. Go to **Data Ingestion** to upload your company data or load the demo dataset.")
        st.stop()

    # ==================================================================
    # ACTIVE ALERTS — recent agent-detected disruptions
    # ==================================================================
    disruptions = get_past_disruptions(limit=10)
    decisions = get_recent_decisions(limit=10)

    # Find disruptions detected by the agent (source = "agent_detected") that are unresolved
    agent_disruptions = [d for d in disruptions if d.get("resolved_at") is None]
    # Find recent impact actions from the decision log
    impact_decisions = [d for d in decisions if d["agent_name"] == "disruption_impact"]

    if agent_disruptions or impact_decisions:
        st.subheader("Active Disruption Alerts")

        for d in agent_disruptions[:3]:
            sev = d["severity"].upper()
            sev_color = {"CRITICAL": "error", "HIGH": "error", "MEDIUM": "warning", "LOW": "info"}.get(sev, "info")
            getattr(st, sev_color)(
                f"**[{sev}] {d['event_type'].replace('_', ' ').title()}** — "
                f"{d['affected_region'] or 'Global'}: {d['description'][:150]}"
            )

        if impact_decisions:
            with st.expander("Agent Actions Taken", expanded=True):
                for dec in impact_decisions[:5]:
                    st.markdown(
                        f"- **{dec['decision']}**  \n"
                        f"  {dec['reasoning']}"
                    )

        # Auto-highlight the most recent disrupted supplier on the network graph
        _auto_disrupted_id = 0
        for d in agent_disruptions:
            if d.get("affected_supplier_id"):
                _auto_disrupted_id = d["affected_supplier_id"]
                break

        st.markdown("---")
    else:
        _auto_disrupted_id = 0

    # ==================================================================
    # KEY METRICS
    # ==================================================================
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Suppliers", len(snapshot["suppliers"]))
    col2.metric("Products", len(snapshot["products"]))
    col3.metric("Active POs", len(snapshot["purchase_orders"]))

    spofs = detect_spofs(snapshot["suppliers"])
    col4.metric("SPOFs Detected", len(spofs), delta=f"{len(spofs)} critical", delta_color="inverse")

    # Count degraded suppliers (reliability below 0.8)
    degraded_count = sum(1 for s in snapshot["suppliers"] if s["reliability_score"] < 0.80)
    col5.metric("Degraded Suppliers", degraded_count,
                delta=f"{degraded_count} below 0.80" if degraded_count else "all healthy",
                delta_color="inverse" if degraded_count else "normal")

    # ==================================================================
    # SUPPLIER HEALTH — flag any degraded suppliers from disruption impact
    # ==================================================================
    degraded_suppliers = [s for s in snapshot["suppliers"] if s["reliability_score"] < 0.80]
    if degraded_suppliers:
        st.subheader("Degraded Suppliers")
        deg_cols = st.columns(min(len(degraded_suppliers), 4))
        for i, s in enumerate(degraded_suppliers[:4]):
            with deg_cols[i]:
                st.metric(
                    f"#{s['id']} {s['name']}",
                    f"Reliability: {s['reliability_score']:.2f}",
                    delta=f"{s['reliability_score'] - 0.90:+.2f} from baseline",
                    delta_color="inverse",
                )
                st.caption(f"T{s['tier']} | {s['region']} | Lead: {s['lead_time_days']}d | Cap: {s['capacity_utilization']:.0%}")

    # ==================================================================
    # NETWORK GRAPH — auto-highlights disrupted supplier if one exists
    # ==================================================================
    st.subheader("Supply Chain Network")

    # Show suppliers that are at-risk: disrupted, degraded, or SPOFs
    _affected_supplier_ids = set()
    for d in disruptions:
        if d.get("affected_supplier_id"):
            _affected_supplier_ids.add(d["affected_supplier_id"])
    for s in snapshot["suppliers"]:
        if s["reliability_score"] < 0.80 or s.get("is_single_source"):
            _affected_supplier_ids.add(s["id"])
    _affected_options = [0] + sorted(_affected_supplier_ids)

    disrupted_id = st.selectbox(
        "Highlight disrupted supplier:",
        options=_affected_options,
        format_func=lambda x: "None (show full network)" if x == 0 else
            f"#{x} - {next((s['name'] for s in snapshot['suppliers'] if s['id'] == x), 'Unknown')}",
        index=_affected_options.index(_auto_disrupted_id)
              if _auto_disrupted_id in _affected_options else 0,
    )
    fig = build_network_graph(disrupted_id)
    st.plotly_chart(fig, use_container_width=True)

    # Two columns: Cascade Analysis + Risk Score
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
                    crit_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(p["criticality"], "")
                    st.write(f"  {crit_icon} **{p['product_name']}** — impact: {p['supply_chain_impact']:.2f}, "
                             f"via {p['component']} ({'CRITICAL' if p['is_critical_component'] else 'non-critical'})")

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

    # ==================================================================
    # INVENTORY STATUS — highlights items below reorder point
    # ==================================================================
    st.subheader("Inventory Status")
    products_map = {p["id"]: p for p in snapshot["products"]}

    if snapshot["inventory"]:
        inv_cols = st.columns(len(snapshot["inventory"]))
        for i, inv in enumerate(snapshot["inventory"]):
            prod = products_map.get(inv["product_id"], {})
            below_reorder = inv["quantity"] < inv["reorder_point"]
            with inv_cols[i]:
                pct = inv["quantity"] / inv["reorder_point"] * 100 if inv["reorder_point"] > 0 else 100
                st.metric(
                    prod.get("name", f"Product {inv['product_id']}"),
                    f"{inv['quantity']} units",
                    delta=f"{pct - 100:+.0f}% vs reorder",
                    delta_color="normal" if not below_reorder else "inverse",
                )
                if below_reorder:
                    st.caption("⚠️ BELOW REORDER POINT")

    # ==================================================================
    # BOTTLENECKS & SPOFS
    # ==================================================================
    st.subheader("Bottleneck Analysis")
    col_b1, col_b2 = st.columns(2)

    with col_b1:
        st.write("**Top Suppliers by Centrality:**")
        centrality = calculate_graph_centrality(snapshot["suppliers"])
        for i, c in enumerate(centrality[:6]):
            st.write(f"{i+1}. **{c['supplier_name']}** (T{c['tier']}) — "
                     f"centrality: {c['combined_centrality']:.3f}, "
                     f"in-degree: {c['in_degree']}, out-degree: {c['out_degree']}")

    with col_b2:
        st.write("**Single Points of Failure:**")
        if spofs:
            for sp in spofs:
                sev_color = "red" if sp["severity"] == "critical" else "orange"
                st.markdown(f":{sev_color}[**{sp['supplier_name']}** ({sp['severity'].upper()})]")
                for reason in sp["reasons"]:
                    st.write(f"  - {reason}")
        else:
            st.success("No single points of failure detected.")

    # ==================================================================
    # DISRUPTION HISTORY + DECISION LOG
    # ==================================================================
    st.subheader("Disruption History")
    if disruptions:
        for d in disruptions[:5]:
            resolved_tag = "  ✅ Resolved" if d.get("resolved_at") else "  🔴 Active"
            with st.expander(f"[{d['severity'].upper()}] {d['event_type'].replace('_', ' ').title()} — {d['affected_region'] or 'Global'}{resolved_tag}"):
                st.write(d["description"])
                if d["mitigation_taken"]:
                    st.write(f"**Mitigation:** {d['mitigation_taken']}")
                if d["mitigation_effectiveness"]:
                    st.progress(d["mitigation_effectiveness"], text=f"Effectiveness: {d['mitigation_effectiveness']:.0%}")
                if d["revenue_impact"]:
                    st.write(f"**Revenue Impact:** ${d['revenue_impact']:,.0f}")
    else:
        st.info("No disruption events recorded yet.")

    # Decision audit trail
    if decisions:
        st.subheader("Agent Decision Log")
        for dec in decisions[:5]:
            with st.expander(f"[{dec['agent_name']}] {dec['decision'][:80]}"):
                if dec["reasoning"]:
                    st.write(dec["reasoning"])
                dc1, dc2, dc3 = st.columns(3)
                if dec["risk_score"] is not None:
                    dc1.metric("Risk Score", f"{dec['risk_score']:.2f}")
                if dec["confidence"] is not None:
                    dc2.metric("Confidence", f"{dec['confidence']:.2f}")
                dc3.caption(dec["timestamp"])


# ====================================================================
# AI AGENT MODE
# ====================================================================
elif mode == "Run AI Agent":
    st.title("AI Agent - Live Pipeline Demo")
    st.caption("Watch the 7-agent pipeline process real news into supply chain actions")

    _snap = get_full_supply_chain_snapshot()
    if not _snap["suppliers"]:
        st.info("No supply chain data loaded. Go to **Data Ingestion** to upload your company data or load the demo dataset.")
        st.stop()

    import time

    # Build dynamic default query from the company's actual data
    _industries = sorted(set(s["industry"] for s in _snap["suppliers"]))
    _regions = sorted(set(s["region"] for s in _snap["suppliers"]))
    _mfg = _snap.get("manufacturer", {})
    _default_query = f"supply chain disruption {_industries[0] if _industries else 'manufacturing'} {_regions[0] if _regions else ''}"

    query = st.text_input(
        "Search query (news topic or disruption scenario):",
        value=_default_query.strip(),
    )

    st.caption(f"Your network: {len(_snap['suppliers'])} suppliers across {', '.join(_regions) or 'various regions'} "
               f"| Industries: {', '.join(_industries) or 'various'}")

    if st.button("Run Live Analysis Pipeline", type="primary", use_container_width=True):
        if not query.strip():
            st.warning("Please enter a search query.")
        else:
            pre_snapshot = get_full_supply_chain_snapshot()

            # ==============================================================
            # STAGE 1: Disruption Monitoring (Agent 1)
            # ==============================================================
            with st.status("**Agent 1: Disruption Monitoring** — Scanning news sources...", expanded=True) as status:
                st.write("Fetching from Google News RSS...")
                news_result = json.loads(fetch_disruption_signals(query))
                articles = news_result.get("articles", [])

                if articles:
                    st.success(f"Found **{len(articles)} articles** from {news_result.get('source', 'news')}")
                    for i, article in enumerate(articles[:5]):
                        st.markdown(
                            f"**{i+1}. {article['title']}**  \n"
                            f"*{article.get('source', 'Unknown')}* — {article.get('published', '')}"
                        )
                else:
                    st.warning("No articles found. Using query text for analysis.")

                # Classify top articles
                st.write("---")
                st.write("Classifying disruption types...")
                classifications = []
                for article in articles[:3]:
                    cls = json.loads(classify_disruption_type(
                        article["title"], article.get("snippet", "")
                    ))
                    cls["article_title"] = article["title"]
                    classifications.append(cls)

                if classifications:
                    for cls in classifications:
                        conf_pct = int(cls["confidence"] * 100)
                        st.markdown(
                            f"- **{cls['disruption_type'].replace('_', ' ').title()}** "
                            f"(confidence: {conf_pct}%) — affects: {', '.join(cls['affected_sectors'])}"
                        )

                # Extract affected entities
                st.write("---")
                st.write("Extracting affected regions and industries...")
                combined_text = " ".join(
                    f"{a['title']} {a.get('snippet', '')}" for a in articles[:5]
                ) or query
                entities = json.loads(extract_affected_entities(combined_text, ""))
                ec1, ec2, ec3 = st.columns(3)
                ec1.metric("Regions", ", ".join(entities["affected_regions"]))
                ec2.metric("Industries", ", ".join(entities["affected_industries"]))
                ec3.metric("Severity", entities["severity_estimate"].upper())

                # Resolve to known suppliers
                st.write("---")
                st.write("Matching to known suppliers in our network...")
                resolved = json.loads(resolve_entities_to_suppliers(combined_text))
                matched_suppliers = resolved.get("matches", [])

                if matched_suppliers:
                    for m in matched_suppliers[:5]:
                        st.markdown(
                            f"- **#{m['supplier_id']} {m['supplier_name']}** "
                            f"(T{m['tier']}, {m['region']}) — "
                            f"confidence: {int(m['confidence']*100)}% "
                            f"({', '.join(m['match_reasons'])})"
                        )
                else:
                    st.info("No direct supplier name matches. Falling back to region/industry matching.")
                    # Fallback: find suppliers in affected regions
                    snapshot = get_full_supply_chain_snapshot()
                    for s in snapshot["suppliers"]:
                        if s["region"] in entities["affected_regions"] or \
                           s["industry"] in entities["affected_industries"]:
                            matched_suppliers.append({
                                "supplier_id": s["id"],
                                "supplier_name": s["name"],
                                "tier": s["tier"],
                                "region": s["region"],
                                "confidence": 0.4,
                            })
                    if matched_suppliers:
                        for m in matched_suppliers[:5]:
                            st.markdown(f"- **#{m['supplier_id']} {m['supplier_name']}** (T{m['tier']}, {m['region']})")

                status.update(label="**Agent 1: Disruption Monitoring** — Complete", state="complete")

            if not matched_suppliers:
                st.error("Could not identify any affected suppliers. Try a more specific query.")
                st.stop()

            primary_supplier_id = matched_suppliers[0]["supplier_id"]
            best_severity = entities.get("severity_estimate", "medium")
            best_disruption_type = classifications[0]["disruption_type"] if classifications else "general"

            # ==============================================================
            # STAGE 2: Knowledge Graph Query (Agent 2)
            # ==============================================================
            with st.status("**Agent 2: Knowledge Graph** — Running BFS propagation...", expanded=True) as status:
                snapshot = get_full_supply_chain_snapshot()

                st.write(f"BFS from **#{primary_supplier_id} {matched_suppliers[0]['supplier_name']}**...")
                bfs_results = bfs_disruption_propagation(snapshot["suppliers"], primary_supplier_id)

                st.write(f"**{len(bfs_results)} suppliers** in the propagation path:")
                for node in bfs_results:
                    bar = int(node["impact_score"] * 20) * "█"
                    st.markdown(
                        f"- **#{node['supplier_id']} {node['supplier_name']}** "
                        f"(T{node['tier']}) — impact: {node['impact_score']:.2f} {bar}"
                    )

                st.write("---")
                st.write("Cascade risk analysis...")
                cascade = analyze_cascade_risk(
                    snapshot["suppliers"], primary_supplier_id,
                    snapshot["supplier_product_links"], snapshot["products"],
                )
                cc1, cc2, cc3, cc4 = st.columns(4)
                cc1.metric("Suppliers Hit", cascade["num_suppliers_affected"])
                cc2.metric("Products Hit", cascade["num_products_affected"])
                cc3.metric("Revenue at Risk", f"${cascade['total_revenue_at_risk']:,.0f}")
                cc4.metric("Cascade Depth", f"{cascade['cascade_depth']} tiers")

                status.update(label="**Agent 2: Knowledge Graph** — Complete", state="complete")

            # ==============================================================
            # STAGE 3: Product Search (Agent 3)
            # ==============================================================
            with st.status("**Agent 3: Product Search** — Mapping to affected products...", expanded=True) as status:
                supplier_ids_str = ",".join(str(m["supplier_id"]) for m in matched_suppliers[:5])
                product_map_result = json.loads(map_suppliers_to_products(supplier_ids_str))
                affected_products = product_map_result.get("affected_products", [])

                if affected_products:
                    for p in affected_products:
                        crit_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(p["criticality"], "⚪")
                        st.markdown(
                            f"- {crit_icon} **{p['product_name']}** ({p['criticality']}) — "
                            f"component: {p['component']} "
                            f"{'⚠️ CRITICAL' if p['is_critical_component'] else ''} — "
                            f"revenue: ${p['annual_revenue']:,.0f}"
                        )
                else:
                    st.info("No direct product links found for matched suppliers.")

                st.write("---")
                st.write("Inventory risk check...")
                inv_risk = json.loads(assess_inventory_risk())
                critical_items = [r for r in inv_risk["inventory_risk"] if r["risk_level"] in ("critical", "high")]
                if critical_items:
                    for item in critical_items:
                        st.warning(
                            f"**{item['product_name']}**: {item['current_stock']} units "
                            f"({item['days_of_supply']} days supply) — "
                            f"risk: **{item['risk_level'].upper()}**"
                        )
                else:
                    st.success("All inventory levels currently above reorder points.")

                status.update(label="**Agent 3: Product Search** — Complete", state="complete")

            # ==============================================================
            # STAGE 4+5: Network Visualization + Risk Scoring (Parallel)
            # ==============================================================
            with st.status("**Agents 4+5: Visualization & Risk** — Running in parallel...", expanded=True) as status:
                col_viz, col_risk = st.columns([3, 2])

                with col_viz:
                    st.write("**Agent 4: Network Visualizer**")
                    fig = build_network_graph(primary_supplier_id)
                    st.plotly_chart(fig, use_container_width=True)

                with col_risk:
                    st.write("**Agent 5: Risk Manager**")
                    risk_data = json.loads(compute_weighted_risk_score(primary_supplier_id, best_severity))
                    st.plotly_chart(
                        build_risk_gauge(risk_data["risk_score"], risk_data["classification"]),
                        use_container_width=True,
                    )
                    st.plotly_chart(
                        build_risk_breakdown(risk_data["component_breakdown"]),
                        use_container_width=True,
                    )

                    if risk_data["board_notification_required"]:
                        st.error("Board notification required (revenue > $5M)")
                    st.info(f"Recommended: {risk_data['recommended_action']}")

                status.update(label="**Agents 4+5: Visualization & Risk** — Complete", state="complete")

            # ==============================================================
            # STAGE 6: CSCO Planning (Agent 6)
            # ==============================================================
            with st.status("**Agent 6: CSCO Planning** — Finding alternatives & strategies...", expanded=True) as status:
                st.write(f"Finding alternatives for **#{primary_supplier_id} {matched_suppliers[0]['supplier_name']}**...")
                alternatives_result = json.loads(find_alternative_suppliers(primary_supplier_id))
                alts = alternatives_result.get("alternatives", [])

                if alts:
                    for alt in alts[:3]:
                        st.markdown(
                            f"- **#{alt['supplier_id']} {alt['supplier_name']}** "
                            f"(T{alt['tier']}, {alt['region']}) — "
                            f"suitability: {alt['suitability_score']:.2f}, "
                            f"reliability: {alt['reliability_score']:.2f}, "
                            f"available capacity: {alt['available_capacity']:.0%}"
                        )

                    best_alt_id = alts[0]["supplier_id"]

                    st.write("---")
                    st.write("Comparing mitigation strategies...")
                    strategies = ["reroute", "dual_source", "buffer", "expedite"]
                    strat_results = []
                    for strat in strategies:
                        r = json.loads(simulate_mitigation_tradeoffs(
                            strat, primary_supplier_id, best_alt_id
                        ))
                        if "error" not in r:
                            strat_results.append(r)

                    if strat_results:
                        strat_cols = st.columns(len(strat_results))
                        for i, sr in enumerate(strat_results):
                            with strat_cols[i]:
                                st.markdown(f"**{sr['strategy'].upper()}**")
                                st.caption(sr["description"][:60])
                                st.metric("Cost Increase", sr["estimated_cost_increase"])
                                st.metric("Risk Reduction", f"{sr['risk_reduction']:.0%}")
                                st.metric("Implementation", f"{sr['implementation_time_days']}d")
                else:
                    st.warning("No alternative suppliers found in the same industry.")

                status.update(label="**Agent 6: CSCO Planning** — Complete", state="complete")

            # ==============================================================
            # STAGE 7: Action Execution (Agent 7)
            # ==============================================================
            with st.status("**Agent 7: Action Execution** — Applying impact & taking actions...", expanded=True) as status:
                # Apply disruption impact to DB
                st.write(f"Applying **{best_severity}** disruption impact to supplier #{primary_supplier_id}...")
                impact_result = json.loads(apply_disruption_impact(
                    primary_supplier_id, best_severity, best_disruption_type
                ))

                if impact_result.get("status") == "applied":
                    updated = impact_result["supplier_updated"]
                    im1, im2, im3 = st.columns(3)
                    im1.metric("Reliability", f"{updated['reliability_score']:.2f}")
                    im2.metric("Lead Time", f"{updated['lead_time_days']}d")
                    im3.metric("Capacity", f"{updated['capacity_utilization']:.0%}")

                    inv_adj = impact_result.get("inventory_adjustments", [])
                    if inv_adj:
                        st.write("**Inventory reductions:**")
                        for adj in inv_adj:
                            st.markdown(
                                f"- {adj['component']}: **-{adj['units_lost']} units** "
                                f"(now: {adj['new_quantity']})"
                            )

                # Emergency reorders
                st.write("---")
                st.write("Checking for emergency reorder needs...")
                post_snapshot = get_full_supply_chain_snapshot()
                reorders = []
                for inv in post_snapshot["inventory"]:
                    if inv["quantity"] < inv["reorder_point"]:
                        ro = json.loads(trigger_emergency_reorder(inv["product_id"]))
                        if ro.get("status") == "po_created":
                            reorders.append(ro)

                if reorders:
                    st.warning(f"**{len(reorders)} emergency POs created:**")
                    for ro in reorders:
                        st.markdown(
                            f"- **PO #{ro['po_id']}**: {ro['quantity']} units of **{ro['product']}** "
                            f"from {ro['supplier']} — ${ro['total_cost']:,.0f} — "
                            f"delivery: {ro['expected_delivery'][:10]}"
                        )
                else:
                    st.success("No emergency reorders needed.")

                status.update(label="**Agent 7: Action Execution** — Complete", state="complete")

            # ==============================================================
            # FINAL: Before/After Summary
            # ==============================================================
            st.markdown("---")
            st.subheader("Before vs After — Network State")

            post_snapshot = get_full_supply_chain_snapshot()
            pre_map = {s["id"]: s for s in pre_snapshot["suppliers"]}

            degraded = []
            for s in post_snapshot["suppliers"]:
                prev = pre_map.get(s["id"])
                if prev and (
                    s["reliability_score"] < prev["reliability_score"]
                    or s["lead_time_days"] > prev["lead_time_days"]
                ):
                    degraded.append((prev, s))

            if degraded:
                for prev, curr in degraded:
                    with st.expander(f"#{curr['id']} {curr['name']} (T{curr['tier']})", expanded=True):
                        d1, d2, d3 = st.columns(3)
                        d1.metric(
                            "Reliability",
                            f"{curr['reliability_score']:.2f}",
                            delta=f"{curr['reliability_score'] - prev['reliability_score']:+.2f}",
                            delta_color="inverse",
                        )
                        d2.metric(
                            "Lead Time",
                            f"{curr['lead_time_days']}d",
                            delta=f"{curr['lead_time_days'] - prev['lead_time_days']:+d}d",
                            delta_color="inverse",
                        )
                        d3.metric(
                            "Capacity",
                            f"{curr['capacity_utilization']:.0%}",
                            delta=f"{curr['capacity_utilization'] - prev['capacity_utilization']:+.0%}",
                            delta_color="inverse",
                        )

            # Inventory before vs after
            st.subheader("Inventory Before vs After")
            pre_inv = {inv["product_id"]: inv["quantity"] for inv in pre_snapshot["inventory"]}
            products_map = {p["id"]: p for p in post_snapshot["products"]}
            inv_cols = st.columns(len(post_snapshot["inventory"]))
            for i, inv in enumerate(post_snapshot["inventory"]):
                prod = products_map.get(inv["product_id"], {})
                prev_qty = pre_inv.get(inv["product_id"], inv["quantity"])
                delta = inv["quantity"] - prev_qty
                with inv_cols[i]:
                    st.metric(
                        prod.get("name", f"Product {inv['product_id']}"),
                        f"{inv['quantity']} units",
                        delta=f"{delta:+d} units" if delta != 0 else "no change",
                        delta_color="normal" if delta >= 0 else "inverse",
                    )

            st.success("Pipeline complete. All 7 agents have processed the disruption signal.")


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

    _current_mfg = get_full_supply_chain_snapshot().get("manufacturer", {})

    with st.form("manufacturer_form"):
        mfg_name = st.text_input("Company Name", value=_current_mfg.get("name", ""))
        mfg_industry = st.text_input("Industry", value=_current_mfg.get("industry", ""))
        mfg_region = st.text_input("Region", value=_current_mfg.get("region", ""))
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
        "Re-seed the database with a sample automotive electronics dataset "
        "(16 suppliers across 3 tiers, 4 products, purchase orders, and disruption history)."
    )

    if st.button("Load Demo Data", type="primary", key="btn_demo"):
        with st.spinner("Clearing and re-seeding demo data..."):
            try:
                clear_all_data(engine)
                from src.db_init import seed_data as _seed_data
                _seed_data(engine)
                st.success(
                    "Demo data loaded successfully! "
                    "16 suppliers, 4 products, 3 purchase orders, 4 historical disruptions."
                )
            except Exception as e:
                st.error(f"Failed to load demo data: {e}")
