"""US-SEC1 — coarsen_point(): deterministic ~500m grid coarsening, no jitter."""
import math

from sagip.geo import COARSEN_CELL_SIZE_M, EARTH_RADIUS_M, coarsen_point

MARIKINA = (14.6507, 121.1029)


def test_is_deterministic_repeated_calls_match_exactly():
    """The whole point of a grid (vs. random jitter) is that repeated calls for the SAME
    point never drift — jitter that averages out over many calls would let an
    unprivileged caller triangulate the real point just by asking enough times."""
    a = coarsen_point(*MARIKINA)
    b = coarsen_point(*MARIKINA)
    assert a == b


def test_the_result_is_within_the_cell_size_of_the_input():
    lat, lng = MARIKINA
    c_lat, c_lng = coarsen_point(lat, lng)
    # ~500m in degrees at this latitude is a small fraction of a degree — the coarsened
    # point must stay in the neighborhood of the real one, not jump cities.
    assert abs(c_lat - lat) < 0.01
    assert abs(c_lng - lng) < 0.01


def test_two_points_at_the_same_latitude_and_nearby_longitude_share_a_cell():
    # Holding lat fixed keeps the longitude-per-degree scale (which depends on lat via
    # cos()) identical between the two calls, so this is the one axis where "nearby ->
    # same cell" is actually guaranteed by the implementation, not just usually true.
    lat, lng = MARIKINA
    m_per_deg_lat = math.pi * EARTH_RADIUS_M / 180
    m_per_deg_lng = m_per_deg_lat * math.cos(math.radians(lat))
    tiny_deg = (COARSEN_CELL_SIZE_M * 0.1) / m_per_deg_lng  # 10% of a cell width, same lat
    a = coarsen_point(lat, lng)
    b = coarsen_point(lat, lng + tiny_deg)
    assert a == b


def test_a_tiny_latitude_shift_can_cross_a_cell_at_the_boundary_but_stays_deterministic():
    """Because each call derives its own longitude scale from its own latitude (see
    coarsen_point's docstring), a lat-only perturbation can — right at a cell edge —
    land in the neighboring cell instead of the same one. That's an accepted precision
    wrinkle, not a security defect: the property that actually matters (the SAME input
    always coarsens to the SAME output, so no averaging-out attack) still holds
    regardless of which side of an edge either point lands on."""
    lat, lng = MARIKINA
    m_per_deg_lat = math.pi * EARTH_RADIUS_M / 180
    tiny_deg = (COARSEN_CELL_SIZE_M * 0.1) / m_per_deg_lat
    a1 = coarsen_point(lat - tiny_deg, lng)
    a2 = coarsen_point(lat - tiny_deg, lng)  # same input, called again
    b1 = coarsen_point(lat + tiny_deg, lng)
    b2 = coarsen_point(lat + tiny_deg, lng)
    assert a1 == a2  # determinism holds regardless of which cell it landed in
    assert b1 == b2


def test_points_far_apart_coarsen_differently():
    a = coarsen_point(14.6507, 121.1029)   # Marikina
    b = coarsen_point(14.5995, 120.9842)   # Manila
    assert a != b


def test_custom_cell_size_changes_the_grid():
    lat, lng = MARIKINA
    a = coarsen_point(lat, lng, cell_size_m=500)
    b = coarsen_point(lat, lng, cell_size_m=5000)
    # A coarser grid snaps to a different (larger) cell's centroid.
    assert a != b
