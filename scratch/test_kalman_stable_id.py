import numpy as np
from scipy.optimize import linear_sum_assignment
import threading
import time

class KalmanCentroidTracker:
    def __init__(self, x: float, y: float):
        self.state = np.array([x, y, 0.0, 0.0], dtype=np.float32)
        self.P = np.diag([1e-2, 1e-2, 1.0, 1.0]).astype(np.float32)
        self.Q = np.diag([1e-4, 1e-4, 1e-2, 1e-2]).astype(np.float32)
        self.R = np.diag([1e-3, 1e-3]).astype(np.float32)
        self.H = np.array([[1.0, 0.0, 0.0, 0.0],
                           [0.0, 1.0, 0.0, 0.0]], dtype=np.float32)

    def predict(self, dt: float = 1.0):
        F = np.array([
            [1.0, 0.0, dt, 0.0],
            [0.0, 1.0, 0.0, dt],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0]
        ], dtype=np.float32)
        self.state = F @ self.state
        self.P = F @ self.P @ F.T + self.Q
        return float(self.state[0]), float(self.state[1])

    def update(self, z_x: float, z_y: float):
        z = np.array([z_x, z_y], dtype=np.float32)
        y = z - self.H @ self.state
        S = self.H @ self.P @ self.H.T + self.R
        det = S[0, 0] * S[1, 1] - S[0, 1] * S[1, 0]
        if abs(det) < 1e-9:
            S_inv = np.diag([1.0 / S[0, 0], 1.0 / S[1, 1]]).astype(np.float32)
        else:
            S_inv = (1.0 / det) * np.array([[S[1, 1], -S[0, 1]], [-S[1, 0], S[0, 0]]], dtype=np.float32)
        K = self.P @ self.H.T @ S_inv
        self.state = self.state + K @ y
        I = np.eye(4, dtype=np.float32)
        self.P = (I - K @ self.H) @ self.P

# Test crossing:
t1 = KalmanCentroidTracker(0.2, 0.5)
t2 = KalmanCentroidTracker(0.6, 0.5)

# Frame 2
p1_pred = t1.predict()
p2_pred = t2.predict()
t1.update(0.25, 0.5)
t2.update(0.55, 0.5)

# Frame 3
p1_pred = t1.predict()
p2_pred = t2.predict()
t1.update(0.35, 0.5)
t2.update(0.45, 0.5)

# Frame 4 (intersection)
p1_pred = t1.predict()
p2_pred = t2.predict()
print(f"Frame 4 predictions: t1={p1_pred}, t2={p2_pred}")
# Actual measurements: t1 has moved to 0.45, t2 has moved to 0.35
m1 = (0.45, 0.5)
m2 = (0.35, 0.5)

# Cost matrix
preds = [p1_pred, p2_pred]
meas = [m1, m2]
cost = np.zeros((2, 2))
for i, p in enumerate(preds):
    for j, m in enumerate(meas):
        cost[i, j] = ((p[0] - m[0])**2 + (p[1] - m[1])**2)**0.5

print("Cost matrix:\n", cost)
row_ind, col_ind = linear_sum_assignment(cost)
print(f"Assigned: t0->m{col_ind[0]}, t1->m{col_ind[1]}")
assert col_ind[0] == 0, "Track 1 should match measurement 1 (0.45)"
assert col_ind[1] == 1, "Track 2 should match measurement 2 (0.35)"
print("SUCCESS: Kalman + Hungarian cleanly separated crossing tracks!")
