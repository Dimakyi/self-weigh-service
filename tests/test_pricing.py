from app.pricing import Policy, quote

import math


def test_nan_weight_is_rejected():
    assert quote(math.nan, P).rejected


def test_infinite_weight_is_rejected():
    assert quote(math.inf, P).rejected
    assert quote(-math.inf, P).rejected


def test_fractional_allowance_calculation():
    policy = Policy(23.5, 32, 15000)

    assert quote(24.1, policy).excess_kg == 1
    assert quote(24.5, policy).excess_kg == 1
    assert quote(24.6, policy).excess_kg == 2


def test_fractional_allowance_fee():
    policy = Policy(23.5, 32, 15000)

    result = quote(24.6, policy)

    assert result.excess_kg == 2
    assert result.fee_cents == 30000


P = Policy(allowance_kg=23, max_bag_kg=32, excess_rate_cents_per_kg=15000)


def test_within_allowance_is_free():
    q = quote(18.6, P)
    assert q.within_allowance and q.fee_cents == 0


def test_exact_allowance_is_free():
    assert quote(23.0, P).fee_cents == 0


def test_excess_charged_per_started_kg():
    q = quote(23.1, P)
    assert q.excess_kg == 1 and q.fee_cents == 15000


def test_too_heavy_rejected():
    assert quote(40, P).rejected


def test_invalid_weight_rejected():
    assert quote(0, P).rejected


def test_different_policies_give_different_fees():
    cheap = Policy(20, 32, 10000)
    assert quote(22, cheap).fee_cents == 20000
    assert quote(22, P).fee_cents == 0


def test_exact_maximum_bag_weight_is_accepted():
    result = quote(32, P)

    assert not result.rejected
    assert result.excess_kg == 9
    assert result.fee_cents == 135000


def test_weight_above_maximum_bag_weight_is_rejected():
    result = quote(32.01, P)

    assert result.rejected
    assert result.fee_cents == 0
