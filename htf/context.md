# Autonomous Supply Chain Resilience Agent — Full Architecture

## System Overview

A multi-agent autonomous system built on **Google ADK** that detects real-world supply chain disruptions from live news, propagates impact through a graph-based supplier network, quantifies risk, plans mitigation, and executes corrective actions — all in a closed loop. Company-agnostic: any company uploads their ERP/supplier data and the system adapts.

**Stack**: Google ADK + Gemini 2.5 | SQLAlchemy + SQLite | Streamlit + Plotly | Python 3.14

---

## Agent Pipeline

```
User Query
    |
    v
[Root Coordinator] (LlmAgent, gemini-2.5-flash)
    |
    |--- analysis_pipeline (SequentialAgent)
    |       |
    |       1. Disruption Monitoring Agent (gemini-2.5-flash-lite)
    |       |    Tools: fetch_disruption_signals, fetch_news_from_api,
    |       |           fetch_from_rss_feed, ingest_manual_alert,
    |       |           classify_disruption_type, extract_affected_entities,
    |       |           resolve_entities_to_suppliers
    |       |
    |       2. Knowledge Graph Agent (gemini-2.5-flash-lite)
    |       |    Tools: bfs_disruption_propagation, analyze_cascade_risk,
    |       |           calculate_graph_centrality, trace_disruption_paths,
    |       |           get_full_supply_chain_snapshot, detect_bottlenecks_and_spofs
    |       |
    |       3. Product Search Agent (gemini-2.5-flash)
    |       |    Tools: query_suppliers_by_industry, assess_inventory_risk,
    |       |           map_suppliers_to_products, get_full_supply_chain_snapshot
    |       |
    |       4+5. ParallelAgent
    |       |    |
    |       |    |-- Network Visualizer (gemini-2.5-flash-lite)
    |       |    |    Tools: get_graph_viz_data, calculate_graph_centrality,
    |       |    |           bfs_disruption_propagation
    |       |    |
    |       |    |-- Risk Manager (gemini-2.5-flash)
    |       |         Tools: compute_weighted_risk_score,
    |       |                compute_tier1_risk_aggregation,
    |       |                get_risk_summary_all_suppliers
    |       |
    |       6. CSCO Planning Loop (LoopAgent, max 2 iterations)
    |       |    |
    |       |    |-- CSCO Agent (gemini-2.5-flash)
    |       |    |    Tools: find_alternative_suppliers,
    |       |    |           simulate_mitigation_tradeoffs,
    |       |    |           model_buffer_stock_strategy,
    |       |    |           recall_past_disruptions,
    |       |    |           find_similar_past_disruptions
    |       |    |
    |       |    |-- Strategy Critic (gemini-2.5-flash-lite)
    |       |         No tools — reviews plan, returns PASS or NEEDS_REVISION
    |       |
    |       7. Action Pipeline (SequentialAgent)
    |            |
    |            |-- Alternative Sourcing Agent (gemini-2.5-flash-lite)
    |            |    Tools: find_alternative_suppliers,
    |            |           simulate_mitigation_tradeoffs
    |            |
    |            |-- Action Execution Agent (gemini-2.5-flash-lite)
    |                 Tools: apply_disruption_impact, trigger_emergency_reorder,
    |                        draft_supplier_email, generate_po_adjustment,
    |                        create_escalation_alert, record_disruption
    |
    |--- Memory Agent (LlmAgent, gemini-2.5-flash)
            Tools: recall_past_disruptions, find_similar_past_disruptions,
                   evaluate_mitigation_effectiveness
```

**Totals**: 11 agents, 39 tool bindings, 4 ADK patterns (Sequential, Parallel, Loop, LLM)

---

## Database Schema

```
manufacturers          suppliers (self-referential graph)
  id                     id
  name                   name
  industry               parent_supplier_id → suppliers.id
  region                 tier (1, 2, 3)
  risk_appetite          region, industry
                         reliability_score (0-1)
                         lead_time_days
                         capacity_utilization (0-1)
                         revenue_impact
                         is_single_source (SPOF flag)

products               supplier_products (M:M)
  id                     supplier_id → suppliers.id
  name, sku              product_id → products.id
  manufacturer_id        component_name
  criticality            is_critical
  annual_revenue

inventory              purchase_orders
  product_id             supplier_id, product_id
  quantity               quantity, unit_cost
  reorder_point          status (pending/confirmed/shipped/delivered/cancelled)
  safety_stock_days      created_at, expected_delivery

disruption_log         decision_log
  event_type             agent_name
  severity               decision, reasoning
  affected_region        risk_score, confidence
  affected_supplier_id   timestamp
  description, source
  mitigation_taken
  mitigation_effectiveness
  revenue_impact
  occurred_at, resolved_at
```

