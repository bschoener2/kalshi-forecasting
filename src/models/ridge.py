import numpy as np
from .base import BaseForecaster


class RidgeModel(BaseForecaster):
    """Ridge regression with lag features.

    Same feature set as XGBoost but with L2 regularisation, which typically
    outperforms tree methods when n < 200 by avoiding overfitting on the
    lag features.
    """

    N_LAGS = 20
    MIN_TRAIN = 30
    ALPHA = 1.0

    def __init__(self):
        self._model = None

    def _build_features(self, y: np.ndarray):
        n = len(y)
        if n <= self.N_LAGS:
            return None, None
        rows, targets = [], []
        for i in range(self.N_LAGS, n):
            window = y[i - self.N_LAGS: i]
            feats = list(window)
            feats += [
                window.mean(),
                window.std(ddof=0),
                window[-5:].mean() if len(window) >= 5 else window.mean(),
                window[-3:].mean() if len(window) >= 3 else window.mean(),
                window[-1] - window[0],   # total change over window
            ]
            rows.append(feats)
            targets.append(float(y[i]))
        return np.array(rows), np.array(targets)

    def fit(self, y: np.ndarray) -> None:
        from sklearn.linear_model import Ridge

        if len(y) < self.MIN_TRAIN + self.N_LAGS:
            self._model = None
            return
        X, Y = self._build_features(y)
        if X is None:
            self._model = None
            return
        self._model = Ridge(alpha=self.ALPHA)
        self._model.fit(X, Y)

    def predict_one(self, y: np.ndarray) -> float:
        if self._model is None or len(y) < self.N_LAGS:
            return float(y[-1])
        window = y[-self.N_LAGS:]
        feats = list(window)
        feats += [
            window.mean(),
            window.std(ddof=0),
            window[-5:].mean() if len(window) >= 5 else window.mean(),
            window[-3:].mean() if len(window) >= 3 else window.mean(),
            window[-1] - window[0],
        ]
        return float(self._model.predict([feats])[0])

    def name(self) -> str:
        return "ridge"
