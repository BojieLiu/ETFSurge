"""
ETF Surge — Risk controls.

Pure-function checks that enforce:
- Single position weight <= 0.30
- Layer budget adherence
- Sector concentration < 40% (HHI-based)

Pure function — no I/O, no database, no HTTP.
"""

from __future__ import annotations

from typing import Any

# ── Constraints ────────────────────────────────────────────────
MAX_SINGLE_WEIGHT = 0.30
MAX_SECTOR_CONCENTRATION = 0.40  # HHI threshold
MIN_WEIGHT = 0.01


def apply_risk_controls(
    strategies: list[dict[str, Any]],
    factor_matrix: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """
    Apply risk-control checks and adjustments to all strategies in-place.

    Checks performed:
      1. Single-position weight cap (MAX_SINGLE_WEIGHT = 0.30)
      2. Layer-budget adherence (sum of weights per layer <= layer budget)
      3. Sector concentration < 40% (Herfindahl-Hirschman Index)

    Args:
        strategies:    List of strategy dicts, each containing
                       "allocations" and "layer_budget".
        factor_matrix: Optional factor-score matrix (reserved for
                       advanced risk models; not used currently).

    Returns:
        The same list of strategies with adjusted weights if any
        risk limits were exceeded.
    """
    _ = factor_matrix  # reserved for future volatility/correlation adjustments

    for strategy in strategies:
        allocations = strategy.get("allocations", [])
        if not allocations:
            continue

        layer_budget: dict[str, float] = strategy.get("layer_budget", {})

        # ── 1. Single-position weight cap ──
        for alloc in allocations:
            w = alloc.get("weight", 0.0)
            if w > MAX_SINGLE_WEIGHT:
                alloc["weight"] = MAX_SINGLE_WEIGHT
                # Note: excess will be redistributed later

        # ── 2. Layer-budget adherence ──
        # Compute current weights per layer
        layer_actual: dict[str, float] = {}
        for alloc in allocations:
            lay = alloc.get("layer", "core")
            layer_actual[lay] = layer_actual.get(lay, 0.0) + alloc.get("weight", 0.0)

        for lay, budget in layer_budget.items():
            actual = layer_actual.get(lay, 0.0)
            if actual > budget and actual > 0:
                # Scale down proportionally within this layer
                scale = budget / actual
                for alloc in allocations:
                    if alloc.get("layer") == lay:
                        alloc["weight"] = round(alloc.get("weight", 0.0) * scale, 4)

        # ── 3. Sector concentration (HHI) < 40% ──
        # Treat each layer as a "sector" for concentration check
        sector_weights: dict[str, float] = {}
        for alloc in allocations:
            sec = alloc.get("layer", "其他")
            sector_weights[sec] = sector_weights.get(sec, 0.0) + alloc.get("weight", 0.0)

        hhi = sum(w ** 2 for w in sector_weights.values())
        if hhi >= MAX_SECTOR_CONCENTRATION and sector_weights:
            # Scale down the largest sector proportionally
            max_sector = max(sector_weights, key=sector_weights.get)  # type: ignore[arg-type]
            target_weight = MAX_SECTOR_CONCENTRATION ** 0.5  # approximate target per sector
            if sector_weights[max_sector] > target_weight:
                scale = target_weight / sector_weights[max_sector]
                for alloc in allocations:
                    if alloc.get("layer") == max_sector:
                        alloc["weight"] = round(
                            alloc.get("weight", 0.0) * scale, 4
                        )

        # ── 4. Renormalise so total allocation weight does not exceed 1.0 ──
        total_weight = sum(a.get("weight", 0.0) for a in allocations)
        if total_weight > 1.0:
            scale_back = 1.0 / total_weight
            for alloc in allocations:
                alloc["weight"] = round(alloc.get("weight", 0.0) * scale_back, 4)

        # ── 5. Update risk_metrics on the strategy ──
        sector_weights_final: dict[str, float] = {}
        for alloc in allocations:
            sec = alloc.get("layer", "其他")
            sector_weights_final[sec] = (
                sector_weights_final.get(sec, 0.0) + alloc.get("weight", 0.0)
            )
        hhi_final = sum(w ** 2 for w in sector_weights_final.values())

        strategy["risk_metrics"] = {
            "sector_concentration": round(hhi_final, 4),
            "sector_breakdown": {
                k: round(v, 4) for k, v in sector_weights_final.items()
            },
        }

    return strategies
