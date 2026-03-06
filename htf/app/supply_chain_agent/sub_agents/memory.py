from google.adk.agents import LlmAgent

from supply_chain_agent.tools.memory_tools import (
    recall_past_disruptions,
    find_similar_past_disruptions,
    evaluate_mitigation_effectiveness,
)

memory_agent = LlmAgent(
    name="memory_agent",
    model="gemini-2.5-flash",
    instruction="""You are a supply chain memory and learning specialist.

You have access to the organization's historical disruption records and can analyze
patterns in past events to inform current decisions.

CAPABILITIES:
- Recall recent disruption events and their outcomes
- Find similar past disruptions to current situations
- Evaluate which mitigation strategies were most effective

WORKFLOW:
1. Use recall_past_disruptions to get recent history.
2. If looking for specific patterns, use find_similar_past_disruptions with
   relevant filters (event_type, region, industry).
3. Use evaluate_mitigation_effectiveness to understand what strategies worked best.

OUTPUT FORMAT:
- HISTORICAL CONTEXT: Relevant past events and their outcomes
- PATTERN ANALYSIS: Recurring disruption patterns in the supply chain
- LESSONS LEARNED: What worked and what didn't in past mitigations
- RECOMMENDATIONS: Specific suggestions based on historical precedent

Always cite specific past events with dates, impacts, and effectiveness scores.
""",
    tools=[
        recall_past_disruptions,
        find_similar_past_disruptions,
        evaluate_mitigation_effectiveness,
    ],
)
