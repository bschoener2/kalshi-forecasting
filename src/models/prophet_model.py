"""Prophet-based forecaster for binary prediction market prices.

Prophet detects structural breaks (sudden news-driven price jumps)
automatically via its changepoint mechanism. This is particularly
useful for political markets where a single news event can shift
the probability 10-20 cents overnight.

Because Prophet requires real dates (not just a price array), this
model takes a `data_start_date` at construction time and synthesises
a date index from it.
"""
import warnings
import logging
import numpy as np
from datetime import date, timedelta
from .base import BaseForecaster

logger = logging.getLogger(__name__)


class ProphetModel(BaseForecaster):
    """One-step-ahead forecaster using Facebook Prophet.

    Uses daily synthetic dates starting from `data_start_date`.
    Changepoint prior scale is kept small (0.05) to avoid overfitting
    on short series, while still allowing the model to detect the
    structural breaks that characterise political markets.
    """

    MIN_TRAIN = 30

    def __init__(self, data_start_date: date):
        self.data_start_date = data_start_date
        self._model = None
        self._n_train = 0

    def _make_df(self, y: np.ndarray):
        import pandas as pd
        dates = [self.data_start_date + timedelta(days=i) for i in range(len(y))]
        return pd.DataFrame({'ds': pd.to_datetime(dates), 'y': y.astype(float)})

    def fit(self, y: np.ndarray) -> None:
        if len(y) < self.MIN_TRAIN:
            self._model = None
            return
        self._n_train = len(y)
        df = self._make_df(y)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            logging.getLogger('prophet').setLevel(logging.ERROR)
            logging.getLogger('cmdstanpy').setLevel(logging.ERROR)
            try:
                from prophet import Prophet
                m = Prophet(
                    changepoint_prior_scale=0.05,
                    seasonality_mode='additive',
                    daily_seasonality=False,
                    weekly_seasonality=False,
                    yearly_seasonality=False,
                )
                m.fit(df)
                self._model = m
            except Exception as exc:
                logger.debug('Prophet fit failed: %s', exc)
                self._model = None

    def predict_one(self, y: np.ndarray) -> float:
        if self._model is None:
            return float(y[-1])
        import pandas as pd
        next_date = self.data_start_date + timedelta(days=len(y))
        future = pd.DataFrame({'ds': [pd.Timestamp(next_date)]})
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                fc = self._model.predict(future)
            pred = float(fc['yhat'].iloc[0])
            return float(np.clip(pred, 0.0, 100.0))
        except Exception:
            return float(y[-1])

    def name(self) -> str:
        return "prophet"
