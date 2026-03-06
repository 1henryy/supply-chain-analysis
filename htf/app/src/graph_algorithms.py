from __future__ import annotations
from collections import defaultdict, deque


def build_adjacency(suppliers: list[dict]) -> tuple[dict, dict]:
    """
    Build two adjacency structures from supplier list:
      - children_of[parent_id] = [child_ids...]   (upstream direction)
      - parent_of[child_id] = parent_id            (downstream direction)
    """
    children_of: dict[int, list[int]] = defaultdict(list)
    parent_of: dict[int, int | None] = {}
    for s in suppliers:
        sid = s["id"]
        pid = s.get("parent_supplier_id")
        parent_of[sid] = pid
        if pid is not None:
            children_of[pid].append(sid)
    return dict(children_of), parent_of


def bfs_disruption_propagation(
    suppliers: list[dict],
    disrupted_supplier_id: int,
    attenuation_factor: float = 0.7,
) -> list[dict]:
    """
    BFS from a disrupted supplier DOWNSTREAM toward the manufacturer.

    Each hop attenuates the impact by `attenuation_factor`.
    Returns list of affected nodes with impact scores.

    Example: if Tier 3 supplier is disrupted at impact 1.0,
      Tier 2 sees 0.7, Tier 1 sees 0.49, manufacturer sees 0.343.
    """
    supplier_map = {s["id"]: s for s in suppliers}
    _, parent_of = build_adjacency(suppliers)

    if disrupted_supplier_id not in supplier_map:
        return []

    affected = []
    visited = set()
    queue = deque([(disrupted_supplier_id, 1.0, 0)])  # (id, impact, hops)

    while queue:
        current_id, impact, hops = queue.popleft()
        if current_id in visited:
            continue
        visited.add(current_id)

        node = supplier_map[current_id]
        affected.append({
            "supplier_id": current_id,
            "supplier_name": node["name"],
            "tier": node["tier"],
            "region": node["region"],
            "impact_score": round(impact, 4),
            "hops_from_source": hops,
        })

        # Propagate downstream
        parent_id = parent_of.get(current_id)
        if parent_id is not None and parent_id not in visited:
            queue.append((parent_id, impact * attenuation_factor, hops + 1))

    return affected


def bfs_upstream_from(
    suppliers: list[dict],
    supplier_id: int,
) -> list[dict]:
    """BFS upstream (toward raw materials) from a given supplier."""
    supplier_map = {s["id"]: s for s in suppliers}
    children_of, _ = build_adjacency(suppliers)

    if supplier_id not in supplier_map:
        return []

    result = []
    visited = set()
    queue = deque([(supplier_id, 0)])

    while queue:
        current_id, depth = queue.popleft()
        if current_id in visited:
            continue
        visited.add(current_id)

        node = supplier_map[current_id]
        result.append({
            "supplier_id": current_id,
            "supplier_name": node["name"],
            "tier": node["tier"],
            "depth_from_start": depth,
        })

        for child_id in children_of.get(current_id, []):
            if child_id not in visited:
                queue.append((child_id, depth + 1))

    return result


def analyze_cascade_risk(
    suppliers: list[dict],
    disrupted_supplier_id: int,
    supplier_product_links: list[dict],
    products: list[dict],
) -> dict:
    """
    Full cascade analysis: disruption propagation + product impact assessment.

    Returns:
      - affected_suppliers: BFS propagation results
      - affected_products: products whose supply chain is impacted
      - total_revenue_at_risk: sum of affected product revenues
      - cascade_depth: how many tiers the disruption spans
    """
    affected = bfs_disruption_propagation(suppliers, disrupted_supplier_id)
    affected_ids = {a["supplier_id"] for a in affected}

    # Find which products are impacted
    product_map = {p["id"]: p for p in products}
    affected_products = []
    total_revenue_at_risk = 0.0

    for link in supplier_product_links:
        if link["supplier_id"] in affected_ids:
            pid = link["product_id"]
            prod = product_map.get(pid)
            if prod and pid not in {ap["product_id"] for ap in affected_products}:
                # Find the impact score for this supplier
                sup_impact = next(
                    (a["impact_score"] for a in affected if a["supplier_id"] == link["supplier_id"]),
                    0.0,
                )
                affected_products.append({
                    "product_id": pid,
                    "product_name": prod["name"],
                    "criticality": prod["criticality"],
                    "annual_revenue": prod["annual_revenue"],
                    "supply_chain_impact": round(sup_impact, 4),
                    "via_supplier": link["supplier_id"],
                    "component": link["component_name"],
                    "is_critical_component": link["is_critical"],
                })
                total_revenue_at_risk += prod["annual_revenue"] * sup_impact

    cascade_depth = max((a["hops_from_source"] for a in affected), default=0)

    return {
        "disrupted_supplier_id": disrupted_supplier_id,
        "affected_suppliers": affected,
        "affected_products": affected_products,
        "total_revenue_at_risk": round(total_revenue_at_risk, 2),
        "cascade_depth": cascade_depth,
        "num_suppliers_affected": len(affected),
        "num_products_affected": len(affected_products),
    }


