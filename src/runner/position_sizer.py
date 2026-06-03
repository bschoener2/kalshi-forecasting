"""Fractional Kelly position sizing with hard budget constraints."""
import logging
import os

logger = logging.getLogger(__name__)

BUDGET_DOLLARS = float(os.environ.get('BUDGET_DOLLARS', '100.0'))
KELLY_MULTIPLIER = 0.25    # fractional Kelly — reduces variance, avoids ruin
MAX_TRADE_FRACTION = 0.20  # never risk more than 20% of budget on a single trade
MIN_CONTRACTS = 1


def kelly_fraction(p_win: float, b: float) -> float:
    """Standard Kelly formula: f* = (p*b - (1-p)) / b."""
    return max(0.0, (p_win * b - (1 - p_win)) / b)


def compute_position(
    current_price_cents: float,
    direction: str,           # 'buy_yes' or 'buy_no'
    confidence: float,        # 0–1
    available_budget_cents: float,
) -> dict:
    """Return position sizing dict with n_contracts and cost_cents.

    Uses fractional Kelly capped at MAX_TRADE_FRACTION of available budget.
    Kalshi contracts pay 100¢ at settlement; cost is the price paid per contract.
    """
    if direction not in ('buy_yes', 'buy_no'):
        return {'n_contracts': 0, 'cost_cents': 0, 'side': '', 'price_cents': 0}

    # Translate direction to Kalshi side + price
    if direction == 'buy_yes':
        side = 'yes'
        price_cents = int(round(current_price_cents))      # pay YES ask ≈ mid
    else:
        side = 'no'
        price_cents = int(round(100 - current_price_cents))  # pay NO ask ≈ 100-mid

    price_cents = max(1, min(99, price_cents))

    # Kelly fraction: p_win estimated from confidence + base rate
    # Base win prob: 50% + confidence-scaled edge
    # At confidence=1.0 → p_win=0.75 (generous upper bound)
    p_win = 0.50 + confidence * 0.25
    b = (100 - price_cents) / price_cents   # net odds per contract

    frac = kelly_fraction(p_win, b) * KELLY_MULTIPLIER
    frac = min(frac, MAX_TRADE_FRACTION)

    max_spend_cents = available_budget_cents * frac
    n_contracts = max(0, int(max_spend_cents / price_cents))

    logger.info(
        'Position size  side=%s  price=%d¢  p_win=%.2f  kelly_f=%.4f  '
        'frac=%.4f  n_contracts=%d  cost=%.0f¢',
        side, price_cents, p_win,
        kelly_fraction(p_win, b), frac,
        n_contracts, n_contracts * price_cents,
    )

    return {
        'n_contracts': n_contracts,
        'cost_cents': n_contracts * price_cents,
        'side': side,
        'price_cents': price_cents,
    }
