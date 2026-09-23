"""RED-first unit tests for the four PURE helpers in
``check_venue_fill_windows.py`` (bisection, arg parsing, header-weight diff,
verdict formatting) -- task 2.3. No credential, no network: every venue call
in that script is excluded from this suite by construction (the helpers
tested here take no `httpx`/signer argument at all).
"""

import pytest
from check_venue_fill_windows import (
    Args,
    ItemVerdict,
    SpanProbe,
    bisect_max_accepted_span,
    clock_skew_ms,
    describe_failure,
    format_item_verdict,
    header_call_cost,
    parse_args,
)

# --- bisect_max_accepted_span ------------------------------------------------


async def _fake_probe(threshold_days: int, refuse_at_or_above: int, calls: list[int]) -> SpanProbe:
    calls.append(threshold_days)
    if threshold_days < refuse_at_or_above:
        return SpanProbe(threshold_days, "accepted", f"ok at {threshold_days}d")
    return SpanProbe(threshold_days, "refused", f"code=10001 at {threshold_days}d")


async def test_bisection_finds_the_boundary_between_1_7_8_30_90() -> None:
    calls: list[int] = []

    async def probe(days: int) -> SpanProbe:
        return await _fake_probe(days, refuse_at_or_above=30, calls=calls)

    result = await bisect_max_accepted_span((1, 7, 8, 30, 90), probe)

    assert result.max_accepted_days == 8
    assert result.first_refused is not None
    assert result.first_refused.days == 30


async def test_bisection_calls_the_probe_at_fewer_points_than_a_linear_scan() -> None:
    """The whole point of bisecting rather than scanning: 5 candidates need
    at most `ceil(log2(5)) + 1` calls, never all 5."""
    calls: list[int] = []

    async def probe(days: int) -> SpanProbe:
        return await _fake_probe(days, refuse_at_or_above=30, calls=calls)

    await bisect_max_accepted_span((1, 7, 8, 30, 90), probe)

    assert len(calls) < 5
    assert calls == [8, 30]


async def test_bisection_reports_no_refusal_when_every_candidate_is_accepted() -> None:
    calls: list[int] = []

    async def probe(days: int) -> SpanProbe:
        return await _fake_probe(days, refuse_at_or_above=9999, calls=calls)

    result = await bisect_max_accepted_span((1, 7, 8, 30, 90), probe)

    assert result.max_accepted_days == 90
    assert result.first_refused is None


async def test_bisection_treats_unknown_like_refused_for_narrowing_never_as_first_refused() -> None:
    async def probe(days: int) -> SpanProbe:
        if days >= 30:
            return SpanProbe(days, "unknown", "timeout")
        return SpanProbe(days, "accepted", "ok")

    result = await bisect_max_accepted_span((1, 7, 8, 30, 90), probe)

    assert result.max_accepted_days == 8
    assert result.first_refused is None


async def test_bisection_refuses_an_empty_candidate_list() -> None:
    async def probe(days: int) -> SpanProbe:
        raise AssertionError("must never be called for an empty candidate list")

    with pytest.raises(ValueError):
        await bisect_max_accepted_span((), probe)


# --- header_call_cost ---------------------------------------------------------


def test_header_call_cost_reads_an_increasing_counter_case_insensitively() -> None:
    before = {"X-Mbx-Used-Weight-1m": "10"}
    after = {"x-mbx-used-weight-1m": "15"}

    assert header_call_cost(before, after, "x-mbx-used-weight-1m", "increasing") == 5


def test_header_call_cost_reads_a_decreasing_counter() -> None:
    before = {"X-Bapi-Limit-Status": "100"}
    after = {"X-Bapi-Limit-Status": "95"}

    assert header_call_cost(before, after, "x-bapi-limit-status", "decreasing") == 5


def test_header_call_cost_is_none_on_an_increasing_rollover() -> None:
    """A LOWER second reading on an 'increasing' header means the window
    rolled over between calls -- the pair proves nothing, per design."""
    before = {"x-mbx-used-weight-1m": "50"}
    after = {"x-mbx-used-weight-1m": "3"}

    assert header_call_cost(before, after, "x-mbx-used-weight-1m", "increasing") is None


def test_header_call_cost_is_none_on_a_decreasing_rollover() -> None:
    """A HIGHER second reading on a 'decreasing' header means the remaining
    budget was replenished between calls -- also not a valid pair."""
    before = {"x-bapi-limit-status": "5"}
    after = {"x-bapi-limit-status": "100"}

    assert header_call_cost(before, after, "x-bapi-limit-status", "decreasing") is None


def test_header_call_cost_is_none_when_the_header_is_missing_from_either_response() -> None:
    header = "x-mbx-used-weight-1m"

    assert header_call_cost({}, {header: "5"}, header, "increasing") is None
    assert header_call_cost({header: "5"}, {}, header, "increasing") is None


