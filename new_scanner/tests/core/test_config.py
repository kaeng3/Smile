from __future__ import annotations
from jusmo_scanner.config import load_config


def test_load_config_reads_all_sections():
    cfg = load_config("config/scanner.yaml")
    assert cfg.core_event_trading_value == 50_000_000_000
    assert cfg.strong_event_value_ratio_min == 2.0
    assert cfg.strong_event_turnover_min == 0.30
    assert cfg.telegram_max_signal_age_days == 3
    assert cfg.cost_weight_event_price == 0.4
    assert cfg.cost_weight_vwap == 0.6
    assert cfg.atr_tolerance_event_low == 1.0
    assert cfg.atr_multiplier_invalidated == 2.0
    assert cfg.cost_hold_tolerance_pct is None
    assert cfg.dormant_vcr_max == 0.40
    assert cfg.dormant_range10_max == 0.15
    assert cfg.ignition_rvol20_min == 1.5
    assert cfg.breakout_rvol20_min == 1.3
    assert cfg.breakout_swing_window == 5
    assert cfg.pullback_drawdown_min == -0.12
    assert cfg.pullback_drawdown_max == -0.03
    assert cfg.pullback_volume_ratio_max == 0.5
    assert cfg.distribution_location120_min == 0.80
    assert cfg.distribution_rvol20_min == 3.0
    assert cfg.distribution_upper_wick_min == 0.40
    assert cfg.score_weight_structure_no_theme == 0.65
    assert cfg.score_weight_trigger_no_theme == 0.35
    assert cfg.score_weight_structure_with_theme == 0.50
    assert cfg.score_weight_trigger_with_theme == 0.30
    assert cfg.score_weight_theme == 0.20
    assert cfg.structure_scoring.event_score_weight == 0.20
    assert cfg.structure_scoring.low_hold_points == 15
    assert cfg.structure_scoring.cost_hold_points == 20
    assert cfg.structure_scoring.cost_distance.ideal_min == -0.02
    assert cfg.structure_scoring.cost_distance.ideal_max == 0.10
    assert cfg.structure_scoring.cost_distance.max_points == 15
    assert cfg.structure_scoring.cost_distance.penalty_scale == 200.0
    assert cfg.structure_scoring.vcr.strong_threshold == 0.25
    assert cfg.structure_scoring.vcr.normal_threshold == 0.40
    assert cfg.structure_scoring.vcr.weak_threshold == 0.60
    assert cfg.structure_scoring.vcr.strong_points == 15
    assert cfg.structure_scoring.vcr.normal_points == 12
    assert cfg.structure_scoring.vcr.weak_points == 6
    assert cfg.structure_scoring.compression.best == 0.08
    assert cfg.structure_scoring.compression.worst == 0.20
    assert cfg.structure_scoring.compression.max_points == 10
    assert cfg.structure_scoring.capital_impact.reference == 0.30
    assert cfg.structure_scoring.capital_impact.max_points == 10
    assert cfg.structure_scoring.distribution_penalty == 25
    assert cfg.trigger_scoring.ma240_cross_points == 20
    assert cfg.trigger_scoring.ma120_cross_points == 10
    assert cfg.trigger_scoring.ma5_slope_points == 10
    assert cfg.trigger_scoring.previous_high_break_points == 20
    assert cfg.trigger_scoring.trend_break_points == 20
    assert cfg.trigger_scoring.rvol.reference == 3.0
    assert cfg.trigger_scoring.rvol.max_points == 20
    assert cfg.trigger_scoring.above_ma240_points == 10
    assert cfg.trigger_scoring.use_state_bonus is False
    assert cfg.trigger_scoring.state_bonus["BREAKOUT"] == 8
    assert cfg.trigger_scoring.state_bonus["INVALIDATED"] == -20


def test_load_telegram_credentials_reads_env(monkeypatch, tmp_path):
    from jusmo_scanner.config import load_telegram_credentials
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    token, chat_id = load_telegram_credentials()
    assert token == "abc123"
    assert chat_id == "999"


def test_load_telegram_credentials_raises_when_missing(monkeypatch):
    from jusmo_scanner.config import load_telegram_credentials
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr("jusmo_scanner.config.load_dotenv", lambda *a, **k: None)
    try:
        load_telegram_credentials()
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
