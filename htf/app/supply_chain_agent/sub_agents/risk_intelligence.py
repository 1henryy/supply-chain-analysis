"""
Agents 4+5: Parallel execution
  Agent 4: Network Visualizer (LlmAgent) - Plotly graph visualization data
  Agent 5: Risk Manager (LlmAgent) - Weighted risk scoring with graph centrality

Wrapped in a ParallelAgent for concurrent execution.
"""

from google.adk.agents import LlmAgent, ParallelAgent

from supply_chain_agent.tools.visualization_tools import get_graph_viz_data
from supply_chain_agent.tools.graph_tools import (
    calculate_graph_centrality,
    bfs_disruption_propagation,
)
from supply_chain_agent.tools.risk_tools import (
    compute_weighted_risk_score,
    compute_tier1_risk_aggregation,
    get_risk_summary_all_suppliers,
)

# Agent 4: Network Visualizer
network_visualizer_agent = LlmAgent(
    name="network_visualizer_agent",
    model="gemini-2.5-flash-lite",
    instruction="""You are a supply chain network visualization specialist.

Your job is to prepare data for an interactive network graph of the supply chain.

WORKFLOW:
1. Use get_graph_viz_data to get the full graph visualization dataset.
   - If a specific supplier is disrupted, pass its ID to highlight the cascade.
2. Use calculate_graph_centrality to add centrality annotations.
3. Summarize the visualization insights.

OUTPUT FORMAT:
- VISUALIZATION DATA: Confirm the graph data is ready (nodes, edges, colors)
- NETWORK TOPOLOGY: Describe the structure (tiers, connections, clusters)
- DISRUPTION OVERLAY: If a disruption is being analyzed, describe the cascade visually
- KEY VISUAL INSIGHTS: What stands out in the network (isolated nodes, dense clusters, etc.)

Keep output concise - the actual graph rendering happens in the Streamlit UI.
""",
    tools=[
        get_graph_viz_data,
        calculate_graph_centrality,
        bfs_disruption_propagation,
    ],
)

# Agent 5: Risk Manager
risk_manager_agent = LlmAgent(
    name="risk_manager_agent",
    model="gemini-2.5-flash",
    instruction="""You are a supply chain risk quantification expert.

You use a weighted 5-factor risk formula incorporating graph centrality metrics:

RISK = 0.35*Breadth + 0.25*Dependency + 0.20*Criticality + 0.10*Centrality + 0.10*Depth

Where:
- Breadth: fraction of products affected by the disruption
- Dependency: how heavily products depend on the disrupted supplier path
- Criticality: weighted importance of affected products
- Centrality: graph centrality of the disrupted supplier (from BFS/betweenness)
- Depth: how deep in the supply chain the disruption originates

WORKFLOW:
1. Use compute_weighted_risk_score for each identified disrupted supplier.
2. For upstream disruptions (Tier 2/3), use compute_tier1_risk_aggregation to map
   the risk to actionable Tier-1 suppliers (per AlMahri et al. 2025 methodology).
3. Use get_risk_summary_all_suppliers to contextualize risks across Tier 1.
4. Provide a comprehensive risk assessment.

OUTPUT FORMAT:
- RISK SCORES: Per-supplier risk scores with 5-factor breakdown
- RISK CLASSIFICATION: HIGH (>=0.6), MEDIUM (0.45-0.59), LOW (<0.45) for each
- HUMAN-IN-THE-LOOP RECOMMENDATION:
  - HIGH risk: VP/CFO approval required
  - MEDIUM risk: Auto-execute with notification
  - LOW risk: Auto-execute silently
  - Revenue at risk > $5M: Board notification required
- COMPARATIVE ANALYSIS: How this risk compares to other potential disruption scenarios
- TOP RISK: The single highest risk that needs immediate attention

Be precise with numbers. The risk scores drive automated decision routing.
""",
    tools=[
        compute_weighted_risk_score,
        compute_tier1_risk_aggregation,
        get_risk_summary_all_suppliers,
    ],
)

# ParallelAgent wrapping Agents 4 and 5
parallel_risk_analysis = ParallelAgent(
    name="parallel_risk_analysis",
    sub_agents=[network_visualizer_agent, risk_manager_agent],
)
