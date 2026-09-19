import math
from goldpipe import hydraulics as H


def test_manning_depth_known():
    # Q=50, w=20, S=0.005, n=0.04 -> h ≈ 1.29 m (håndregning: R=1.14, v=1.93 m/s)
    h = H.manning_depth(50, 20, 0.005, 0.04)
    assert 1.2 < h < 1.4
    r = 20 * h / (20 + 2 * h)
    q = (1 / 0.04) * 20 * h * r ** (2 / 3) * 0.005 ** 0.5
    assert math.isclose(q, 50, rel_tol=1e-3)


def test_shields():
    tc = H.shields_critical(0.01)
    assert math.isclose(tc, 0.045 * 1650 * 9.81 * 0.01, rel_tol=1e-9)
    assert 7 < tc < 8


def test_gold_equivalence():
    assert math.isclose(H.gold_equivalent_diameter(0.001), 0.001 * 18300 / 1650, rel_tol=1e-9)
    assert H.gold_mobility(5.0) < 1.0    # 5 Pa flytter ikke et 1 mm gullkorn (terskel ≈ 8 Pa)
    assert H.gold_mobility(1000.0) > 1.0


def test_segment_gate():
    seg = H.segment_hydraulics(245, 60, 0.0002, 0.045)   # flat, bred strekning i Lågen
    assert seg["h"] > 0 and seg["tau"] > 0 and seg["omega"] > 0
    assert 10 < seg["tau_c"] < 14 and seg["M"] < 1.0        # som prototypen: ingen transport på flata
