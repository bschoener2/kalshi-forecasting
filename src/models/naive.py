import numpy as np
from .base import BaseForecaster


class NaiveModel(BaseForecaster):
    """Predict that tomorrow == today (random-walk baseline)."""

    def fit(self, y: np.ndarray) -> None:
        self._last = float(y[-1])

    def predict_one(self, y: np.ndarray) -> float:
        return float(y[-1])

    def name(self) -> str:
        return "naive"
