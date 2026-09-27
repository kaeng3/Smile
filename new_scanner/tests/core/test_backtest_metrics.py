from __future__ import annotations

import math

import numpy as np
import pytest

from jusmo_scanner.backtest import metrics
from jusmo_scanner.backtest.metrics import CLOSE_MODE_WARNING, DEFAULT_HORIZONS, EntryMode, forward_metrics
from jusmo_scanner.config import load_config, override_config

CFG = load_config("config/scanner.yaml")

# hand-computed fixture: bars 0..5
OPEN = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
HIGH = [110.0, 106.0, 112.0, 108.0, 109.0, 111.0]
LOW = [90.0, 99.0, 98.0, 100.0, 101.0, 102.0]
CLOSE = [100.0, 103.0, 104.0, 105.0, 106.0, 107.0]


def _fm(mode, i=1, h=3, o=OPEN, hi=HIGH, lo=LOW, c=CLOSE):
    return forward_metrics(o, hi, lo, c, i, h, mode)


def test_next_open_numeric_example():
    r = _fm(EntryMode.NEXT_OPEN)  # entry = open[2] = 102; window bars 2..4
    assert r.entry_price == 102.0
    assert r.forward_return == pytest.approx(106 / 102 - 1)
    assert r.mfe == pytest.approx(112 / 102 - 1)
    assert r.mae == pytest.approx(98 / 102 - 1)
    assert (r.hit_up_5, r.hit_up_10) == (True, False)
    assert (r.hit_down_3, r.hit_down_5) == (True, False)


def test_close_mode_numeric_example():
    r = _fm(EntryMode.CLOSE)  # entry = close[1] = 103; same window 2..4
    assert r.entry_price == 103.0
    assert r.forward_return == pytest.approx(106 / 103 - 1)
    assert r.mfe == pytest.approx(112 / 103 - 1)
    assert r.mae == pytest.approx(98 / 103 - 1)
    assert (r.hit_up_5, r.hit_up_10) == (True, False)
    assert (r.hit_down_3, r.hit_down_5) == (True, False)  # -4.85% <= -3%


def test_close_mode_warning_and_defaults():
    assert "optimistic" in CLOSE_MODE_WARNING and "close" in CLOSE_MODE_WARNING.lower()
    assert DEFAULT_HORIZONS == (1, 3, 5, 10, 20, 40)
    assert CFG.backtest_horizons == DEFAULT_HORIZONS
    assert [m.name for m in EntryMode] == ["NEXT_OPEN", "CLOSE"]


def test_future_return_starts_after_signal_bar():
    # h=1 from signal bar 1: NEXT_OPEN enters at bar 2's open and exits at bar 2's close
    r = _fm(EntryMode.NEXT_OPEN, h=1)
    assert r.entry_price == OPEN[2] and r.forward_return == pytest.approx(CLOSE[2] / OPEN[2] - 1)
    # CLOSE mode: enters at the signal close, exits at close[i+1]
    r = _fm(EntryMode.CLOSE, h=1)
    assert r.forward_return == pytest.approx(CLOSE[2] / CLOSE[1] - 1)
    # NEXT_OPEN result depends only on bars > i (open/close/high/low of bars <= i are ignored)
    a = _fm(EntryMode.NEXT_OPEN, i=1, h=2)
    o2, c2, h2, l2 = list(OPEN), list(CLOSE), list(HIGH), list(LOW)
    o2[0] = o2[1] = c2[0] = c2[1] = 1.0
    h2[0] = h2[1] = 999.0
    l2[0] = l2[1] = 0.5
    assert a == _fm(EntryMode.NEXT_OPEN, i=1, h=2, o=o2, hi=h2, lo=l2, c=c2)


@pytest.mark.parametrize("mode", list(EntryMode))
def test_mfe_excludes_signal_bar(mode):
    hi = list(HIGH)
    hi[1] = 500.0  # extreme signal-bar high: would dominate MFE if included
    base, ext = _fm(mode), _fm(mode, hi=hi)
    assert ext.mfe == base.mfe and ext.mfe < 1.0
    assert ext.hit_up_30 is False and base.hit_up_30 is False


@pytest.mark.parametrize("mode", list(EntryMode))
def test_mae_excludes_signal_bar(mode):
    lo = list(LOW)
    lo[1] = 1.0  # extreme signal-bar low: would give MAE ~ -99% if included
    ext, base = _fm(mode, lo=lo), _fm(mode)
    assert base.mae == ext.mae and ext.mae > -0.5
    assert ext.hit_down_20 is False


def test_window_includes_last_bar_and_excludes_bars_after():
    hi = list(HIGH)
    hi[5] = 999.0  # after the horizon end (e = 4)
    assert _fm(EntryMode.NEXT_OPEN, hi=hi).mfe == _fm(EntryMode.NEXT_OPEN).mfe
    hi = list(HIGH)
    hi[4] = 999.0  # exactly the horizon end bar: included
    assert _fm(EntryMode.NEXT_OPEN, hi=hi).mfe == pytest.approx(999 / 102 - 1)


