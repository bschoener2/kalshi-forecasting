"""Walk-forward cross-validation and metric computation for forecasters."""
import logging
import math
import warnings
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy import stats

from .base import BaseForecaster

logger = logging.getLogger(__name__)

# Kalshi round-trip transaction cost estimate (buy + sell, in cents per contract)
TC_CENTS = 2.0


@dataclass
class EvalResult:
    model_name: str
    ticker: str
    n_predictions: int
    mae: float
    rmse: float
    dir_accuracy: float           # fraction of correct directional calls
    ev_cents: float               # mean P&L per trade in cents
    ev_pvalue: float              # one-sided p-value: EV > 0
    ev_fdr_adjusted: float = 1.0  # filled in by apply_bh_correction()
    sharpe: float = 0.0           # annualised Sharpe of daily P&L
    is_significant: bool = False   # survives FDR correction


def walk_forward(
    y: np.ndarray,
    model: BaseForecaster,
    min_train: int = 60,
    step: int = 7,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (predictions, actuals) from walk-forward CV.

    step > 1 reduces computation: model is refit every `step` days.
    No future data leaks into training.
    """
    n = len(y)
    if n < min_train + 2:
        return np.array([]), np.array([])

    preds, actuals = [], []

    for i in range(min_train, n - 1, step):
        train = y[:i]
        # Predict up to `step` steps without refitting
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            model.fit(train)

        # Emit predictions for the next `step` steps
        for j in range(step):
            t = i + j
            if t >= n - 1:
                break
            pred = model.predict_one(y[:t])
            actual = float(y[t])
            preds.append(pred)
            actuals.append(actual)

    return np.array(preds), np.array(actuals)


def compute_metrics(
    preds: np.ndarray,
    actuals: np.ndarray,
    tc_cents: float = TC_CENTS,
) -> dict:
    """Compute evaluation metrics from walk-forward output."""
    n = len(preds)
    if n < 2:
        return {}

    errors = preds - actuals
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))

    # Directional accuracy
    actual_changes = np.diff(actuals)
    pred_directions = np.sign(preds[:-1] - actuals[:-1])  # predicted direction at t
    actual_directions = np.sign(actual_changes)
    # Only count non-zero actual moves to avoid dividing by noise
    non_flat = actual_directions != 0
    if non_flat.sum() > 0:
        dir_acc = float(np.mean(pred_directions[non_flat] == actual_directions[non_flat]))
    else:
        dir_acc = 0.5

    # EV: trade in predicted direction, realise actual change, minus TC
    directions = np.sign(preds[:-1] - actuals[:-1])
    pnl = directions * actual_changes - tc_cents
    ev_cents = float(np.mean(pnl))

    # Sharpe (annualised, assuming 252 trading days)
    pnl_std = float(np.std(pnl, ddof=1)) if len(pnl) > 1 else 1.0
    sharpe = (ev_cents / (pnl_std + 1e-9)) * math.sqrt(252) if pnl_std > 0 else 0.0

    # One-sided t-test: H0 = EV <= 0
    if len(pnl) >= 5:
        t_stat, p_two = stats.ttest_1samp(pnl, 0.0)
        ev_pvalue = float(p_two / 2) if t_stat > 0 else 1.0
    else:
        ev_pvalue = 1.0

    return {
        'n_predictions': n,
        'mae': mae,
        'rmse': rmse,
        'dir_accuracy': dir_acc,
        'ev_cents': ev_cents,
        'sharpe': sharpe,
        'ev_pvalue': ev_pvalue,
    }


def apply_bh_correction(
    results: list[EvalResult],
    fdr: float = 0.05,
) -> list[EvalResult]:
    """Apply Benjamini–Hochberg FDR correction in-place."""
    m = len(results)
    if m == 0:
        return results

    # Sort by p-value ascending
    sorted_idx = sorted(range(m), key=lambda i: results[i].ev_pvalue)

    # BH thresholds
    for rank, idx in enumerate(sorted_idx, start=1):
        threshold = fdr * rank / m
        # Cap adjusted p-value at 1.0 (standard BH convention)
        results[idx].ev_fdr_adjusted = min(1.0, float(results[idx].ev_pvalue * m / rank))
        results[idx].is_significant = results[idx].ev_pvalue <= threshold

    return results


class WalkForwardEvaluator:
    def __init__(self, min_train: int = 60, step: int = 7):
        self.min_train = min_train
        self.step = step

    def evaluate(
        self,
        ticker: str,
        y: np.ndarray,
        model: BaseForecaster,
    ) -> Optional[EvalResult]:
        """Run walk-forward CV and return an EvalResult (or None if insufficient data)."""
        if len(y) < self.min_train + 2:
            return None

        logger.debug('  %s | %s | %d points', ticker, model.name(), len(y))
        preds, actuals = walk_forward(y, model, self.min_train, self.step)

        if len(preds) < 5:
            return None

        m = compute_metrics(preds, actuals)
        if not m:
            return None

        return EvalResult(
            model_name=model.name(),
            ticker=ticker,
            **m,
        )
