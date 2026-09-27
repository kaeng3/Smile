from __future__ import annotations
import dataclasses
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclasses.dataclass(frozen=True)
class CostDistanceScoring:
    ideal_min: float
    ideal_max: float
    max_points: float
    penalty_scale: float


@dataclasses.dataclass(frozen=True)
class VcrScoring:
    strong_threshold: float
    normal_threshold: float
    weak_threshold: float
    strong_points: float
    normal_points: float
    weak_points: float


@dataclasses.dataclass(frozen=True)
class CompressionScoring:
    best: float
    worst: float
    max_points: float


@dataclasses.dataclass(frozen=True)
class CapitalImpactScoring:
    reference: float
    max_points: float


@dataclasses.dataclass(frozen=True)
class StructureScoringConfig:
    event_score_weight: float
    low_hold_points: float
    cost_hold_points: float
    cost_distance: CostDistanceScoring
    vcr: VcrScoring
    compression: CompressionScoring
    capital_impact: CapitalImpactScoring
    distribution_penalty: float


@dataclasses.dataclass(frozen=True)
class RvolScoring:
    reference: float
    max_points: float


@dataclasses.dataclass(frozen=True)
class TriggerScoringConfig:
    ma240_cross_points: float
    ma120_cross_points: float
    ma5_slope_points: float
    previous_high_break_points: float
    trend_break_points: float
    rvol: RvolScoring
    above_ma240_points: float
    use_state_bonus: bool
    state_bonus: dict[str, float]


def normalize_horizons(hz) -> tuple[int, ...]:
    """Validates a horizons sequence (non-empty, positive ints, no bools) and
    returns it sorted and de-duplicated. Raises ValueError otherwise."""
    if isinstance(hz, (str, bytes)) or not hasattr(hz, "__iter__"):
        raise ValueError(f"backtest_horizons must be a sequence of positive ints, got {hz!r}")
    items = list(hz)
    if not items or any(not (isinstance(h, int) and not isinstance(h, bool) and h > 0) for h in items):
        raise ValueError(f"backtest_horizons must be a non-empty sequence of positive ints, got {items!r}")
    return tuple(sorted(set(items)))