def _compute_pagerank(
    suppliers: list[dict],
    children_of: dict[int, list[int]],
    parent_of: dict[int, int | None],
    damping: float = 0.85,
    max_iterations: int = 100,
    tol: float = 0.0001,
) -> dict[int, float]:
    """
    Compute PageRank over the supplier directed graph (AlMahri et al. 2025).

    Edge semantics: if supplier B has parent_supplier_id = A then there is
    an edge B -> A (B feeds into A).  A supplier that many others feed into
    receives more PageRank, reflecting its structural importance.

    Uses the standard iterative power-method with damping factor 0.85.

    Returns:
        Dict mapping supplier_id -> PageRank score (sums to ~1.0).
    """
    all_ids = [s["id"] for s in suppliers]
    n = len(all_ids)
    if n == 0:
        return {}

    # Build outgoing-edge lookup: for each node, which nodes does it link to?
    # Edge B -> A exists when B has parent_supplier_id = A
    out_links: dict[int, list[int]] = defaultdict(list)
    for s in suppliers:
        sid = s["id"]
        pid = s.get("parent_supplier_id")
        if pid is not None:
            out_links[sid].append(pid)

    # Initialise uniform ranks
    rank: dict[int, float] = {sid: 1.0 / n for sid in all_ids}

    for _ in range(max_iterations):
        new_rank: dict[int, float] = {}
        # Collect rank mass from dangling nodes (no outgoing edges)
        dangling_sum = sum(rank[sid] for sid in all_ids if not out_links[sid])

        for sid in all_ids:
            # Incoming contribution: sum over all nodes that have an edge -> sid
            # Node j links to sid if sid is in out_links[j]
            incoming = 0.0
            for j in children_of.get(sid, []):
                # j -> sid is an edge (j feeds into sid)
                out_count = len(out_links[j])
                if out_count > 0:
                    incoming += rank[j] / out_count

            new_rank[sid] = (
                (1.0 - damping) / n
                + damping * (incoming + dangling_sum / n)
            )

        # Check convergence
        delta = sum(abs(new_rank[sid] - rank[sid]) for sid in all_ids)
        rank = new_rank
        if delta < tol:
            break

    return rank