**Key relationship**: `suppliers.parent_supplier_id` creates the directed supply chain graph (Tier 3 → Tier 2 → Tier 1 → Manufacturer).

---

## Graph Algorithms (`src/graph_algorithms.py`)

| Algorithm | Purpose | Key Detail |
|-----------|---------|------------|
| `bfs_disruption_propagation` | Trace impact downstream | Attenuates 30% per tier hop (1.0 → 0.7 → 0.49) |
| `analyze_cascade_risk` | Full disruption analysis | Propagation + product impact + total revenue at risk |
| `calculate_graph_centrality` | Find bottlenecks | Degree + Betweenness + PageRank (damping=0.85, per AlMahri et al. 2025) |
| `detect_spofs` | Single points of failure | 4 criteria: explicit flag, sole-child, hub (≥3 children), high PageRank |
| `aggregate_risk_to_tier1` | Upstream risk → Tier 1 exposure | 5-factor weighted score per AlMahri et al. 2025 |
| `trace_disruption_paths` | Exact chain from source to T1 | Parent traversal through self-referential FK |

---

## Risk Scoring Formula

```
RISK = severity_multiplier * (
    0.35 * breadth        +   # fraction of products affected
    0.25 * dependency     +   # avg impact score on affected products
    0.20 * criticality    +   # weighted by product criticality level
    0.10 * centrality     +   # PageRank-based network importance
    0.10 * depth              # cascade_depth / max_tiers
)

Classification:
  HIGH   (>= 0.6)  → VP/CFO approval required
  MEDIUM (0.45-0.59) → Auto-execute with notification
  LOW    (< 0.45)  → Auto-execute silently
  Revenue > $5M    → Board notification (always)
```

---

## Closed-Loop: News → DB Mutation

This is the core differentiator. Detected disruptions actually change the supplier network state:

```
Google News / GDELT / RSS / Manual Alert
    |
    v
Agent 1: fetch + classify + extract entities + resolve to supplier IDs
    |
    v
Agents 2-5: BFS propagation → cascade analysis → risk scoring
    |
    v
Agent 6: CSCO plans mitigation (with critic review loop)
    |
    v
Agent 7: apply_disruption_impact() ← WRITES TO DB
    |
    |  Supplier table:
    |    reliability_score:    -0.05 (low) to -0.35 (critical)
    |    lead_time_days:       +2d (low) to +21d (critical)
    |    capacity_utilization: +0.05 (low) to +0.35 (critical)
    |
    |  Inventory table:
    |    quantity: -5% (low) to -35% (critical) for all products from this supplier
    |
    |  Disruption-type modifiers:
    |    shipping:        lead_time impact × 1.5
    |    cyber/failure:   reliability impact × 1.5
    |
    v
trigger_emergency_reorder() → Creates POs if stock < reorder_point
record_disruption()         → Logs event for future memory/learning
create_escalation_alert()   → Routes to appropriate leadership
```

---

## News/Perception Pipeline

### Sources
1. **Google News RSS** — free, default, no key needed
2. **GDELT Project** — free, global event monitoring
3. **NewsAPI.org** — requires `NEWS_API_KEY` in `.env`
4. **Custom RSS** — any URL
5. **Manual alerts** — supplier advisories, ERP signals

### Entity Resolution (news text → supplier IDs)
```
Scoring:
  Exact name match:   +0.9
  Partial name match:  +0.3 per word (>3 chars)
  Region match:       +0.2
  Industry match:     +0.15
  Threshold:          >= 0.2 confidence
```

---

## Data Ingestion Pipeline

Supports **CSV** and **JSON** uploads via Streamlit UI or programmatic API.

| Data Type | CSV Columns | Function |
|-----------|-------------|----------|
| Manufacturer | name, industry, region, risk_appetite | `ingest_manufacturer()` |
| Suppliers | name, tier, parent_supplier_name, region, industry, reliability_score, lead_time_days, capacity_utilization, revenue_impact, is_single_source | `ingest_suppliers()` |
| Products | name, sku, criticality, annual_revenue | `ingest_products()` |
| Supplier-Product Links | supplier_name, product_name, component_name, is_critical | `ingest_supplier_product_links()` |
| Inventory | product_name, quantity, reorder_point, safety_stock_days | `ingest_inventory()` |
| Purchase Orders | supplier_name, product_name, quantity, unit_cost, status, expected_delivery | `ingest_purchase_orders()` |
| Disruption History | event_type, severity, affected_region, affected_supplier_name, description, ... | `ingest_disruption_history()` |
| Full Bundle | All of the above in one JSON | `ingest_full_bundle()` |