@dataclasses.dataclass(frozen=True)
class ScannerConfig:
    core_event_trading_value: float
    strong_event_value_ratio_min: float
    strong_event_turnover_min: float
    cost_weight_event_price: float
    cost_weight_vwap: float
    atr_tolerance_event_low: float
    atr_multiplier_invalidated: float
    dormant_vcr_max: float
    dormant_range10_max: float
    ignition_rvol20_min: float
    breakout_rvol20_min: float
    breakout_swing_window: int
    pullback_drawdown_min: float
    pullback_drawdown_max: float
    pullback_volume_ratio_max: float
    distribution_location120_min: float
    distribution_rvol20_min: float
    distribution_upper_wick_min: float
    score_weight_structure_no_theme: float
    score_weight_trigger_no_theme: float
    score_weight_structure_with_theme: float
    score_weight_trigger_with_theme: float
    score_weight_theme: float
    structure_scoring: StructureScoringConfig
    trigger_scoring: TriggerScoringConfig
    telegram_max_signal_age_days: int
    cost_hold_tolerance_pct: float | None = None  # None = ATR rule; else 0 <= tol < 1
    # Backtest-only research settings (never influence the state machine/scoring).
    backtest_accumulation_min_days: int = 3
    backtest_accumulation_vcr_max: float = 0.50
    # Forward-return horizons in trading days (validated: positive ints; stored sorted/unique).
    backtest_horizons: tuple[int, ...] = (1, 3, 5, 10, 20, 40)
    # Sample-count thresholds (very_low_below, low_below, medium_below): n < first -> VERY_LOW,
    # < second -> LOW, < third -> MEDIUM, else HIGH. Strictly ascending positive ints.
    backtest_sample_quality: tuple[int, int, int] = (30, 100, 300)
    # Groups with fewer samples get low_sample=True (values are still shown, never hidden).
    backtest_min_sample_size: int = 100
    # ROLLING-indicator warm-up (MA240 ~ 340 calendar days + margin): used ONLY to warn when a
    # ticker's data starts less than this many calendar days before signal_start. It is NOT a
    # fetch lookback: episode history has no expiry (an episode can stay alive for years), so
    # historical fetches default to the provider's full available history.
    backtest_rolling_warmup_calendar_days: int = 600
    event_location_bottom_max: float = 0.30
    event_location_high_min: float = 0.70

    def __post_init__(self) -> None:
        lo, hi = self.event_location_bottom_max, self.event_location_high_min
        if (any(not isinstance(x, (int, float)) or isinstance(x, bool) for x in (lo, hi))
                or not 0 <= lo < hi <= 1):
            raise ValueError("event location thresholds must satisfy 0 <= bottom_max < high_min <= 1")
        # Runs for load_config AND override_config (dataclasses.replace).
        md = self.backtest_accumulation_min_days
        if not (isinstance(md, int) and not isinstance(md, bool) and md >= 0):
            raise ValueError(f"backtest_accumulation_min_days must be an int >= 0, got {md!r}")
        vm = self.backtest_accumulation_vcr_max
        if not (isinstance(vm, (int, float)) and not isinstance(vm, bool) and vm > 0):
            raise ValueError(f"backtest_accumulation_vcr_max must be a number > 0, got {vm!r}")
        object.__setattr__(self, "backtest_horizons", normalize_horizons(self.backtest_horizons))
        sq = self.backtest_sample_quality
        if isinstance(sq, (str, bytes)) or not hasattr(sq, "__iter__"):
            raise ValueError(f"backtest_sample_quality must be 3 ascending positive ints, got {sq!r}")
        sq = tuple(sq)
        if (len(sq) != 3 or any(not (isinstance(x, int) and not isinstance(x, bool) and x > 0) for x in sq)
                or not (sq[0] < sq[1] < sq[2])):
            raise ValueError(f"backtest_sample_quality must be 3 strictly ascending positive ints, got {sq!r}")
        object.__setattr__(self, "backtest_sample_quality", sq)
        ms = self.backtest_min_sample_size
        if not (isinstance(ms, int) and not isinstance(ms, bool) and ms > 0):
            raise ValueError(f"backtest_min_sample_size must be a positive int, got {ms!r}")
        wd = self.backtest_rolling_warmup_calendar_days
        if not (isinstance(wd, int) and not isinstance(wd, bool) and wd > 0):
            raise ValueError(f"backtest_rolling_warmup_calendar_days must be a positive int, got {wd!r}")
        tol = self.cost_hold_tolerance_pct
        if tol is not None and not (
            isinstance(tol, (int, float)) and not isinstance(tol, bool) and 0 <= tol < 1
        ):
            raise ValueError(f"cost_hold_tolerance_pct must be None or 0 <= tol < 1, got {tol!r}")


# The sweep axes (parameter -> ScannerConfig fields) live ONLY in backtest/parameter_grid.py.


def override_config(cfg: ScannerConfig, **kwargs) -> ScannerConfig:
    """`dataclasses.replace` that raises ValueError on unknown field names."""
    valid = {f.name for f in dataclasses.fields(ScannerConfig)}
    unknown = sorted(set(kwargs) - valid)
    if unknown:
        raise ValueError(f"unknown ScannerConfig field(s): {', '.join(unknown)}")
    return dataclasses.replace(cfg, **kwargs)


