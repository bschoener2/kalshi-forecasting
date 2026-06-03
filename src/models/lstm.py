import numpy as np
from .base import BaseForecaster


class LSTMModel(BaseForecaster):
    """Single-layer LSTM with a linear output head (PyTorch).

    Data is normalized per-window to zero-mean, unit-variance before training.
    Requires MIN_TRAIN points.
    """

    SEQ_LEN = 30
    HIDDEN = 32
    EPOCHS = 60
    LR = 0.005
    MIN_TRAIN = 60

    def __init__(self):
        self._net = None
        self._mu = 0.0
        self._sigma = 1.0

    def fit(self, y: np.ndarray) -> None:
        import torch
        import torch.nn as nn

        if len(y) < self.MIN_TRAIN:
            self._net = None
            return

        # Normalize
        self._mu = float(y.mean())
        self._sigma = float(y.std(ddof=0)) or 1.0
        yn = (y - self._mu) / self._sigma

        # Build sequences
        X, Y = [], []
        for i in range(self.SEQ_LEN, len(yn)):
            X.append(yn[i - self.SEQ_LEN: i])
            Y.append(yn[i])
        if not X:
            self._net = None
            return

        Xt = torch.tensor(np.array(X), dtype=torch.float32).unsqueeze(-1)
        Yt = torch.tensor(np.array(Y), dtype=torch.float32)

        class _Net(nn.Module):
            def __init__(self, hidden):
                super().__init__()
                self.lstm = nn.LSTM(1, hidden, batch_first=True)
                self.fc = nn.Linear(hidden, 1)

            def forward(self, x):
                out, _ = self.lstm(x)
                return self.fc(out[:, -1, :]).squeeze(-1)

        net = _Net(self.HIDDEN)
        opt = torch.optim.Adam(net.parameters(), lr=self.LR)
        loss_fn = nn.MSELoss()

        net.train()
        for _ in range(self.EPOCHS):
            opt.zero_grad()
            pred = net(Xt)
            loss = loss_fn(pred, Yt)
            loss.backward()
            opt.step()

        net.eval()
        self._net = net

    def predict_one(self, y: np.ndarray) -> float:
        import torch

        if self._net is None or len(y) < self.SEQ_LEN:
            return float(y[-1])
        yn = (y - self._mu) / self._sigma
        seq = torch.tensor(yn[-self.SEQ_LEN:], dtype=torch.float32).unsqueeze(0).unsqueeze(-1)
        with torch.no_grad():
            pred_n = float(self._net(seq).item())
        return pred_n * self._sigma + self._mu

    def name(self) -> str:
        return "lstm"