def test_hit_thresholds_independent_and_inclusive():
    # entry (NEXT_OPEN) = 1000; one bar with high +15% and low -10% exactly
    o = [1000.0, 1000.0, 1000.0]
    r = forward_metrics(o, [1000.0, 1150.0, 1000.0], [1000.0, 900.0, 1000.0], o, 0, 1, EntryMode.NEXT_OPEN)
    assert (r.hit_up_5, r.hit_up_10, r.hit_up_15, r.hit_up_20, r.hit_up_30) == (True, True, True, False, False)
    assert (r.hit_down_3, r.hit_down_5, r.hit_down_10, r.hit_down_15, r.hit_down_20) == (
        True, True, True, False, False)  # both directions can hit; order unknown
    r = forward_metrics(o, [1000.0, 1049.9, 1000.0], [1000.0, 970.1, 1000.0], o, 0, 1, EntryMode.NEXT_OPEN)
    assert (r.hit_up_5, r.hit_down_3) == (False, False)


def test_missing_next_bar_or_horizon_returns_none():
    n = len(CLOSE)
    assert forward_metrics(OPEN, HIGH, LOW, CLOSE, n - 1, 1, EntryMode.NEXT_OPEN) is None
    assert forward_metrics(OPEN, HIGH, LOW, CLOSE, n - 1, 1, EntryMode.CLOSE) is None
    assert _fm(EntryMode.CLOSE, i=2, h=3) is not None      # e = 5 = n-1
    assert _fm(EntryMode.CLOSE, i=3, h=3) is None          # e = 6: no partial window
    assert _fm(EntryMode.NEXT_OPEN, i=3, h=3) is None


def test_bad_arguments_raise_but_bad_prices_do_not():
    with pytest.raises(ValueError):
        _fm(EntryMode.CLOSE, h=0)
    with pytest.raises(ValueError):
        _fm(EntryMode.CLOSE, i=-1)
    assert forward_metrics(OPEN[:3], HIGH, LOW, CLOSE, 0, 1, EntryMode.CLOSE) is None  # ragged


@pytest.mark.parametrize("mode", list(EntryMode))
@pytest.mark.parametrize("field,idx", [("o", 2), ("h", 3), ("lo", 4), ("c", 4), ("c", 1)])
@pytest.mark.parametrize("bad", [float("nan"), 0.0, -5.0, float("inf")])
def test_bad_prices_return_none(mode, field, idx, bad):
    arrs = {"o": list(OPEN), "h": list(HIGH), "lo": list(LOW), "c": list(CLOSE)}
    arrs[field][idx] = bad
    r = forward_metrics(arrs["o"], arrs["h"], arrs["lo"], arrs["c"], 1, 3, mode)
    # open[2] is only used as the NEXT_OPEN entry; close[1] only as the CLOSE entry
    unused = (field == "o" and mode is EntryMode.CLOSE) or (
        field == "c" and idx == 1 and mode is EntryMode.NEXT_OPEN)
    if unused:
        assert r is not None
    else:
        assert r is None


def test_numpy_input_and_no_numpy_scalars_in_result():
    r = forward_metrics(np.array(OPEN), np.array(HIGH), np.array(LOW), np.array(CLOSE), 1, 3, EntryMode.NEXT_OPEN)
    assert type(r.forward_return) is float and type(r.hit_up_5) is bool
    assert all(math.isfinite(v) for v in (r.entry_price, r.forward_return, r.mfe, r.mae))


def test_legacy_helpers_still_work():
    assert metrics.win_rate([0.1, -0.1]) == 0.5
    assert metrics.average_return([0.1, 0.3]) == pytest.approx(0.2)
    assert metrics.max_drawdown([0.1, -0.5]) == pytest.approx(-0.5)


# --- horizons config ---------------------------------------------------------

def test_horizons_config_sorted_unique_and_validated(tmp_path):
    assert override_config(CFG, backtest_horizons=[10, 3, 3, 1]).backtest_horizons == (1, 3, 10)
    for bad in ([], [0], [-1], [1.5], ["3"], [True], 5, "12"):
        with pytest.raises(ValueError):
            override_config(CFG, backtest_horizons=bad)
    p = tmp_path / "c.yaml"
    with open("config/scanner.yaml", encoding="utf-8") as fh:
        src = fh.read()
    p.write_text(src.replace("horizons: [1, 3, 5, 10, 20, 40]", "horizons: [20, 5, 5]"), encoding="utf-8")
    assert load_config(p).backtest_horizons == (5, 20)
    p.write_text(src.replace("horizons: [1, 3, 5, 10, 20, 40]", "horizons: [0, 5]"), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(p)
    # a config without any backtest section still loads with defaults
    p.write_text(src.split("# Research-only backtest settings")[0], encoding="utf-8")
    c = load_config(p)
    assert c.backtest_horizons == DEFAULT_HORIZONS and c.backtest_accumulation_min_days == 3