def test_header_call_cost_is_none_for_a_non_integer_value() -> None:
    before = {"x-mbx-used-weight-1m": "not-a-number"}
    after = {"x-mbx-used-weight-1m": "5"}

    assert header_call_cost(before, after, "x-mbx-used-weight-1m", "increasing") is None


# --- parse_args ----------------------------------------------------------------


def test_parse_args_defaults() -> None:
    args = parse_args([])

    assert args == Args(
        symbol="BTCUSDT",
        lookback_days=7,
        span_candidates_days=(1, 7, 8, 30, 90),
        page_limit=50,
    )


def test_parse_args_uppercases_the_symbol_and_sorts_span_days() -> None:
    args = parse_args(
        [
            "--symbol",
            "ethusdt",
            "--lookback-days",
            "30",
            "--span-days",
            "8",
            "1",
            "3",
            "--page-limit",
            "10",
        ]
    )

    assert args.symbol == "ETHUSDT"
    assert args.lookback_days == 30
    assert args.span_candidates_days == (1, 3, 8)
    assert args.page_limit == 10


def test_parse_args_refuses_a_nonpositive_lookback() -> None:
    with pytest.raises(ValueError):
        parse_args(["--lookback-days", "0"])


def test_parse_args_refuses_a_nonpositive_page_limit() -> None:
    with pytest.raises(ValueError):
        parse_args(["--page-limit", "-1"])


def test_parse_args_refuses_a_nonpositive_span_day() -> None:
    with pytest.raises(ValueError):
        parse_args(["--span-days", "1", "0", "7"])


# --- format_item_verdict --------------------------------------------------------


def test_format_item_verdict_answered() -> None:
    rendered = format_item_verdict("f", ItemVerdict("answered", "retCode=0"))

    assert "ANSWERED" in rendered
    assert "retCode=0" in rendered
    assert "REFUSED" not in rendered
    assert "UNKNOWN" not in rendered


def test_format_item_verdict_refused_includes_the_venues_own_code() -> None:
    rendered = format_item_verdict("f", ItemVerdict("refused", "retMsg='denied'", code="10003"))

    assert "REFUSED" in rendered
    assert "10003" in rendered
    assert "denied" in rendered


def test_format_item_verdict_unknown_never_reads_as_answered_or_refused() -> None:
    rendered = format_item_verdict("d", ItemVerdict("unknown", "no liquidation in history"))

    assert "UNKNOWN" in rendered
    assert "ANSWERED" not in rendered
    assert "REFUSED" not in rendered


def test_format_item_verdict_falls_back_to_the_raw_key_for_an_unlabelled_item() -> None:
    rendered = format_item_verdict("z", ItemVerdict("answered", "n/a"))

    assert rendered.startswith("z:")


# --- describe_failure ----------------------------------------------------------


def test_describe_failure_strips_a_signed_query_string_from_the_exception_text() -> None:
    # The owner pastes this script's output into a chat; a transport error
    # that echoes the request URL would carry Binance's query-string signature.
    exc = RuntimeError(
        "boom for url 'https://fapi.binance.com/fapi/v1/userTrades"
        "?symbol=STXUSDT&timestamp=1&signature=deadbeefcafe'"
    )

    described = describe_failure(exc)

    assert described.startswith("RuntimeError: boom for url")
    assert "deadbeefcafe" not in described
    assert "signature=" not in described


# --- clock_skew_ms -------------------------------------------------------------


def test_clock_skew_compares_the_server_to_the_midpoint_of_the_request() -> None:
    # The first live run compared the server against ONE timestamp taken before
    # both venues ran, so Binance "measured" Bybit's whole run (1989 ms).
    skew, round_trip = clock_skew_ms(server_ms=1_000, sent_ms=900, received_ms=1_100)

    assert skew == 0
    assert round_trip == 200


def test_clock_skew_reports_a_venue_ahead_as_positive() -> None:
    skew, round_trip = clock_skew_ms(server_ms=1_250, sent_ms=1_000, received_ms=1_100)

    assert skew == 200
    assert round_trip == 100


# --- header_call_cost: a counter that did not move ------------------------------


def test_header_call_cost_is_none_when_the_counter_did_not_move() -> None:
    """Every call costs at least one unit, so an unchanged counter means the
    window reset between the readings -- unmeasured, never "free". The first
    live run reported Bybit at "0 units per call" exactly this way."""
    before = {"x-bapi-limit-status": "49"}
    after = {"x-bapi-limit-status": "49"}

    assert header_call_cost(before, after, "x-bapi-limit-status", "decreasing") is None
    assert header_call_cost(before, after, "x-bapi-limit-status", "increasing") is None
