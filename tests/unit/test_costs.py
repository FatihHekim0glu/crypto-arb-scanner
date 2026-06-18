"""Unit tests for the ``cryptoarb.costs`` group.

Pins the honest cost machinery: fee schedules load real (non-zero) rates per
venue, transfer cost converts a flat withdrawal + latency penalty into bps, and
the gross -> net waterfall composes them so that ``net_bps <= gross_bps`` ALWAYS
(costs are non-negative). The fixed-input waterfall test is the arithmetic
anchor for the headline collapse.
"""

from __future__ import annotations

import itertools
import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cryptoarb._exceptions import ValidationError
from cryptoarb.costs import fees as fees_mod
from cryptoarb.costs import transfer as transfer_mod
from cryptoarb.costs.fees import (
    FeeSchedule,
    load_fee_schedules,
    round_trip_taker_bps,
)
from cryptoarb.costs.transfer import (
    TransferSchedule,
    load_transfer_schedules,
    transfer_cost_bps,
)
from cryptoarb.costs.waterfall import (
    CompositeCost,
    Waterfall,
    WaterfallStage,
    build_waterfall,
)

pytestmark = pytest.mark.unit

_PROFILES = ("default", "low", "high")


# --------------------------------------------------------------------------- #
# FeeSchedule + profile loading                                               #
# --------------------------------------------------------------------------- #
def test_fee_schedule_bps_conversion() -> None:
    """``maker``/``taker`` fractions convert to bps via the ``* 1e4`` factor."""
    fee = FeeSchedule(venue="binance", maker=0.0010, taker=0.0026)
    assert fee.maker_bps == pytest.approx(10.0)
    assert fee.taker_bps == pytest.approx(26.0)


def test_fee_schedule_to_dict_round_trips_rates() -> None:
    """``to_dict`` is JSON-friendly and exposes both fraction and bps views."""
    fee = FeeSchedule(venue="kraken", maker=0.0016, taker=0.0026)
    d = fee.to_dict()
    assert d == {
        "venue": "kraken",
        "maker": 0.0016,
        "taker": 0.0026,
        "maker_bps": pytest.approx(16.0),
        "taker_bps": pytest.approx(26.0),
    }


@pytest.mark.parametrize("profile", _PROFILES)
def test_load_fee_schedules_has_three_venues_with_positive_taker(profile: str) -> None:
    """Every profile defines the three reference venues; takers are never zeroed."""
    fees = load_fee_schedules(profile)
    assert set(fees) >= {"binance", "coinbase", "kraken"}
    for venue, fee in fees.items():
        assert fee.venue == venue
        assert fee.taker_bps > 0.0, f"{profile}:{venue} taker must be positive"
        assert fee.maker >= 0.0


def test_load_fee_schedules_default_values() -> None:
    """Pin the documented default taker rates so a profile edit is caught."""
    fees = load_fee_schedules("default")
    assert fees["binance"].taker_bps == pytest.approx(10.0)
    assert fees["coinbase"].taker_bps == pytest.approx(60.0)
    assert fees["kraken"].taker_bps == pytest.approx(26.0)


def test_load_fee_schedules_unknown_profile_raises() -> None:
    """An unknown profile name is rejected, not silently defaulted."""
    with pytest.raises(ValidationError, match="unknown cost profile"):
        load_fee_schedules("nonexistent")


def test_build_fee_schedule_rejects_non_mapping() -> None:
    """A non-mapping entry for a venue is rejected with a clear message."""
    with pytest.raises(ValidationError, match="must be a mapping"):
        fees_mod._build_fee_schedule("binance", [0.001, 0.002])


def test_build_fee_schedule_rejects_missing_key() -> None:
    """A schedule missing the ``taker`` rate names the missing key."""
    with pytest.raises(ValidationError, match="missing key 'taker'"):
        fees_mod._build_fee_schedule("binance", {"maker": 0.001})


def test_build_fee_schedule_rejects_non_numeric() -> None:
    """A non-numeric rate is reported as such rather than crashing."""
    with pytest.raises(ValidationError, match="non-numeric rate"):
        fees_mod._build_fee_schedule("binance", {"maker": "free", "taker": 0.001})


def test_build_fee_schedule_rejects_negative_rate() -> None:
    """A negative fee (a fake rebate that could manufacture an edge) is rejected."""
    with pytest.raises(ValidationError, match="negative rate"):
        fees_mod._build_fee_schedule("binance", {"maker": -0.001, "taker": 0.001})


