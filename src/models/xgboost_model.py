import numpy as np
from .base import BaseForecaster


class XGBoostModel(BaseForecaster):
    """XGBoost with lag + rolling-stat features.

    Requires at least MIN_TRAIN points to fit.
    """

    N_LAGS = 30
    MIN_TRAIN = 50

    def __init__(self):
        self._model = None
        self._last_y = None

    def _build_features(self, y: np.ndarray):
        """Return (X, Y) from time series y."""
        n = len(y)
        if n <= self.N_LAGS:
            return None, None
        rows, targets = [], []
        for i in range(self.N_LAGS, n):
            window = y[i - self.N_LAGS: i]
            feats = list(window)                          # raw lags
            feats += [window.mean(), window.std(ddof=0),  # rolling stats
                      window[-7:].mean() if len(window) >= 7 else window.mean(),
                      window[-3:].mean() if len(window) >= 3 else window.mean(),
                      float(i) / n]                        # position in series
            rows.append(feats)
            targets.append(float(y[i]))
        return np.array(rows), np.array(targets)

    def fit(self, y: np.ndarray) -> None:
        import xgboost as xgb

        self._last_y = y.copy()
        if len(y) < self.MIN_TRAIN + self.N_LAGS:
            self._model = None
            return
        X, Y = self._build_features(y)
        if X is None or len(X) == 0:
            self._model = None
            return
        self._model = xgb.XGBRegressor(
            n_estimators=200,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            n_jobs=1,
            verbosity=0,
        )
        self._model.fit(X, Y)

    def predict_one(self, y: np.ndarray) -> float:
        if self._model is None:
            return float(y[-1])
        if len(y) < self.N_LAGS:
            return float(y[-1])
        n = len(y)
        window = y[-self.N_LAGS:]
        feats = list(window)
        feats += [window.mean(), window.std(ddof=0),
                  window[-7:].mean() if len(window) >= 7 else window.mean(),
                  window[-3:].mean() if len(window) >= 3 else window.mean(),
                  float(n) / n]
        return float(self._model.predict([feats])[0])

    def name(self) -> str:
        return "xgboost"
