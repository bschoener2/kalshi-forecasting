"""Generate next-day price forecast for KXLEAVESTARMER using ARIMA + ETS ensemble."""
import logging
import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

TICKER = 'KXLEAVESTARMER-26JUL01'
HISTORY_WINDOW = 200   # use at most this many recent candles for fitting


@dataclass
class Forecast:
    ticker: str
    current_price: float          # current mid-price in cents
    predicted_price: float        # next-day forecast in cents
    arima_pred: float
    ets_pred: float
    direction: str                # 'buy_yes', 'buy_no', or 'hold'
    confidence: float             # 0–1, scaled edge above 50%
    model: str = 'arima+ets'


def _fit_arima(y: np.ndarray) -> Optional[float]:
    import pmdarima as pm
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        try:
            m = pm.auto_arima(
                y,
                start_p=0, max_p=3,
                start_q=0, max_q=3,
                d=None, max_d=2,
                seasonal=False,
                information_criterion='aic',
                error_action='ignore',
                suppress_warnings=True,
                stepwise=True,
            )
            return float(m.predict(n_periods=1)[0])
        except Exception as e:
            logger.warning('ARIMA fit failed: %s', e)
            return None


def _fit_ets(y: np.ndarray) -> Optional[float]:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        try:
            m = ExponentialSmoothing(
                y,
                trend='add',
                damped_trend=True,
                initialization_method='estimated',
            ).fit(optimized=True)
            return float(m.forecast(1)[0])
        except Exception as e:
            logger.warning('ETS fit failed: %s', e)
            return None


def generate_forecast(y: np.ndarray, min_confidence: float = 0.0) -> Optional[Forecast]:
    """Fit ARIMA + ETS on recent history and return an ensemble Forecast.

    Returns None if there is insufficient data or the ensemble confidence
    is below min_confidence.
    """
    if len(y) < 30:
        logger.warning('Insufficient price history (%d points)', len(y))
        return None

    window = y[-HISTORY_WINDOW:]
    current = float(window[-1])

    arima_pred = _fit_arima(window)
    ets_pred = _fit_ets(window)

    # Ensemble: average of available predictions
    preds = [p for p in [arima_pred, ets_pred] if p is not None]
    if not preds:
        return None
    predicted = float(np.mean(preds))
    predicted = float(np.clip(predicted, 0.0, 100.0))

    change = predicted - current
    abs_change = abs(change)

    # Confidence: scale the predicted move relative to recent volatility
    recent_vol = float(np.std(np.diff(window[-30:]))) if len(window) >= 31 else 1.0
    if recent_vol < 0.01:
        recent_vol = 0.01
    # Normalise: 1 std-dev move → confidence 0.5
    confidence = float(np.clip(abs_change / (2 * recent_vol), 0.0, 1.0))

    if abs_change < 0.5:
        direction = 'hold'
    elif change > 0:
        direction = 'buy_yes'
    else:
        direction = 'buy_no'

    if confidence < min_confidence:
        direction = 'hold'

    logger.info(
        'Forecast  current=%.1f¢  predicted=%.1f¢  (arima=%.1f ets=%.1f)  '
        'direction=%s  confidence=%.2f',
        current, predicted,
        arima_pred if arima_pred else float('nan'),
        ets_pred if ets_pred else float('nan'),
        direction, confidence,
    )

    return Forecast(
        ticker=TICKER,
        current_price=current,
        predicted_price=predicted,
        arima_pred=arima_pred or predicted,
        ets_pred=ets_pred or predicted,
        direction=direction,
        confidence=confidence,
    )
