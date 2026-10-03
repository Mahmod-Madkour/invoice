from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.calculations import grand_total, line_amounts, line_total, round_money, running_totals

D = Decimal


@pytest.mark.parametrize(
    ("qty", "price", "disc", "expected"),
    [
        ("2", "100.00", "0", "200.00"),  # 0%
        ("2", "100.00", "10", "180.00"),  # 10%
        ("2", "100.00", "12.5", "175.00"),  # 12.5%
        ("2", "100.00", "100", "0.00"),  # 100%
        ("2.5", "45.00", "10", "101.25"),  # decimal quantity
        ("0.125", "480.00", "0", "60.00"),
        ("3", "54.99", "33.33", "109.99"),  # 164.97 - 54.985... = 109.985... → 109.99
        ("1", "0", "0", "0.00"),  # free item
        ("7", "0.00", "50", "0.00"),
        ("999999.999", "0.01", "0", "10000.00"),  # widest quantity
    ],
)
def test_line_total(qty, price, disc, expected):
    assert line_total(D(qty), D(price), D(disc)) == D(expected)


@pytest.mark.parametrize(
    ("qty", "price", "disc", "expected"),
    [
        ("0.001", "5.00", "0", "0.01"),  # 0.005 → 0.01 (half-even would give 0.00)
        ("1.005", "1.00", "0", "1.01"),  # 1.005 → 1.01 (half-even would give 1.00)
        ("0.125", "1.00", "0", "0.13"),  # 0.125 → 0.13 (half-even would give 0.12)
        ("1", "0.25", "50", "0.13"),  # 0.25 - 0.125 = 0.125 → 0.13
        ("0.003", "1.00", "0", "0.00"),  # 0.003 → 0.00
        ("0.004", "1.00", "0", "0.00"),  # just below the half
        ("0.006", "1.00", "0", "0.01"),  # just above the half
        ("1", "0.01", "50", "0.01"),  # 0.005 → 0.01
        ("1", "0.01", "50.01", "0.00"),  # 0.004999 → 0.00
    ],
)
def test_rounding_at_half_cent_boundaries_is_half_up(qty, price, disc, expected):
    assert line_total(D(qty), D(price), D(disc)) == D(expected)


def test_line_amounts_breakdown_is_exact_and_only_total_is_rounded():
    amounts = line_amounts(D("3"), D("54.99"), D("33.33"))
    assert amounts.gross == D("164.97")
    assert amounts.discount_amount == D("54.984501")
    assert amounts.total == D("109.99")


@pytest.mark.parametrize(
    ("qty", "price", "disc", "expected"),
    [
        ("99.999", "10000000.00", "0", "999990000.00"),
        ("1000000", "999.99", "0", "999990000.00"),
        ("100", "9999999.99", "0", "999999999.00"),
        ("100", "10000000", "0.01", "999900000.00"),
        # gross = 9,999,999,980,000.00001 (exact, 22 significant digits); × 0.0001 → 999,999,998.0000000001
        ("999999.999", "9999999.99", "99.99", "999999998.0000000001"),
    ],
)
def test_large_values_near_the_limits_are_exact(qty, price, disc, expected):
    assert line_total(D(qty), D(price), D(disc)) == round_money(D(expected))


def test_grand_total_is_the_sum_of_rounded_line_totals():
    # Each line is 0.005 before rounding → 0.01 after. Rounding the raw sum (0.015) would give 0.02.
    totals = [line_total(D("0.001"), D("5.00")) for _ in range(3)]
    assert totals == [D("0.01")] * 3
    assert grand_total(totals) == D("0.03")


def test_grand_total_of_nothing_is_zero_with_two_decimals():
    assert grand_total([]) == D("0.00")
    assert str(grand_total([])) == "0.00"


def test_running_totals_are_cumulative():
    assert running_totals([D("1.10"), D("2.20"), D("0.00"), D("3.30")]) == [D("1.10"), D("3.30"), D("3.30"), D("6.60")]
    assert running_totals([]) == []


def test_round_money_is_half_up():
    assert round_money(D("2.345")) == D("2.35")
    assert round_money(D("2.344999")) == D("2.34")
    assert round_money(D("10")) == D("10.00")


def _reference_total(qty: Decimal, price: Decimal, disc: Decimal) -> Decimal:
    """Independent reference: exact rational arithmetic + explicit half-up rounding to cents."""
    exact = Fraction(qty) * Fraction(price) * (1 - Fraction(disc) / 100)
    cents = (exact * 100 + Fraction(1, 2)).__floor__()
    return Decimal(cents) / 100


quantities = st.decimals(min_value=Decimal("0.001"), max_value=1_000_000, places=3)
prices = st.decimals(min_value=0, max_value=10_000_000, places=2)
discounts = st.decimals(min_value=0, max_value=100, places=2)


@given(quantities, prices, discounts)
def test_line_total_matches_exact_rational_reference(qty, price, disc):
    assert line_total(qty, price, disc) == _reference_total(qty, price, disc)


@given(st.lists(st.tuples(quantities, prices, discounts), min_size=1, max_size=50))
def test_running_and_grand_totals_agree(lines):
    totals = [line_total(*line) for line in lines]
    running = running_totals(totals)
    assert running[-1] == grand_total(totals)
    assert all(b - a == t for a, b, t in zip(running, running[1:], totals[1:]))
