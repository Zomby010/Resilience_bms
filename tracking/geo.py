"""Distance and geofence rules. Pure functions, no database."""
import math

from .models import MAX_ACCURACY_M, NEAR_LIMIT_M, LocationStatus

EARTH_RADIUS_M = 6_371_008.8  # mean Earth radius (IUGG)


def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres between two latitude/longitude points (haversine).

    Within a few hundred metres this is accurate to well under 1 m, which is far
    better than phone GPS itself.
    """
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = p2 - p1
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def classify(distance, accuracy, radius):
    """Turn a distance into a status. No gaps, no overlaps:

        accuracy worse than MAX_ACCURACY_M  -> WEAK (we do not know, so never OFF)
        0 .. radius                         -> ON
        radius .. NEAR_LIMIT_M              -> NEAR
        beyond NEAR_LIMIT_M                 -> OFF

    Boundaries are inclusive on the lower status: exactly `radius` is ON,
    exactly NEAR_LIMIT_M is NEAR.
    """
    if accuracy > MAX_ACCURACY_M:
        return LocationStatus.WEAK
    if distance <= radius:
        return LocationStatus.ON
    if distance <= NEAR_LIMIT_M:
        return LocationStatus.NEAR
    return LocationStatus.OFF
