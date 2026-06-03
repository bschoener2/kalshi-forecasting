import warnings
import numpy as np
from .base import BaseForecaster


class ARIMAModel(BaseForecaster):
    """ARIMA with automatic order selection via pmdarima.

    Uses a rolling window of up to MAX_HISTORY points to keep fitting fast.
    Falls back to ARIMA(1,1,1) if auto-selection fails.
    """

    MAX_HISTORY = 200
    FALLBACK_ORDER = (1, 1, 1)

    def __init__(self):
        self._model = None

    def fit(self, y: np.ndarray) -> None:
        import pmdarima as pm

        window = y[-self.MAX_HISTORY:]
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                self._model = pm.auto_arima(
                    window,
                    start_p=0, max_p=3,
                    start_q=0, max_q=3,
                    d=None, max_d=2,
                    seasonal=False,
                    information_criterion='aic',
                    error_action='ignore',
                    suppress_warnings=True,
                    stepwise=True,
                )
            except Exception:
                from statsmodels.tsa.arima.model import ARIMA as _ARIMA
                self._model = _ARIMA(window, order=self.FALLBACK_ORDER).fit()
                self._model._is_statsmodels = True

    def predict_one(self, y: np.ndarray) -> float:
        if self._model is None:
            return float(y[-1])
        try:
            if getattr(self._model, '_is_statsmodels', False):
                return float(self._model.forecast(1)[0])
            fc = self._model.predict(n_periods=1)
            return float(fc[0])
        except Exception:
            return float(y[-1])

    def name(self) -> str:
        return "arima"