def calculate_graph_centrality(suppliers: list[dict]) -> list[dict]:
    """
    Calculate degree, betweenness, and PageRank centrality for each supplier.

    Degree centrality = (in_degree + out_degree) / (N - 1)
    Betweenness approximation = count of paths through this node / total paths
    PageRank = iterative importance score (damping 0.85, per AlMahri et al. 2025)

    Returns suppliers sorted by combined centrality (highest first).
    """
    children_of, parent_of = build_adjacency(suppliers)
    supplier_map = {s["id"]: s for s in suppliers}
    n = len(suppliers)
    if n <= 1:
        return []

    # Degree centrality
    in_degree = defaultdict(int)
    out_degree = defaultdict(int)
    for s in suppliers:
        sid = s["id"]
        pid = s.get("parent_supplier_id")
        if pid is not None:
            out_degree[sid] += 1  # this node has an outgoing edge to parent
            in_degree[pid] += 1   # parent receives an incoming edge

    # Betweenness: for each leaf, trace path to root, count intermediaries
    leaves = [s["id"] for s in suppliers if s["id"] not in children_of]
    path_count = defaultdict(int)
    total_paths = 0

    for leaf in leaves:
        path = []
        current = leaf
        while current is not None:
            path.append(current)
            current = parent_of.get(current)
        # Intermediate nodes (not source, not final)
        for node in path[1:]:
            path_count[node] += 1
        total_paths += 1

    # PageRank (AlMahri et al. 2025)
    pagerank = _compute_pagerank(suppliers, children_of, parent_of)

    results = []
    for s in suppliers:
        sid = s["id"]
        deg_centrality = (in_degree.get(sid, 0) + out_degree.get(sid, 0)) / max(n - 1, 1)
        betweenness = path_count.get(sid, 0) / max(total_paths, 1)
        pr = pagerank.get(sid, 0.0)
        # Combined centrality now incorporates all three signals
        combined = (deg_centrality + betweenness + pr) / 3
        results.append({
            "supplier_id": sid,
            "supplier_name": s["name"],
            "tier": s["tier"],
            "degree_centrality": round(deg_centrality, 4),
            "betweenness_centrality": round(betweenness, 4),
            "pagerank": round(pr, 4),
            "combined_centrality": round(combined, 4),
            "in_degree": in_degree.get(sid, 0),
            "out_degree": out_degree.get(sid, 0),
        })

    results.sort(key=lambda x: x["combined_centrality"], reverse=True)
    return results


