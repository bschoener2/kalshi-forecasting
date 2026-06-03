from abc import ABC, abstractmethod
import numpy as np


class BaseForecaster(ABC):
    """Predict the next value in a 1-D time series."""

    @abstractmethod
    def fit(self, y: np.ndarray) -> None:
        """Fit on the given history (all values up to the current time)."""

    @abstractmethod
    def predict_one(self, y: np.ndarray) -> float:
        """Return point forecast for the step immediately after y[-1].

        Called after fit(y); y is the same array passed to fit.
        """

    @abstractmethod
    def name(self) -> str:
        """Short identifier used in results tables."""

    def __repr__(self) -> str:
        return self.name()
