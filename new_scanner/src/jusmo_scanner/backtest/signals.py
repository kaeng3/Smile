"""Backtest signal types and causal extraction from a snapshot-collecting scan.

Signals are a pure post-processing of `TickerScan.snapshots`; nothing here reads
prices, so a signal at bar i can only depend on information known at bar i.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from jusmo_scanner.scanner.engine import TickerScan
from jusmo_scanner.scanner.snapshot import SignalSnapshot


class SignalCategory(Enum):
    STATE = "STATE"
    TRANSITION = "TRANSITION"
    FEATURE = "FEATURE"


class SignalType(Enum):
    # state signals: bars whose state == S (EVENT: bars where an event was detected)
    EVENT = "EVENT"
    ACCUMULATION = "ACCUMULATION"
    DORMANT = "DORMANT"
    IGNITION = "IGNITION"
    BREAKOUT = "BREAKOUT"
    PULLBACK = "PULLBACK"
    COST_TRACKING = "COST_TRACKING"
    # transition signals: (previous_state, state) pair on that bar
    EVENT_TO_ACCUMULATION = "EVENT_TO_ACCUMULATION"
    ACCUMULATION_TO_DORMANT = "ACCUMULATION_TO_DORMANT"
    DORMANT_TO_IGNITION = "DORMANT_TO_IGNITION"
    IGNITION_TO_BREAKOUT = "IGNITION_TO_BREAKOUT"
    BREAKOUT_TO_PULLBACK = "BREAKOUT_TO_PULLBACK"
    # feature signals: flags on the snapshot
    MA120_CROSS = "MA120_CROSS"
    MA240_CROSS = "MA240_CROSS"
    PREVIOUS_HIGH_BREAK = "PREVIOUS_HIGH_BREAK"
    TREND_BREAK = "TREND_BREAK"
    STRONG_EVENT = "STRONG_EVENT"
    MULTI_EVENT_CLUSTER = "MULTI_EVENT_CLUSTER"
    # research feature: fires ONCE per episode, on the first bar whose snapshot flag
    # `accumulation_confirmed` is true (see `extract_signals`)
    ACCUMULATION_CONFIRMED = "ACCUMULATION_CONFIRMED"

    @property
    def category(self) -> SignalCategory:
        return _CATEGORY[self]


_STATE_TYPES = (SignalType.EVENT, SignalType.ACCUMULATION, SignalType.DORMANT,
                SignalType.IGNITION, SignalType.BREAKOUT, SignalType.PULLBACK, SignalType.COST_TRACKING)
_TRANSITION_PAIRS: dict[SignalType, tuple[str, str]] = {
    SignalType.EVENT_TO_ACCUMULATION: ("EVENT", "ACCUMULATION"),
    SignalType.ACCUMULATION_TO_DORMANT: ("ACCUMULATION", "DORMANT"),
    SignalType.DORMANT_TO_IGNITION: ("DORMANT", "IGNITION"),
    SignalType.IGNITION_TO_BREAKOUT: ("IGNITION", "BREAKOUT"),
    SignalType.BREAKOUT_TO_PULLBACK: ("BREAKOUT", "PULLBACK"),
}
_FEATURE_TYPES = (SignalType.MA120_CROSS, SignalType.MA240_CROSS, SignalType.PREVIOUS_HIGH_BREAK,
                  SignalType.TREND_BREAK, SignalType.STRONG_EVENT, SignalType.MULTI_EVENT_CLUSTER,
                  SignalType.ACCUMULATION_CONFIRMED)
# feature types that are pure functions of ONE snapshot (ACCUMULATION_CONFIRMED needs the
# episode's earlier bars, so extract_signals adds it)
_SNAPSHOT_FEATURES = tuple(t for t in _FEATURE_TYPES if t is not SignalType.ACCUMULATION_CONFIRMED)
_CATEGORY: dict[SignalType, SignalCategory] = {
    **{t: SignalCategory.STATE for t in _STATE_TYPES},
    **{t: SignalCategory.TRANSITION for t in _TRANSITION_PAIRS},
    **{t: SignalCategory.FEATURE for t in _FEATURE_TYPES},
}

_EVENT_BASELINE = (
    "EVENT_BASELINE (unconfirmed: fires on the event bar itself, not a confirmation of "
    "accumulation; same sample as EVENT and EVENT_TO_ACCUMULATION at the anchor bar)"
)
_ACCUMULATION_CONFIRMED = (
    "ACCUMULATION_CONFIRMED (research feature, state machine untouched: once per episode, on the "
    "first bar where the derived accumulation_confirmed flag is true = days since the event >= "
    "min_days AND event low held AND estimated cost held AND vcr_anchor <= vcr_max)"
)
_EVENT_ANCHOR_CAVEAT = (
    "EVENT (caveat: anchor-bar EVENT == EVENT_BASELINE sample, i.e. an EVENT signal on the episode's anchor bar; "
    "in FIRST_SIGNAL_PER_EPISODE mode EVENT, ACCUMULATION and EVENT_TO_ACCUMULATION "
    "select byte-identical samples)"
)
SIGNAL_SEMANTICS: dict[SignalType, str] = {
    SignalType.EVENT: _EVENT_ANCHOR_CAVEAT,
    SignalType.ACCUMULATION: _EVENT_BASELINE,
    SignalType.EVENT_TO_ACCUMULATION: _EVENT_BASELINE,
    SignalType.ACCUMULATION_CONFIRMED: _ACCUMULATION_CONFIRMED,
}


def signal_semantics(signal_type: SignalType) -> str:
    """Label reports/CSVs must attach to a signal type. ACCUMULATION and
    EVENT_TO_ACCUMULATION are an unconfirmed event baseline (use the snapshot's
    `accumulation_confirmed` flag to split them); EVENT carries the anchor-bar
    caveat (see `signal_row_semantics` for the per-row refinement); all others
    are "STANDARD"."""
    return SIGNAL_SEMANTICS.get(signal_type, "STANDARD")


def signal_row_semantics(signal: "Signal") -> str:
    """Per-signal label. An EVENT on the anchor bar (days_since_event_trading == 0)
    is the same sample as the EVENT_BASELINE signals; an EVENT that joins an
    already-active episode is a distinct observation ("STANDARD")."""
    if signal.signal_type is SignalType.EVENT:
        return _EVENT_ANCHOR_CAVEAT if signal.snapshot.days_since_event_trading == 0 else "STANDARD"
    return signal_semantics(signal.signal_type)


def identical_sample_groups(signal_rows) -> list[tuple[str, ...]]:
    """Groups (size >= 2, sorted names, sorted list) of signal types whose
    (ticker, episode_id, bar_index) sets are identical and non-empty in
    `signal_rows` - the selected samples of ONE sample mode (in FIRST mode this
    is EVENT / ACCUMULATION / EVENT_TO_ACCUMULATION whenever every episode has a
    single event). Reports use it to flag rows that are not independent evidence.
    Accepts `Signal` objects or dicts with signal_type/ticker/episode_id/bar_index."""
    sets: dict[str, set[tuple]] = {}
    for r in signal_rows:
        if isinstance(r, Signal):
            name, key = r.signal_type.value, (r.ticker, r.episode_id, r.bar_index)
        else:
            t = r["signal_type"]
            name = t.value if isinstance(t, SignalType) else str(t)
            key = (r["ticker"], r["episode_id"], r["bar_index"])
        sets.setdefault(name, set()).add(key)
    by_set: dict[frozenset, list[str]] = {}
    for name, keys in sets.items():
        by_set.setdefault(frozenset(keys), []).append(name)
    return sorted(tuple(sorted(g)) for g in by_set.values() if len(g) > 1)


@dataclass(frozen=True)
class Signal:
    """A signal at one bar plus its causal snapshot. The overlap fields are
    None until `backtest.engine.annotate_overlap` / `annotate_sample_overlap` ran."""
    signal_type: SignalType
    snapshot: SignalSnapshot
    # All-signals basis (annotate_overlap, before dedup): neighbours may be non-sampled signals.
    days_since_previous_same_signal: int | None = None
    days_since_previous_signal: int | None = None
    is_overlapping: bool | None = None
    # Sample basis (annotate_sample_overlap, over the selected rows only).
    days_since_previous_same_sample: int | None = None
    days_since_previous_sample: int | None = None
    is_overlapping_sample: bool | None = None
    # Number of DISTINCT signal types firing on this ticker/bar (counted over all types
    # before any filtering/dedup, by `annotate_overlap`).
    signal_types_on_bar: int | None = None

    @property
    def category(self) -> SignalCategory:
        return self.signal_type.category

    @property
    def ticker(self) -> str:
        return self.snapshot.ticker

    @property
    def bar_index(self) -> int:
        return self.snapshot.bar_index

    @property
    def signal_date(self):
        return self.snapshot.signal_date

    @property
    def episode_id(self) -> str:
        return self.snapshot.episode_id


def _feature_flag(t: SignalType, s: SignalSnapshot) -> bool:
    if t is SignalType.MA120_CROSS:
        return s.cross_ma120
    if t is SignalType.MA240_CROSS:
        return s.cross_ma240
    if t is SignalType.PREVIOUS_HIGH_BREAK:
        return s.previous_high_break
    if t is SignalType.TREND_BREAK:
        return s.trend_break
    if t is SignalType.STRONG_EVENT:
        return s.strong_event_this_bar
    if t is SignalType.MULTI_EVENT_CLUSTER:
        # fires on EVERY bar where an event joins an already-active episode
        # (count >= 2), i.e. repeatedly within one episode; FIRST mode keeps one.
        return s.event_added_this_bar and s.event_count_so_far >= 2
    raise AssertionError(t)


def signal_types_at(s: SignalSnapshot) -> list[SignalType]:
    """All signal types firing on this snapshot's bar (declaration order).
    A bar on which the episode ends (state INVALIDATED) yields nothing: it is not
    a buy candidate in any category."""
    if s.state == "INVALIDATED":
        return []
    out: list[SignalType] = []
    for t in _STATE_TYPES:
        if t is SignalType.EVENT:
            if s.event_added_this_bar:  # the engine never shows EVENT as a bar state
                out.append(t)
        elif s.state == t.value:
            out.append(t)
    pair = (s.previous_state, s.state)
    out += [t for t, p in _TRANSITION_PAIRS.items() if p == pair]
    out += [t for t in _SNAPSHOT_FEATURES if _feature_flag(t, s)]
    return out


def extract_signals(scan: TickerScan) -> list[Signal]:
    """Signals of a scan in bar order (a bar may yield several). INVALIDATED
    bars yield none. Requires a scan built with collect_snapshots=True."""
    if scan.snapshots is None:
        raise ValueError("extract_signals needs a scan built with collect_snapshots=True")
    out: list[Signal] = []
    confirmed_episodes: set[str] = set()
    for s in scan.snapshots:
        types = signal_types_at(s)
        # ACCUMULATION_CONFIRMED: once per episode, on the first (non-INVALIDATED) bar where the
        # flag is true. It never re-fires when the flag stays true or flips back and forth, and
        # depends only on this and earlier bars of the same episode (prefix invariant).
        if s.accumulation_confirmed and s.state != "INVALIDATED" and s.episode_id not in confirmed_episodes:
            confirmed_episodes.add(s.episode_id)
            types.append(SignalType.ACCUMULATION_CONFIRMED)
        out += [Signal(t, s) for t in types]
    return out