def detect_spofs(suppliers: list[dict]) -> list[dict]:
    """
    Detect Single Points of Failure:
      1. Suppliers explicitly flagged as is_single_source
      2. Tier 1 suppliers with no alternative (only supplier for a parent)
      3. Nodes where removal disconnects part of the graph
      4. Nodes with high PageRank centrality (AlMahri et al. 2025)
    """
    children_of, parent_of = build_adjacency(suppliers)
    supplier_map = {s["id"]: s for s in suppliers}

    # Compute PageRank to identify structurally critical nodes
    pagerank = _compute_pagerank(suppliers, children_of, parent_of)
    # Determine high-PageRank threshold: top 15% of scores (at least 2x average)
    n = len(suppliers)
    avg_pr = 1.0 / max(n, 1)
    pr_threshold = max(avg_pr * 2.0, sorted(pagerank.values(), reverse=True)[max(n // 7, 1) - 1]) if n > 1 else 0

    spofs = []

    for s in suppliers:
        sid = s["id"]
        reasons = []

        # Explicitly flagged
        if s.get("is_single_source"):
            reasons.append("Flagged as single-source supplier")

        # Only child of its parent (no alternative at this level)
        pid = s.get("parent_supplier_id")
        if pid is not None:
            siblings = children_of.get(pid, [])
            if len(siblings) == 1:
                reasons.append(f"Only supplier feeding into {supplier_map.get(pid, {}).get('name', pid)}")

        # High number of dependents (many children rely on this)
        num_children = len(children_of.get(sid, []))
        if num_children >= 3:
            reasons.append(f"Critical hub: {num_children} upstream suppliers depend on it")

        # High PageRank -- structurally critical node (per AlMahri et al. 2025)
        pr_score = pagerank.get(sid, 0.0)
        if pr_score >= pr_threshold:
            reasons.append(f"High PageRank centrality ({round(pr_score, 4)}): many supply paths converge here")

        if reasons:
            spofs.append({
                "supplier_id": sid,
                "supplier_name": s["name"],
                "tier": s["tier"],
                "region": s.get("region", "unknown"),
                "pagerank": round(pr_score, 4),
                "reasons": reasons,
                "severity": "critical" if len(reasons) >= 2 else "high",
            })

    return spofs


def aggregate_risk_to_tier1(
    suppliers: list[dict],
    disrupted_supplier_id: int,
    supplier_product_links: list[dict],
    products: list[dict],
) -> list[dict]:
    """
    Tier-1 risk aggregation (per AlMahri et al. 2025).

    Maps any upstream disruption to its Tier-1 impact. Companies have direct
    operational control only over Tier-1 suppliers, so upstream disruptions must
    be expressed as Tier-1 risk to be actionable.

    For each Tier-1 supplier on the disruption path, aggregates:
    - exposure_breadth: fraction of Tier-1's sub-suppliers affected
    - dependency_ratio: how many of Tier-1's products depend on the disrupted path
    - downstream_criticality: max criticality weight of affected products
    - exposure_depth: how deep the disruption originates (normalized)
    """
    children_of, parent_of = build_adjacency(suppliers)
    supplier_map = {s["id"]: s for s in suppliers}
    product_map = {p["id"]: p for p in products}

    if disrupted_supplier_id not in supplier_map:
        return []

    # Trace from disrupted supplier down to Tier 1
    affected = bfs_disruption_propagation(suppliers, disrupted_supplier_id)
    affected_ids = {a["supplier_id"] for a in affected}

    # Find which Tier-1 suppliers are on the disruption path
    tier1_on_path = [a for a in affected if supplier_map[a["supplier_id"]]["tier"] == 1]

    crit_weights = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
    max_depth = max((s["tier"] for s in suppliers), default=1)
    disrupted_tier = supplier_map[disrupted_supplier_id]["tier"]

    results = []
    for t1 in tier1_on_path:
        t1_id = t1["supplier_id"]
        t1_info = supplier_map[t1_id]

        # Count total upstream suppliers feeding this Tier-1
        all_upstream = bfs_upstream_from(suppliers, t1_id)
        total_upstream = len([u for u in all_upstream if u["supplier_id"] != t1_id])

        # Count how many of those are affected
        affected_upstream = len(affected_ids & {u["supplier_id"] for u in all_upstream} - {t1_id})

        # Exposure breadth
        exposure_breadth = affected_upstream / max(total_upstream, 1)

        # Products depending on this Tier-1
        t1_products = [l for l in supplier_product_links if l["supplier_id"] == t1_id]
        total_t1_products = len(t1_products)

        # Products affected by the disruption through this Tier-1
        affected_product_ids = set()
        for link in supplier_product_links:
            if link["supplier_id"] in affected_ids:
                affected_product_ids.add(link["product_id"])
        t1_affected_products = [l for l in t1_products if l["product_id"] in affected_product_ids]

        dependency_ratio = len(t1_affected_products) / max(total_t1_products, 1)

        # Downstream criticality — max criticality of affected products
        downstream_criticality = 0
        for l in t1_affected_products:
            prod = product_map.get(l["product_id"])
            if prod:
                downstream_criticality = max(
                    downstream_criticality,
                    crit_weights.get(prod["criticality"], 0.5),
                )

        # Exposure depth (normalized)
        exposure_depth = disrupted_tier / max(max_depth, 1)

        # Combined Tier-1 risk
        tier1_risk = (
            0.35 * exposure_breadth
            + 0.25 * dependency_ratio
            + 0.20 * downstream_criticality
            + 0.10 * t1["impact_score"]  # propagated impact from BFS
            + 0.10 * exposure_depth
        )

        results.append({
            "tier1_supplier_id": t1_id,
            "tier1_supplier_name": t1_info["name"],
            "tier1_region": t1_info["region"],
            "aggregated_risk_score": round(tier1_risk, 4),
            "exposure_breadth": round(exposure_breadth, 4),
            "dependency_ratio": round(dependency_ratio, 4),
            "downstream_criticality": round(downstream_criticality, 4),
            "propagated_impact": t1["impact_score"],
            "exposure_depth": round(exposure_depth, 4),
            "disruption_source_tier": disrupted_tier,
            "products_at_risk": len(t1_affected_products),
        })

    results.sort(key=lambda x: x["aggregated_risk_score"], reverse=True)
    return results


def trace_disruption_paths(
    suppliers: list[dict],
    from_supplier_id: int,
) -> list[list[dict]]:
    """
    Trace all paths from a supplier downstream to Tier 1 (manufacturer boundary).
    Returns list of paths, where each path is a list of supplier dicts.
    """
    supplier_map = {s["id"]: s for s in suppliers}
    _, parent_of = build_adjacency(suppliers)

    if from_supplier_id not in supplier_map:
        return []

    paths = []
    current = from_supplier_id
    path = []

    while current is not None:
        node = supplier_map.get(current)
        if node is None:
            break
        path.append({
            "supplier_id": current,
            "supplier_name": node["name"],
            "tier": node["tier"],
            "region": node.get("region", "unknown"),
        })
        current = parent_of.get(current)

    if path:
        paths.append(path)

    return paths
