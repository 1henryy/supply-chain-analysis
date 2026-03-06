from google.adk.agents import LlmAgent, SequentialAgent

from supply_chain_agent.tools.planning_tools import (
    find_alternative_suppliers,
    simulate_mitigation_tradeoffs,
)
from supply_chain_agent.tools.action_tools import (
    draft_supplier_email,
    generate_po_adjustment,
    create_escalation_alert,
    record_disruption,
    apply_disruption_impact,
    trigger_emergency_reorder,
)

# Alternative Sourcing Agent
alternative_sourcing_agent = LlmAgent(
    name="alternative_sourcing_agent",
    model="gemini-2.5-flash-lite",
    instruction="""You are a supplier sourcing specialist.

Based on the CSCO's mitigation plan from the previous step, identify and evaluate
alternative suppliers for any disrupted or at-risk components.

WORKFLOW:
1. For each disrupted/at-risk supplier mentioned in the plan, use find_alternative_suppliers.
2. For the best alternatives, use simulate_mitigation_tradeoffs to compare strategies.
3. Rank alternatives by suitability and flag any gaps where no alternative exists.

OUTPUT FORMAT:
- SOURCING RECOMMENDATIONS: For each at-risk supplier, the top 1-2 alternatives
- STRATEGY COMPARISON: Cost/time/risk tradeoffs for reroute vs dual_source vs buffer
- SOURCING GAPS: Components where no viable alternative was found (CRITICAL FLAG)
- RECOMMENDED APPROACH: The specific strategy to pursue for each component

Be specific with supplier IDs and names.
""",
    tools=[
        find_alternative_suppliers,
        simulate_mitigation_tradeoffs,
    ],
)

# Action Execution Agent
action_execution_agent = LlmAgent(
    name="action_execution_agent",
    model="gemini-2.5-flash-lite",
    instruction="""You are a supply chain action execution specialist.

Based on the mitigation plan and sourcing recommendations, take concrete actions:

WORKFLOW:
1. Use apply_disruption_impact to degrade the affected supplier's state in the database
   (reliability, lead time, capacity) so downstream analysis reflects the new reality.
2. For each product that falls below reorder point after impact, use trigger_emergency_reorder.
3. For each recommended supplier engagement, use draft_supplier_email.
4. For any additional purchase orders, use generate_po_adjustment.
5. For high/critical risk situations, use create_escalation_alert.
6. Use record_disruption to log the current event for future learning.

ACTION RULES:
- CRITICAL risk: apply_disruption_impact + trigger_emergency_reorder + escalation alert + emails
- HIGH risk (score >= 0.6): apply_disruption_impact + escalation alert + draft emails + generate PO
- MEDIUM risk (0.45-0.59): apply_disruption_impact + draft emails + generate PO
- LOW risk (< 0.45): Record event only, no immediate action needed
- Revenue at risk > $5M: Always create escalation alert with board notification

OUTPUT FORMAT:
- IMPACT APPLIED: Which suppliers were degraded and by how much
- INVENTORY IMPACT: Products affected, units lost, emergency reorders triggered
- EMAILS DRAFTED: Summary of supplier communications (pending human review)
- PO ADJUSTMENTS: Any purchase order changes (pending approval if high risk)
- ESCALATION ALERTS: Any alerts created and their routing
- RECORDED EVENTS: Disruptions logged for memory/learning

All high-risk actions are flagged as requiring human approval before execution.
""",
    tools=[
        draft_supplier_email,
        generate_po_adjustment,
        create_escalation_alert,
        record_disruption,
        apply_disruption_impact,
        trigger_emergency_reorder,
    ],
)

# SequentialAgent: Alternative Sourcing -> Action Execution
action_pipeline = SequentialAgent(
    name="action_pipeline",
    sub_agents=[alternative_sourcing_agent, action_execution_agent],
)