def test_load_fee_schedules_rejects_profile_without_fees_section(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A profile that parses but lacks a usable ``fees`` section is a domain error."""
    monkeypatch.setattr(fees_mod, "load_profile", lambda _profile: {"transfers": {}})
    with pytest.raises(ValidationError, match="no usable 'fees' section"):
        load_fee_schedules("default")


def test_round_trip_taker_applies_each_leg_independently() -> None:
    """Round-trip taker is buy-leg taker + sell-leg taker (per-leg, not doubled)."""
    buy = FeeSchedule(venue="binance", maker=0.0, taker=0.0010)  # 10 bps
    sell = FeeSchedule(venue="kraken", maker=0.0, taker=0.0026)  # 26 bps
    assert round_trip_taker_bps(buy=buy, sell=sell) == pytest.approx(36.0)
    # Asymmetry is preserved: swapping legs with different rates is not the same
    # as doubling one leg.
    same = FeeSchedule(venue="x", maker=0.0, taker=0.0026)
    assert round_trip_taker_bps(buy=same, sell=same) == pytest.approx(52.0)


# --------------------------------------------------------------------------- #
# TransferSchedule                                                            #
# --------------------------------------------------------------------------- #
def test_transfer_cost_bps_fixed_input() -> None:
    """Flat fee -> bps plus the notional-invariant latency penalty."""
    sched = TransferSchedule(
        asset="BTC",
        withdrawal_flat=0.0002,
        network_minutes=30.0,
        latency_bps_per_min=0.05,
    )
    # withdrawal: 1e4 * 0.0002 * 50000 / 10000 = 10 bps ; latency: 30 * 0.05 = 1.5
    cost = transfer_cost_bps(sched, notional_usd=10_000.0, asset_price_usd=50_000.0)
    assert cost == pytest.approx(11.5)


def test_transfer_cost_flat_fee_dilutes_with_notional() -> None:
    """Doubling the notional halves the flat fee's bps share; latency unchanged."""
    sched = TransferSchedule(
        asset="BTC",
        withdrawal_flat=0.0002,
        network_minutes=30.0,
        latency_bps_per_min=0.05,
    )
    small = transfer_cost_bps(sched, notional_usd=10_000.0, asset_price_usd=50_000.0)
    big = transfer_cost_bps(sched, notional_usd=20_000.0, asset_price_usd=50_000.0)
    # latency component (1.5 bps) is invariant; withdrawal (10 bps) halves to 5.
    assert small == pytest.approx(11.5)
    assert big == pytest.approx(6.5)
    assert big < small


@pytest.mark.parametrize(
    ("notional", "price"),
    [(0.0, 50_000.0), (-1.0, 50_000.0), (10_000.0, 0.0), (10_000.0, -5.0)],
)
def test_transfer_cost_rejects_non_positive(notional: float, price: float) -> None:
    """Non-positive notional or asset price is a domain error."""
    sched = TransferSchedule("BTC", 0.0002, 30.0, 0.05)
    with pytest.raises(ValidationError):
        transfer_cost_bps(sched, notional_usd=notional, asset_price_usd=price)


@pytest.mark.parametrize("profile", _PROFILES)
def test_load_transfer_schedules_non_negative(profile: str) -> None:
    """Transfer schedules expose BTC and never carry negative parameters."""
    transfers = load_transfer_schedules(profile)
    assert "BTC" in transfers
    for asset, sched in transfers.items():
        assert sched.asset == asset
        assert sched.withdrawal_flat >= 0.0
        assert sched.network_minutes >= 0.0
        assert sched.latency_bps_per_min >= 0.0


def test_load_transfer_schedules_unknown_profile_raises() -> None:
    with pytest.raises(ValidationError, match="unknown cost profile"):
        load_transfer_schedules("bogus")


def test_build_transfer_schedule_rejects_non_mapping() -> None:
    with pytest.raises(ValidationError, match="must be a mapping"):
        transfer_mod._build_transfer_schedule("BTC", 0.0002)


def test_build_transfer_schedule_rejects_missing_key() -> None:
    with pytest.raises(ValidationError, match="missing key 'network_minutes'"):
        transfer_mod._build_transfer_schedule(
            "BTC", {"withdrawal_flat": 0.0002, "latency_bps_per_min": 0.05}
        )


def test_build_transfer_schedule_rejects_non_numeric() -> None:
    with pytest.raises(ValidationError, match="non-numeric value"):
        transfer_mod._build_transfer_schedule(
            "BTC",
            {"withdrawal_flat": "free", "network_minutes": 30.0, "latency_bps_per_min": 0.05},
        )


def test_build_transfer_schedule_rejects_negative_value() -> None:
    with pytest.raises(ValidationError, match="negative value"):
        transfer_mod._build_transfer_schedule(
            "BTC",
            {"withdrawal_flat": 0.0002, "network_minutes": -30.0, "latency_bps_per_min": 0.05},
        )


def test_load_transfer_schedules_rejects_profile_without_transfers_section(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A profile lacking a usable ``transfers`` section is a domain error."""
    monkeypatch.setattr(transfer_mod, "load_profile", lambda _profile: {"fees": {}})
    with pytest.raises(ValidationError, match="no usable 'transfers' section"):
        load_transfer_schedules("default")


def test_transfer_schedule_to_dict() -> None:
    sched = TransferSchedule("ETH", 0.003, 6.0, 0.05)
    d = sched.to_dict()
    assert d["asset"] == "ETH"
    assert d["latency_bps"] == pytest.approx(0.3)


# --------------------------------------------------------------------------- #
# CompositeCost                                                               #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("profile", _PROFILES)
def test_composite_cost_from_profile(profile: str) -> None:
    """A composite bundles both fee and transfer schedules for one profile."""
    cc = CompositeCost.from_profile(profile)
    assert cc.profile == profile
    assert "binance" in cc.fees
    assert "BTC" in cc.transfers
    d = cc.to_dict()
    assert d["profile"] == profile
    assert "fees" in d and "transfers" in d
    assert d["fees"]["binance"]["taker_bps"] > 0.0


def test_composite_cost_unknown_profile_raises() -> None:
    with pytest.raises(ValidationError):
        CompositeCost.from_profile("does-not-exist")


# --------------------------------------------------------------------------- #
# build_waterfall - the gross -> net collapse                                 #
# --------------------------------------------------------------------------- #
def _default_legs() -> tuple[FeeSchedule, FeeSchedule, TransferSchedule]:
    fees = load_fee_schedules("default")
    transfers = load_transfer_schedules("default")
    return fees["binance"], fees["kraken"], transfers["BTC"]


def test_build_waterfall_fixed_input_arithmetic() -> None:
    """Golden gross -> net decomposition on the default profile.

    gross 40 bps -> -taker(10+26=36) -> running 4 -> -transfer(11.5) -> net -7.5.
    The dominant cost leg is ``taker_fees`` (36 > 11.5). This is the honest
    collapse: an apparent 40 bps gross edge is negative net.
    """
    buy, sell, transfer = _default_legs()
    wf = build_waterfall(
        gross_bps=40.0,
        buy_fee=buy,
        sell_fee=sell,
        transfer=transfer,
        notional_usd=10_000.0,
        asset_price_usd=50_000.0,
    )
    assert wf.gross_bps == pytest.approx(40.0)
    assert wf.net_bps == pytest.approx(-7.5)
    assert wf.dominant_cost_leg == "taker_fees"

    labels = [s.label for s in wf.stages]
    assert labels == ["gross", "taker_fees", "transfer", "net"]
    by_label = {s.label: s for s in wf.stages}
    assert by_label["gross"].running_bps == pytest.approx(40.0)
    assert by_label["taker_fees"].delta_bps == pytest.approx(-36.0)
    assert by_label["taker_fees"].running_bps == pytest.approx(4.0)
    assert by_label["transfer"].delta_bps == pytest.approx(-11.5)
    assert by_label["transfer"].running_bps == pytest.approx(-7.5)
    assert by_label["net"].running_bps == pytest.approx(-7.5)

    # Running level after the final cost stage equals net.
    assert wf.stages[-1].running_bps == pytest.approx(wf.net_bps)


def test_build_waterfall_skips_transfer_when_none() -> None:
    """With ``transfer=None`` (e.g. triangular single-venue), only fees apply."""
    buy, sell, _ = _default_legs()
    wf = build_waterfall(
        gross_bps=40.0,
        buy_fee=buy,
        sell_fee=sell,
        transfer=None,
        notional_usd=10_000.0,
        asset_price_usd=50_000.0,
    )
    assert [s.label for s in wf.stages] == ["gross", "taker_fees", "net"]
    assert wf.net_bps == pytest.approx(4.0)
    assert wf.dominant_cost_leg == "taker_fees"


def test_build_waterfall_transfer_can_dominate() -> None:
    """When fees are tiny, the transfer leg becomes the dominant cost."""
    cheap = FeeSchedule(venue="x", maker=0.0, taker=0.00001)  # 0.1 bps
    big_transfer = TransferSchedule("BTC", 0.0002, 600.0, 0.05)  # 30 bps latency
    wf = build_waterfall(
        gross_bps=50.0,
        buy_fee=cheap,
        sell_fee=cheap,
        transfer=big_transfer,
        notional_usd=10_000.0,
        asset_price_usd=50_000.0,
    )
    assert wf.dominant_cost_leg == "transfer"


@pytest.mark.parametrize(
    ("notional", "price"),
    [(0.0, 50_000.0), (10_000.0, 0.0), (-5.0, 50_000.0), (10_000.0, -1.0)],
)
def test_build_waterfall_rejects_non_positive(notional: float, price: float) -> None:
    buy, sell, transfer = _default_legs()
    with pytest.raises(ValidationError):
        build_waterfall(
            gross_bps=40.0,
            buy_fee=buy,
            sell_fee=sell,
            transfer=transfer,
            notional_usd=notional,
            asset_price_usd=price,
        )


def test_waterfall_to_dict_is_json_friendly() -> None:
    buy, sell, transfer = _default_legs()
    wf = build_waterfall(
        gross_bps=40.0,
        buy_fee=buy,
        sell_fee=sell,
        transfer=transfer,
        notional_usd=10_000.0,
        asset_price_usd=50_000.0,
    )
    d = wf.to_dict()
    assert d["gross_bps"] == pytest.approx(40.0)
    assert d["net_bps"] == pytest.approx(-7.5)
    assert d["dominant_cost_leg"] == "taker_fees"
    assert isinstance(d["stages"], list)
    assert d["stages"][0] == {
        "label": "gross",
        "delta_bps": pytest.approx(40.0),
        "running_bps": pytest.approx(40.0),
    }


def test_waterfall_stage_is_frozen() -> None:
    """Stages are immutable value objects."""
    stage = WaterfallStage(label="gross", delta_bps=1.0, running_bps=1.0)
    with pytest.raises(AttributeError):
        stage.delta_bps = 2.0  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# The core honest-null invariant: net <= gross, ALWAYS                         #
# --------------------------------------------------------------------------- #
@given(
    gross_bps=st.floats(min_value=-200.0, max_value=200.0, allow_nan=False),
    buy_taker=st.floats(min_value=0.0, max_value=0.01, allow_nan=False),
    sell_taker=st.floats(min_value=0.0, max_value=0.01, allow_nan=False),
    withdrawal_flat=st.floats(min_value=0.0, max_value=0.01, allow_nan=False),
    network_minutes=st.floats(min_value=0.0, max_value=120.0, allow_nan=False),
    latency_bps_per_min=st.floats(min_value=0.0, max_value=0.5, allow_nan=False),
    notional_usd=st.floats(min_value=100.0, max_value=5_000_000.0, allow_nan=False),
    asset_price_usd=st.floats(min_value=1.0, max_value=200_000.0, allow_nan=False),
    include_transfer=st.booleans(),
)
@pytest.mark.property
def test_net_never_exceeds_gross(
    gross_bps: float,
    buy_taker: float,
    sell_taker: float,
    withdrawal_flat: float,
    network_minutes: float,
    latency_bps_per_min: float,
    notional_usd: float,
    asset_price_usd: float,
    include_transfer: bool,
) -> None:
    """Costs are non-negative, so the net edge can never beat the gross edge."""
    buy = FeeSchedule(venue="b", maker=0.0, taker=buy_taker)
    sell = FeeSchedule(venue="s", maker=0.0, taker=sell_taker)
    transfer = (
        TransferSchedule("BTC", withdrawal_flat, network_minutes, latency_bps_per_min)
        if include_transfer
        else None
    )
    wf = build_waterfall(
        gross_bps=gross_bps,
        buy_fee=buy,
        sell_fee=sell,
        transfer=transfer,
        notional_usd=notional_usd,
        asset_price_usd=asset_price_usd,
    )
    assert wf.net_bps <= wf.gross_bps + 1e-9
    assert math.isfinite(wf.net_bps)
    # Each cost stage's running level is monotone non-increasing along the chain.
    running = [s.running_bps for s in wf.stages if s.label != "net"]
    for prev, cur in itertools.pairwise(running):
        assert cur <= prev + 1e-9


def test_returned_waterfall_is_frozen() -> None:
    """The result dataclass is immutable (no post-hoc edge inflation)."""
    buy, sell, transfer = _default_legs()
    wf = build_waterfall(
        gross_bps=40.0,
        buy_fee=buy,
        sell_fee=sell,
        transfer=transfer,
        notional_usd=10_000.0,
        asset_price_usd=50_000.0,
    )
    assert isinstance(wf, Waterfall)
    with pytest.raises(AttributeError):
        wf.net_bps = 100.0  # type: ignore[misc]
