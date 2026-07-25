"""
TDD: risk_controls.py — pure function risk control tests.

Covers P1-4 regression, drawdown, defense, stale, minnows, apply_risk_controls pipeline.
All tests are I/O-free, pure logic verification.
"""
from __future__ import annotations
from typing import Any
import pytest
from app.engine.risk_controls import (
    MAX_SINGLE_WEIGHT,
    _consolidate_minnows,
    apply_risk_controls,
    check_defense_effectiveness,
    filter_extreme_drawdown,
    remove_stale_candidates,
)

def _strategy(allocations=None, profile='aggressive', layer_budget=None):
    return {'profile': profile, 'allocations': allocations or [], 'layer_budget': layer_budget or {'core': 0.5, 'satellite': 0.25, 'defense': 0.15}}

def _etf(symbol, weight=0.1, layer='core', rationale='base', price=10.0, return_1m=0.02, return_3m=0.05):
    return {'symbol': symbol, 'weight': weight, 'layer': layer, 'selection_rationale': rationale, 'price': price, 'return_1m': return_1m, 'return_3m': return_3m}


class TestP14Regression:
    """P1-4 regression: rationale string not corrupted by operator precedence."""

    def test_rationale_not_corrupted_when_ret_is_none(self):
        etfs = [_etf('510300', rationale='good', return_1m=None)]
        result = filter_extreme_drawdown([_strategy([etfs[0]])], {'510300': {'return_1m': None}})
        assert result[0]['allocations'][0]['selection_rationale'] == 'good'

    def test_rationale_contains_note_when_ret_is_bad(self):
        etfs = [_etf('510300', rationale='good', return_1m=-0.25)]
        result = filter_extreme_drawdown([_strategy([etfs[0]])], {'510300': {'return_1m': -0.25}})
        assert '风控' in result[0]['allocations'][0]['selection_rationale']

    def test_rationale_string_not_swallowed_by_ternary(self):
        etfs = [_etf('159338', rationale='original text', return_1m=-0.25)]
        result = filter_extreme_drawdown([_strategy([etfs[0]])], {'159338': {'return_1m': -0.25}})
        assert 'original' in result[0]['allocations'][0]['selection_rationale']


class TestDrawdown:
    """filter_extreme_drawdown: bad ETFs removed, weight redistributed."""

    def test_removes_bad_etf(self):
        etfs = [_etf('510300', weight=0.3, return_1m=-0.50), _etf('518880', weight=0.2, return_1m=0.01)]
        fm = {'510300': {'return_1m': -0.50}, '518880': {'return_1m': 0.01}}
        result = filter_extreme_drawdown([_strategy(etfs)], fm)
        symbols = {a['symbol'] for a in result[0]['allocations']}
        assert '510300' not in symbols
        assert '518880' in symbols

    def test_redistributes_weight_to_survivors(self):
        etfs = [_etf('510300', weight=0.3, return_1m=-0.50), _etf('518880', weight=0.2, return_1m=0.01)]
        fm = {'510300': {'return_1m': -0.50}, '518880': {'return_1m': 0.01}}
        result = filter_extreme_drawdown([_strategy(etfs)], fm)
        survivor = [a for a in result[0]['allocations'] if a['symbol'] == '518880'][0]
        assert survivor['weight'] > 0.2

    def test_preserves_cash(self):
        etfs = [{'symbol': 'CASH', 'weight': 0.1, 'layer': 'satellite'}, _etf('510300', weight=0.2, return_1m=-0.50)]
        result = filter_extreme_drawdown([_strategy(etfs)], {'510300': {'return_1m': -0.50}})
        assert any(a['symbol'] == 'CASH' for a in result[0]['allocations'])


class TestDefenseEffectiveness:
    """check_defense_effectiveness: defense ETFs with bad 3m return get weight halved."""

    def test_reduces_weight_when_bad(self):
        etfs = [_etf('518880', weight=0.1, layer='defense', return_3m=-0.15)]
        result = check_defense_effectiveness([_strategy(etfs)], {'518880': {'return_3m': -0.15}})
        assert result[0]['allocations'][0]['weight'] < 0.08

    def test_ignores_non_defense(self):
        etfs = [_etf('510300', weight=0.1, layer='core', return_3m=-0.20)]
        result = check_defense_effectiveness([_strategy(etfs)], {'510300': {'return_3m': -0.20}})
        assert result[0]['allocations'][0]['weight'] == 0.1


class TestStaleCandidates:
    """remove_stale_candidates: ETFs without price/return data are removed."""

    def test_removes_etf_without_data(self):
        etfs = [_etf('510300', weight=0.1, price=None, return_1m=None), _etf('518880', weight=0.1, price=10.0, return_1m=0.01)]
        fm = {'510300': {}, '518880': {'price': 10.0, 'return_1m': 0.01}}
        result = remove_stale_candidates([_strategy(etfs)], fm)
        assert '510300' not in {a['symbol'] for a in result[0]['allocations']}

    def test_preserves_cash(self):
        etfs = [{'symbol': 'CASH', 'weight': 0.1}, _etf('510300', weight=0.2, price=None, return_1m=None)]
        result = remove_stale_candidates([_strategy(etfs)], {})
        assert any(a['symbol'] == 'CASH' for a in result[0]['allocations'])


class TestConsolidateMinnows:
    """_consolidate_minnows: small defense positions merged into largest one."""

    def test_merges_small_defense(self):
        etfs = [_etf('518880', weight=0.01, layer='defense'), _etf('511090', weight=0.08, layer='defense')]
        result = _consolidate_minnows([_strategy(etfs)])
        assert len(result[0]['allocations']) == 1

    def test_does_not_merge_when_above_minimum(self):
        etfs = [_etf('518880', weight=0.05, layer='defense'), _etf('511090', weight=0.08, layer='defense')]
        result = _consolidate_minnows([_strategy(etfs)])
        assert len(result[0]['allocations']) == 2


class TestApplyRiskControls:
    """Full pipeline integration."""

    def test_pipeline_does_not_crash(self):
        fm = {'510300': {'return_1m': 0.02, 'return_3m': 0.05, 'price': 10.0}}
        result = apply_risk_controls([_strategy([_etf('510300', weight=0.3)])], fm)
        assert len(result) == 1

    def test_single_weight_not_exceed_max(self):
        fm = {'510300': {'return_1m': 0.02, 'return_3m': 0.05, 'price': 10.0}}
        result = apply_risk_controls([_strategy([_etf('510300', weight=0.5)], layer_budget={'core': 0.5})], fm)
        for a in result[0]['allocations']:
            if a.get('symbol') != 'CASH':
                assert a['weight'] <= MAX_SINGLE_WEIGHT + 0.001