Two-pass supplier import resolves `parent_supplier_name` → `parent_supplier_id` after all suppliers are created.

---

## Streamlit UI Modes

### 1. Dashboard
- Company name (dynamic from DB), supplier count, product count, active POs, SPOFs detected
- Interactive Plotly network graph with disruption simulation dropdown
- Cascade analysis, risk gauge, 5-factor breakdown, centrality rankings
- Inventory status with reorder point comparison
- Disruption history with mitigation effectiveness

### 2. Run AI Agent (Live Pipeline Demo)
- Real-time step-by-step 7-stage visualization:
  - Stage 1: News articles fetched → classified → entities extracted → suppliers resolved
  - Stage 2: BFS propagation with impact bars
  - Stage 3: Product mapping with criticality icons + inventory risk
  - Stage 4+5: Network graph (left) + risk gauge & breakdown (right)
  - Stage 6: Alternative suppliers + 4-strategy comparison (reroute/dual_source/buffer/expedite)
  - Stage 7: DB mutation (supplier degradation + inventory reduction + emergency POs)
  - Final: Before vs after comparison (supplier metrics + inventory deltas)

### 3. Data Ingestion
- Full bundle JSON upload
- Individual CSV uploaders (Suppliers, Products, Links, Inventory, POs, Disruptions)
- Manufacturer configuration form (reads current values from DB)
- Clear all data + Load demo data

---

## Project Structure

```
app/
├── main.py                          # CLI entry point + rate-limit retry
├── src/
│   ├── models.py                    # SQLAlchemy ORM (9 models)
│   ├── db_service.py                # READ + WRITE database helpers
│   ├── db_init.py                   # Demo data seeding (16 suppliers, 3 tiers)
│   ├── graph_algorithms.py          # BFS, cascade, centrality, SPOF, PageRank
│   └── ingest.py                    # CSV/JSON data import pipeline
├── supply_chain_agent/
│   ├── __init__.py                  # Exports root_agent
│   ├── agent.py                     # Root coordinator + SequentialAgent pipeline
│   ├── sub_agents/
│   │   ├── perception.py            # Agent 1: Disruption Monitoring
│   │   ├── knowledge_graph.py       # Agent 2: Knowledge Graph Query
│   │   ├── product_search.py        # Agent 3: Product Search
│   │   ├── risk_intelligence.py     # Agents 4+5: ParallelAgent (Viz + Risk)
│   │   ├── planning.py              # Agent 6: CSCO LoopAgent + Critic
│   │   ├── action.py                # Agent 7: SequentialAgent (Sourcing + Execution)
│   │   └── memory.py                # Memory Agent (standalone)
│   └── tools/
│       ├── perception_tools.py      # News fetch, classify, entity resolution
│       ├── graph_tools.py           # BFS, cascade, centrality wrappers
│       ├── product_tools.py         # Supplier-product mapping, inventory risk
│       ├── visualization_tools.py   # Plotly graph data generation
│       ├── risk_tools.py            # 5-factor risk scoring, Tier-1 aggregation
│       ├── planning_tools.py        # Alternative suppliers, strategy simulation
│       ├── action_tools.py          # DB mutations, emails, POs, alerts, reorders
│       └── memory_tools.py          # Historical recall, pattern matching
└── ui/
    └── app.py                       # Streamlit dashboard (3 modes)
```

---

## ADK Patterns Used

| Pattern | Where | Purpose |
|---------|-------|---------|
| **SequentialAgent** | analysis_pipeline (1→2→3→4/5→6→7) | Information flows forward through stages |
| **ParallelAgent** | risk_intelligence (Viz ∥ Risk) | Independent analyses run concurrently |
| **LoopAgent** | csco_loop (CSCO → Critic, max 2) | Iterative plan refinement with feedback |
| **LlmAgent** | All 11 leaf agents | Natural language reasoning with tool access |
| **Coordinator-Dispatcher** | root_agent → pipeline or memory | Routes by intent |

---

## Reference

AlMahri et al. (2025) "Automating Supply Chain Disruption Monitoring via an Agentic AI Approach" — PageRank centrality (damping=0.85), 5-factor Tier-1 risk aggregation, entity resolution pattern.
