import warnings
import numpy as np
from .base import BaseForecaster


class ETSModel(BaseForecaster):
    """Holt-Winters exponential smoothing with additive trend and damping.

    Uses a rolling window of at most MAX_HISTORY points.
    """

    MAX_HISTORY = 200
    MIN_POINTS = 10

    def __init__(self):
        self._model = None

    def fit(self, y: np.ndarray) -> None:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        window = y[-self.MAX_HISTORY:]
        if len(window) < self.MIN_POINTS:
            self._model = None
            self._last = float(y[-1])
            return

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                m = ExponentialSmoothing(
                    window,
                    trend='add',
                    damped_trend=True,
                    initialization_method='estimated',
                )
                self._model = m.fit(optimized=True)
            except Exception:
                self._model = None
                self._last = float(y[-1])

    def predict_one(self, y: np.ndarray) -> float:
        if self._model is None:
            return float(y[-1])
        try:
            return float(self._model.forecast(1)[0])
        except Exception:
            return float(y[-1])

    def name(self) -> str:
        return "ets"
