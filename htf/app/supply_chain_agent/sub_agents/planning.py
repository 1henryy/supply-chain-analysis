from google.adk.agents import LlmAgent, LoopAgent

from supply_chain_agent.tools.planning_tools import (
    find_alternative_suppliers,
    simulate_mitigation_tradeoffs,
    model_buffer_stock_strategy,
)
from supply_chain_agent.tools.memory_tools import (
    recall_past_disruptions,
    find_similar_past_disruptions,
)

# CSCO Agent (generates the plan)
csco_agent = LlmAgent(
    name="csco_agent",
    model="gemini-2.5-flash",
    instruction="""You are a Chief Supply Chain Officer (CSCO) synthesizing all analytics
into an expert action plan.

You have access to all findings from previous agents in the pipeline. Your job is to
create a comprehensive mitigation strategy.

WORKFLOW:
1. Review the disruption analysis, graph traversal results, product impacts, and risk scores
   from previous agents in the conversation.
2. Use find_similar_past_disruptions to check for historical precedents.
3. Use recall_past_disruptions to understand what worked before.
4. For each high-risk supplier, use find_alternative_suppliers to identify backup options.
5. Use simulate_mitigation_tradeoffs to evaluate different strategies (reroute, buffer, expedite, dual_source).
6. Use model_buffer_stock_strategy for products with low inventory.

OUTPUT FORMAT (structured report):

## EXECUTIVE SUMMARY
2-3 sentences on the current situation and recommended course of action.

## RISK ASSESSMENT SUMMARY
- Overall risk level and classification
- Revenue at risk
- Products most affected

## MITIGATION STRATEGIES (prioritized)
For each strategy:
1. Strategy name and description
2. Affected supplier/product
3. Cost estimate
4. Timeline
5. Expected risk reduction
6. Historical precedent (if any)

## IMMEDIATE ACTIONS (next 48 hours)
Numbered list of urgent actions.

## MEDIUM-TERM ACTIONS (2-4 weeks)
Numbered list of follow-up actions.

## DECISION ROUTING
- Which decisions need human approval
- Which can be auto-executed
- Board notification requirements

If the Strategy Critic has provided feedback, address each point specifically.
""",
    tools=[
        find_alternative_suppliers,
        simulate_mitigation_tradeoffs,
        model_buffer_stock_strategy,
        recall_past_disruptions,
        find_similar_past_disruptions,
    ],
)

# Strategy Critic (reviews the plan)
strategy_critic_agent = LlmAgent(
    name="strategy_critic_agent",
    model="gemini-2.5-flash-lite",
    instruction="""You are a strategy review critic for supply chain mitigation plans.

Review the CSCO agent's plan against these criteria:

1. COMPLETENESS: Does the plan address all identified risks?
2. ACTIONABILITY: Are recommendations specific enough to execute?
3. COST AWARENESS: Are cost implications clearly stated?
4. PERSONALIZATION: Is the plan tailored to the specific manufacturer's profile?
5. CONTINGENCY: Are backup plans included if primary mitigation fails?
6. RESPONSIBLE AI: Are there human oversight checkpoints for high-stakes decisions?

OUTPUT FORMAT:
- OVERALL ASSESSMENT: PASS or NEEDS_REVISION
- STRENGTHS: What the plan does well (2-3 points)
- GAPS: What's missing or needs improvement (specific, actionable feedback)
- SUGGESTIONS: Concrete improvements to make

If the plan is acceptable, say OVERALL ASSESSMENT: PASS.
If it needs work, say OVERALL ASSESSMENT: NEEDS_REVISION and explain what to fix.

Be constructive and specific. The CSCO agent will use your feedback to improve the plan.
""",
    tools=[],
)

# LoopAgent: CSCO -> Critic -> CSCO (max 2 iterations)
csco_loop = LoopAgent(
    name="csco_planning_loop",
    sub_agents=[csco_agent, strategy_critic_agent],
    max_iterations=2,
)
