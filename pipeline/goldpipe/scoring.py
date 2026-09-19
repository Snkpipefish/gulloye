"""Fellescore per 100 m-segment -> relativ indeks P (0–100).

P_raw = (w_D·D + w_R·R + w_sv·sving + w_os·os + w_f·foss) · port · B
P     = 100 · P_raw / max(P_raw)  (per område)
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter1d

WEIGHTS = {"D": 0.20, "R": 0.25, "sving": 0.15, "os": 0.15, "foss": 0.15, "juv": 0.10}
M_STAR, SIGMA = 1.5, 0.6
R_REF = 150.0           # m – svingradius som gir full score
GATE_TAU = 0.3          # τ < 0.3·τ_c -> ingen transport -> port 0
GATE_OMEGA = 0.5        # W/m² – stillestående


def deposition(omega: np.ndarray) -> np.ndarray:
    """D_i = clip((ω_{i-1} − ω_i)/ω_{i-1}, 0, 1), glattet over 3 segmenter."""
    om = uniform_filter1d(np.asarray(omega, float), 3, mode="nearest")
    prev = np.concatenate([[om[0]], om[:-1]])
    d = np.clip((prev - om) / np.maximum(prev, 1e-6), 0, 1)
    return uniform_filter1d(d, 3, mode="nearest")


def retention(M: np.ndarray) -> np.ndarray:
    """R = exp(−(ln M − ln M*)² / 2σ²): sand i bevegelse, gull blir liggende."""
    return np.exp(-((np.log(np.maximum(M, 1e-6)) - np.log(M_STAR)) ** 2) / (2 * SIGMA ** 2))


def bend_score(kappa: np.ndarray) -> np.ndarray:
    return np.clip(kappa * R_REF, 0, 1)


def proximity_score(dist: np.ndarray, scale: float) -> np.ndarray:
    return np.exp(-np.maximum(dist, 0) / scale)


def source_multiplier(frac_fav: np.ndarray, d_gold_m: np.ndarray, A_km2: np.ndarray | None = None) -> np.ndarray:
    """B = (0.5 + 0.7·andel gunstig berggrunn oppstrøms + 0.2·exp(−d/5 km)) · A_f, maks 1.2.
    A_f = clip(0,4 + 0,2·log10(A), 0,4, 1,1): større nedbørfelt drenerer mer kildebergart og fører mer gull."""
    b = np.minimum(0.5 + 0.7 * frac_fav + 0.2 * np.exp(-d_gold_m / 5000.0), 1.2)
    if A_km2 is not None:
        b = b * np.clip(0.4 + 0.2 * np.log10(np.maximum(A_km2, 0.1)), 0.4, 1.1)
    return b


def gorge_score(w_dtm_raw: np.ndarray, w_q: np.ndarray) -> np.ndarray:
    """juv = clip((w_Q − w_DTM)/w_Q, 0, 1): kanal mye smalere enn hydraulisk geometri tilsier = innsnevret fjellkanal
    (jettegryter, sprekker, fjell i dagen)."""
    return np.clip((w_q - w_dtm_raw) / np.maximum(w_q, 1.0), 0, 1)


def combine(D, R, sving, os_, foss, gate, B, juv=None) -> np.ndarray:
    raw = (WEIGHTS["D"] * D + WEIGHTS["R"] * R + WEIGHTS["sving"] * sving + WEIGHTS["os"] * os_ + WEIGHTS["foss"] * foss)
    if juv is not None:
        raw = raw + WEIGHTS["juv"] * juv
    return raw * gate * B


def normalize(p_raw: np.ndarray) -> np.ndarray:
    m = np.nanmax(p_raw) if len(p_raw) else 0
    if not m or not np.isfinite(m):
        return np.zeros_like(p_raw)
    return 100.0 * p_raw / m