def load_config(path: str | Path) -> ScannerConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    bt = raw.get("backtest") or {}
    acc_conf = bt.get("accumulation_confirmation") or {}
    bt_kwargs: dict = {}
    if "min_days" in acc_conf:
        bt_kwargs["backtest_accumulation_min_days"] = acc_conf["min_days"]
    if "vcr_max" in acc_conf:
        bt_kwargs["backtest_accumulation_vcr_max"] = acc_conf["vcr_max"]
    if "horizons" in bt:
        bt_kwargs["backtest_horizons"] = bt["horizons"]
    sq = bt.get("sample_quality")
    if sq is not None:
        bt_kwargs["backtest_sample_quality"] = (
            sq["very_low_below"], sq["low_below"], sq["medium_below"])
    if "min_sample_size" in bt:
        bt_kwargs["backtest_min_sample_size"] = bt["min_sample_size"]
    if "rolling_warmup_calendar_days" in bt:
        bt_kwargs["backtest_rolling_warmup_calendar_days"] = bt["rolling_warmup_calendar_days"]
    return ScannerConfig(
        **bt_kwargs,
        event_location_bottom_max=raw.get("event_location", {}).get("bottom_max", 0.30),
        event_location_high_min=raw.get("event_location", {}).get("high_min", 0.70),
        core_event_trading_value=raw["event"]["core_trading_value_krw"],
        strong_event_value_ratio_min=raw["event"]["strong_value_ratio_min"],
        strong_event_turnover_min=raw["event"]["strong_turnover_min"],
        cost_weight_event_price=raw["accumulation"]["cost_weight_event_price"],
        cost_weight_vwap=raw["accumulation"]["cost_weight_vwap"],
        atr_tolerance_event_low=raw["accumulation"]["atr_tolerance_event_low"],
        atr_multiplier_invalidated=raw["accumulation"]["atr_multiplier_invalidated"],
        cost_hold_tolerance_pct=raw["accumulation"].get("cost_hold_tolerance_pct"),
        dormant_vcr_max=raw["dormant"]["vcr_max"],
        dormant_range10_max=raw["dormant"]["range10_max"],
        ignition_rvol20_min=raw["ignition"]["rvol20_min"],
        breakout_rvol20_min=raw["breakout"]["rvol20_min"],
        breakout_swing_window=raw["breakout"]["swing_high_window"],
        pullback_drawdown_min=raw["pullback"]["drawdown_min"],
        pullback_drawdown_max=raw["pullback"]["drawdown_max"],
        pullback_volume_ratio_max=raw["pullback"]["volume_ratio_max"],
        distribution_location120_min=raw["distribution_warning"]["location120_min"],
        distribution_rvol20_min=raw["distribution_warning"]["rvol20_min"],
        distribution_upper_wick_min=raw["distribution_warning"]["upper_wick_ratio_min"],
        score_weight_structure_no_theme=raw["scoring"]["structure_weight_no_theme"],
        score_weight_trigger_no_theme=raw["scoring"]["trigger_weight_no_theme"],
        score_weight_structure_with_theme=raw["scoring"]["structure_weight_with_theme"],
        score_weight_trigger_with_theme=raw["scoring"]["trigger_weight_with_theme"],
        score_weight_theme=raw["scoring"]["theme_weight"],
        structure_scoring=_load_structure_scoring(raw["scoring"]["structure"]),
        trigger_scoring=_load_trigger_scoring(raw["scoring"]["trigger"]),
        telegram_max_signal_age_days=int(raw["telegram"]["max_signal_age_days"]),
    )


def _load_structure_scoring(raw: dict) -> StructureScoringConfig:
    return StructureScoringConfig(
        event_score_weight=raw["event_score_weight"],
        low_hold_points=raw["low_hold_points"],
        cost_hold_points=raw["cost_hold_points"],
        cost_distance=CostDistanceScoring(**raw["cost_distance"]),
        vcr=VcrScoring(**raw["vcr"]),
        compression=CompressionScoring(**raw["compression"]),
        capital_impact=CapitalImpactScoring(**raw["capital_impact"]),
        distribution_penalty=raw["distribution_penalty"],
    )


def _load_trigger_scoring(raw: dict) -> TriggerScoringConfig:
    return TriggerScoringConfig(
        ma240_cross_points=raw["ma240_cross_points"],
        ma120_cross_points=raw["ma120_cross_points"],
        ma5_slope_points=raw["ma5_slope_points"],
        previous_high_break_points=raw["previous_high_break_points"],
        trend_break_points=raw["trend_break_points"],
        rvol=RvolScoring(**raw["rvol"]),
        above_ma240_points=raw["above_ma240_points"],
        use_state_bonus=raw["use_state_bonus"],
        state_bonus=dict(raw["state_bonus"]),
    )


def load_telegram_credentials() -> tuple[str, str]:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in the environment or .env"
        )
    return token, chat_id
