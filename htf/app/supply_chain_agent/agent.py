"""
Root Coordinator Agent - Entry point for the Supply Chain Resilience system.

Pattern: Coordinator-Dispatcher
  - Analyzes user intent
  - Delegates to the 7-Agent Analysis Pipeline or Memory Agent

Pipeline Flow: Agent 1 -> 2 -> 3 -> (4 || 5) -> 6 -> 7
"""

from google.adk.agents import LlmAgent, SequentialAgent

from supply_chain_agent.sub_agents.perception import disruption_monitoring_agent
from supply_chain_agent.sub_agents.knowledge_graph import knowledge_graph_agent
from supply_chain_agent.sub_agents.product_search import product_search_agent
from supply_chain_agent.sub_agents.risk_intelligence import parallel_risk_analysis
from supply_chain_agent.sub_agents.planning import csco_loop
from supply_chain_agent.sub_agents.action import action_pipeline
from supply_chain_agent.sub_agents.memory import memory_agent

# 7-Agent Analysis Pipeline (SequentialAgent)
# Flow: 1 -> 2 -> 3 -> (4 || 5) -> 6 -> 7
analysis_pipeline = SequentialAgent(
    name="analysis_pipeline",
    sub_agents=[
        disruption_monitoring_agent,   # Agent 1: Disruption Monitoring
        knowledge_graph_agent,          # Agent 2: Knowledge Graph Query
        product_search_agent,           # Agent 3: Product Search
        parallel_risk_analysis,         # Agents 4+5: Parallel (Viz + Risk)
        csco_loop,                      # Agent 6: CSCO + Strategy Critic Loop
        action_pipeline,                # Agent 7: Alt Sourcing + Actions
    ],
)

# Root Coordinator Agent
root_agent = LlmAgent(
    name="supply_chain_coordinator",
    model="gemini-2.5-flash",
    instruction="""You are the root coordinator for an Autonomous Supply Chain Resilience system
serving TechDrive Motors, a mid-market automotive electronics manufacturer based in Germany.

COMPANY PROFILE:
- Industry: Automotive electronics
- Products: AutoPilot ECU, BatteryGuard BMS, SafeView ADAS, DriveCore Processor
- Supply chain: 16 suppliers across 3 tiers in Taiwan, China, South Korea, Japan, USA, Germany, Chile, Peru, Malaysia, India
- Risk appetite: Moderate

YOUR ROLE:
You analyze user queries and delegate to the appropriate sub-system:

1. ANALYSIS PIPELINE: For any query about:
   - Current or potential supply chain disruptions
   - Risk assessment and mitigation planning
   - "What if" scenarios (e.g., "What happens if Taiwan is disrupted?")
   - Running a full disruption analysis cycle
   - Any proactive monitoring request
   -> Delegate to: analysis_pipeline

2. MEMORY / HISTORY: For queries about:
   - Past disruption events and their outcomes
   - Historical patterns and lessons learned
   - "What did we do last time when..."
   -> Delegate to: memory_agent

IMPORTANT GUIDELINES:
- Always be specific about which supplier IDs, regions, and products are involved
- Quantify risks with dollar amounts and scores where possible
- Flag any decision requiring human approval (risk score >= 0.6 or revenue at risk > $5M)
- Reference the supply chain graph structure (3 tiers, parent-child relationships)
- After the pipeline completes, provide a clear executive summary

When the user asks to "run analysis" or "check for disruptions" with no specifics,
delegate to the analysis_pipeline which will autonomously scan for real-world signals
and run the full 7-agent analysis.

Start each response by briefly explaining what you'll do, then delegate.
""",
    sub_agents=[analysis_pipeline, memory_agent],
)
