"""Hydrauliske formler (dokumentert på Metode-siden).

Alle størrelser i SI. Bredt rektangulært tverrsnitt.
"""
from __future__ import annotations

import numpy as np

RHO = 1000.0        # vann kg/m³
RHO_S = 2650.0      # kvarts/sand kg/m³
RHO_AU = 19300.0    # gull kg/m³
G = 9.81
THETA_C = 0.045     # Shields-parameter, kritisk


def manning_depth(q: float, w: float, s: float, n: float) -> float:
    """Normaldybde h fra Manning: Q = (1/n)·w·h·R^(2/3)·S^(1/2), R = w·h/(w+2h). Biseksjon."""
    if q <= 0 or w <= 0 or s <= 0:
        return 0.0
    lo, hi = 1e-3, 60.0

    def f(h):
        r = w * h / (w + 2 * h)
        return (1.0 / n) * w * h * r ** (2.0 / 3.0) * s ** 0.5 - q

    if f(hi) < 0:
        return hi
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def shear_stress(h: float, s: float) -> float:
    """τ = ρ·g·h·S  (Pa)"""
    return RHO * G * h * s


def stream_power(q: float, s: float, w: float) -> float:
    """ω = ρ·g·Q·S / w  (W/m²)"""
    return RHO * G * q * s / max(w, 0.1)


def d50_from_slope(s: float, coeff: float = 1.0, exp: float = 0.5,
                   dmin: float = 0.016, dmax: float = 0.5) -> float:
    """D50 = coeff·S^exp (m), klemt til [dmin, dmax]. Kalibrert mot Rollag-prototypen:
    flat elv (S≈0.0002) -> 16 mm (τ_c≈12 Pa), bratt stryk (S≈0.02) -> 14 cm (τ_c≈100 Pa)."""
    return float(np.clip(coeff * max(s, 1e-6) ** exp, dmin, dmax))


def shields_critical(d50: float, theta_c: float = THETA_C) -> float:
    """τ_c = θ_c·(ρ_s−ρ)·g·D50"""
    return theta_c * (RHO_S - RHO) * G * d50


def gold_equivalent_diameter(d_au: float, shape_factor: float = 1.0) -> float:
    """Hydraulisk ekvivalent kvartsdiameter for et gullkorn: d_eq = d_Au·(ρ_Au−ρ)/(ρ_s−ρ)·formfaktor."""
    return d_au * (RHO_AU - RHO) / (RHO_S - RHO) * shape_factor


def gold_mobility(tau: float, d_au: float = 0.001, theta_c: float = THETA_C) -> float:
    """M_Au = τ / (θ_c·(ρ_Au−ρ)·g·d_Au). <1: gullkornet ligger i ro."""
    return tau / (theta_c * (RHO_AU - RHO) * G * d_au)


def segment_hydraulics(q: float, w: float, s: float, n: float, d50_coeff=1.0, d50_exp=0.5) -> dict:
    """Alle hydrauliske størrelser for ett 100 m-segment."""
    s_eff = max(s, 1e-5)
    h = manning_depth(q, w, s_eff, n)
    tau = shear_stress(h, s_eff)
    omega = stream_power(q, s_eff, w)
    d50 = d50_from_slope(s_eff, d50_coeff, d50_exp)
    tau_c = shields_critical(d50)
    return {
        "h": h, "v": q / max(w * h, 1e-6), "tau": tau, "omega": omega, "d50": d50,
        "tau_c": tau_c, "M": tau / max(tau_c, 1e-6), "M_au": gold_mobility(tau),
    }
