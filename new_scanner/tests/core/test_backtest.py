from __future__ import annotations
from jusmo_scanner.backtest.engine import BacktestEngine, BacktestResult
from jusmo_scanner.backtest import metrics


def test_backtest_engine_run_on_empty_input_returns_empty_result():
    result = BacktestEngine().run(state_history=[], events=[])
    assert isinstance(result, BacktestResult)
    assert result.trades == []


def test_metrics_win_rate_empty_list_is_none():
    assert metrics.win_rate([]) is None


def test_metrics_win_rate_computes_fraction_positive():
    assert metrics.win_rate([0.05, -0.02, 0.01, -0.01]) == 0.5


def test_metrics_average_return_empty_list_is_none():
    assert metrics.average_return([]) is None


def test_metrics_max_drawdown_empty_list_is_none():
    assert metrics.max_drawdown([]) is None
