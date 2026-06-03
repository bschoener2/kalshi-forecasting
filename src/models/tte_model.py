"""Time-To-Expiry (TTE) model for binary prediction markets.

Binary Kalshi markets must resolve to 0 or 100 cents at expiry.
The key insight: as expiry approaches, the price dynamics change —
there is less time for new information to arrive, so large reversals
become less probable. Including `days_remaining` as a feature lets
the model learn this "resolution gravity" directly from the data.

Features:
  - Recent lags (price memory)
  - days_remaining and log(days_remaining + 1)
  - price × log(days_remaining + 1)   — interaction: how much does
    the current level matter given time remaining?
  - price × (100 - price)              — variance proxy: markets near
    50¢ are most uncertain regardless of time left
"""
import numpy as np
from datetime import date
from .base import BaseForecaster


class TimeToExpiryModel(BaseForecaster):
    """Ridge regression augmented with days-to-expiry features.

    Requires expiry_date and data_start_date at construction time so it can
    compute days_remaining = f(position in series) during walk-forward CV,
    where only the price array is available.
    """

    N_LAGS = 10
    MIN_TRAIN = 30
    ALPHA = 0.5

    def __init__(self, expiry_date: date, data_start_date: date):
        self.expiry_date = expiry_date
        self.data_start_date = data_start_date
        self._total_days = (expiry_date - data_start_date).days
        self._model = None

    def _days_remaining(self, idx: int) -> float:
        """Approximate days remaining when the series index is `idx`."""
        return max(1.0, self._total_days - idx)

    def _featurise(self, y: np.ndarray, idx: int) -> list:
        window = y[max(0, idx - self.N_LAGS): idx + 1]
        p = float(y[idx])
        dr = self._days_remaining(idx)
        log_dr = np.log1p(dr)
        feats = list(window[-self.N_LAGS:].tolist() if len(window) >= self.N_LAGS
                     else ([0.0] * (self.N_LAGS - len(window)) + list(window)))
        feats += [
            dr,
            log_dr,
            p * log_dr,
            p * (100.0 - p),       # variance proxy
            p * (100.0 - p) / (dr + 1),  # variance / time: should shrink near expiry
        ]
        return feats

    def fit(self, y: np.ndarray) -> None:
        from sklearn.linear_model import Ridge

        if len(y) < self.MIN_TRAIN + self.N_LAGS:
            self._model = None
            return

        rows, targets = [], []
        for i in range(self.N_LAGS, len(y) - 1):
            rows.append(self._featurise(y, i))
            targets.append(float(y[i + 1]))

        if not rows:
            self._model = None
            return

        self._model = Ridge(alpha=self.ALPHA)
        self._model.fit(rows, targets)

    def predict_one(self, y: np.ndarray) -> float:
        if self._model is None:
            return float(y[-1])
        idx = len(y) - 1
        feats = self._featurise(y, idx)
        pred = float(self._model.predict([feats])[0])
        return np.clip(pred, 0.0, 100.0)

    def name(self) -> str:
        return "tte"
