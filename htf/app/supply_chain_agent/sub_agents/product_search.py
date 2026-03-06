"""
Agent 3: Product Search (LlmAgent)

Maps disrupted suppliers to affected products.
Builds company-product chains preserving tier order.
"""

from google.adk.agents import LlmAgent

from supply_chain_agent.tools.product_tools import (
    query_suppliers_by_industry,
    assess_inventory_risk,
    map_suppliers_to_products,
)
from supply_chain_agent.tools.graph_tools import get_full_supply_chain_snapshot

product_search_agent = LlmAgent(
    name="product_search_agent",
    model="gemini-2.5-flash-lite",
    instruction="""You are a product impact analyst for a supply chain system.

Your job is to map disrupted suppliers to affected finished products and assess
inventory exposure.

WORKFLOW:
1. Use assess_inventory_risk to get current stock levels and risk for all products.
2. Based on findings from Agent 2 (knowledge graph), use map_suppliers_to_products
   to identify which products are affected by disrupted suppliers.
3. If specific industries are affected, use query_suppliers_by_industry to find
   all suppliers in that sector.

OUTPUT FORMAT:
- INVENTORY STATUS: Current stock levels and risk classification for each product
- AFFECTED PRODUCTS: Products impacted by identified disruptions
- SUPPLY CHAIN MAPPING: Which suppliers feed into which products (preserve tier order)
- CRITICAL GAPS: Products at highest risk (low stock + disrupted supply)
- REVENUE EXPOSURE: Total annual revenue at risk from identified disruptions

Prioritize critical and high-criticality products. Flag any product that is both
below reorder point AND has disrupted suppliers.
""",
    tools=[
        query_suppliers_by_industry,
        assess_inventory_risk,
        map_suppliers_to_products,
        get_full_supply_chain_snapshot,
    ],
)
