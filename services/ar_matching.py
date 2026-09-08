import math
from difflib import SequenceMatcher


# Confidence-score weights (must sum to 100). Visual/image matching is out
# of scope for the web-only MVP, so the original 4-signal split collapses
# to these 3 -- see the AR Scan feature plan for why 40/30/30 rather than
# the original 40/30/15/15.
GPS_WEIGHT = 40
OCR_WEIGHT = 30
HEADING_WEIGHT = 30

# GPS score falls off linearly to 0 at this distance -- candidates beyond
# it are still returned by the nearby-stalls radius query but score 0 here.
GPS_MAX_DISTANCE_M = 50
# Approximate rear-camera field of view used to translate an angular
# heading/bearing mismatch into a score falloff.
HEADING_FOV_DEG = 60

CONFIDENCE_HIGH = 90
CONFIDENCE_CONFIRM = 75
CONFIDENCE_AMBIGUOUS = 50


def bearing_degrees(lat1, lng1, lat2, lng2):
    """Initial great-circle bearing from point 1 to point 2, in degrees
    clockwise from true north, in [0, 360)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lng2 - lng1)
    x = math.sin(delta_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        delta_lambda
    )
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _angular_difference(heading_a, heading_b):
    """Smallest angle between two compass headings, in [0, 180]."""
    diff = abs(heading_a - heading_b) % 360
    return diff if diff <= 180 else 360 - diff


def gps_score(distance_m):
    if distance_m is None:
        return 0.0
    return GPS_WEIGHT * max(0.0, 1 - distance_m / GPS_MAX_DISTANCE_M)


def ocr_score(ocr_text, stall_name):
    """Fuzzy match ratio between OCR'd signboard text and the stall's
    registered name. Empty/missing OCR text scores 0 -- a stall with no
    readable sign shouldn't get a free pass on this signal."""
    if not ocr_text or not ocr_text.strip():
        return 0.0
    ratio = SequenceMatcher(
        None, ocr_text.strip().lower(), stall_name.strip().lower()
    ).ratio()
    return OCR_WEIGHT * ratio


def heading_score(user_heading_deg, bearing_deg):
    """user_heading_deg is None when the device has no compass or
    orientation permission was denied -- never guessed, always 0 then."""
    if user_heading_deg is None or bearing_deg is None:
        return 0.0
    diff = _angular_difference(user_heading_deg, bearing_deg)
    return HEADING_WEIGHT * max(0.0, 1 - diff / HEADING_FOV_DEG)


def confidence_score(distance_m, ocr_text, stall_name, user_heading_deg, bearing_deg):
    gps = gps_score(distance_m)
    ocr = ocr_score(ocr_text, stall_name)
    heading = heading_score(user_heading_deg, bearing_deg)
    total = gps + ocr + heading
    return {
        "gps": round(gps, 1),
        "ocr": round(ocr, 1),
        "heading": round(heading, 1),
        "total": round(total, 1),
    }


def confidence_band(total_score):
    """Never show a specific shop's rating below CONFIDENCE_AMBIGUOUS -- a
    wrong rating shown confidently is worse than no rating."""
    if total_score >= CONFIDENCE_HIGH:
        return "high"
    if total_score >= CONFIDENCE_CONFIRM:
        return "confirm"
    if total_score >= CONFIDENCE_AMBIGUOUS:
        return "ambiguous"
    return "low"
