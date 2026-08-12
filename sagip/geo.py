"""City centroids for the rescue-map proximity query (US-S4).

The map is city-scoped: a viewer chooses a city, and reports are ranked by distance from
that city's centre. `stray_report.city` (reverse-geocoded) is out of MVP scope, so the
centroid — not the stored column — is what anchors the query. Metro Manila first, matching
the launch scope. Coordinates are (lat, lng), approximate city centres.
"""
CITY_CENTROIDS = {
    "Marikina": (14.6507, 121.1029),
    "Pasig": (14.5764, 121.0851),
    "Quezon City": (14.6760, 121.0437),
    "Manila": (14.5995, 120.9842),
    "Makati": (14.5547, 121.0244),
    "Taguig": (14.5176, 121.0509),
    "Pasay": (14.5378, 121.0014),
    "Mandaluyong": (14.5794, 121.0359),
    "San Juan": (14.6019, 121.0355),
    "Caloocan": (14.6577, 120.9842),
}


def centroid_for(city):
    """(lat, lng) for a known city, case-insensitively; None if unknown or unset."""
    if not city:
        return None
    key = city.strip().lower()
    for name, latlng in CITY_CENTROIDS.items():
        if name.lower() == key:
            return latlng
    return None
