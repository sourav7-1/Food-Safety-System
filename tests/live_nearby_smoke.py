"""Manual live-MySQL smoke check for the "Nearby Stalls" feature.

Exercises everything that needs the real latest_stall_inspection view and
get_hygiene_grade() function -- neither exists under the sqlite:///:memory:
database the main unittest suite (tests/test_nearby_stalls.py) runs
against, so distance-query correctness lives here instead, following the
existing tests/live_mysql_smoke.py pattern.

Run with:
    python tests/live_nearby_smoke.py

The script creates only QA-prefixed records and removes them in `finally`.
"""

import math
import sys
from datetime import datetime, timedelta
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app
from extensions import db
from models import Area, Inspection, Inspector, Role, Stall, User, Vendor


QA_TAG = "QA-NEARBY"
ORIGIN_LAT = 23.8103
ORIGIN_LNG = 90.4125
EARTH_RADIUS_KM = 6371.0


def _destination_point(lat, lng, bearing_deg, distance_km):
    """Independent (non-Haversine-derived) formula for "the point exactly
    distance_km from (lat, lng) at bearing_deg" -- used to build fixtures
    with a known, precomputed expected distance, rather than hand-picking
    coordinates and hoping the arithmetic works out.
    """
    lat1 = math.radians(lat)
    lng1 = math.radians(lng)
    brng = math.radians(bearing_deg)
    d_r = distance_km / EARTH_RADIUS_KM

    lat2 = math.asin(
        math.sin(lat1) * math.cos(d_r) + math.cos(lat1) * math.sin(d_r) * math.cos(brng)
    )
    lng2 = lng1 + math.atan2(
        math.sin(brng) * math.sin(d_r) * math.cos(lat1),
        math.cos(d_r) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lng2)


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
        session["_csrf_token"] = "qa-csrf-token"


def run():
    created = {
        "inspections": [],
        "stalls": [],
        "inspector": None,
        "vendor": None,
        "area": None,
        "users": [],
    }
    with app.app_context():
        try:
            student_role = Role.query.filter_by(role_name="student").one()
            vendor_role = Role.query.filter_by(role_name="vendor").one()
            inspector_role = Role.query.filter_by(role_name="inspector").one()

            area = Area(area_name=f"{QA_TAG} Area", city="Dhaka", zone="Test")
            db.session.add(area)
            db.session.flush()
            created["area"] = area

            vendor_user = User(
                role_id=vendor_role.role_id,
                full_name=f"{QA_TAG} Vendor",
                email=f"{QA_TAG.lower()}-vendor@localhost.test",
                status="active",
                auth_provider="local",
            )
            vendor_user.set_password("QaTest!2026")
            db.session.add(vendor_user)
            db.session.flush()
            created["users"].append(vendor_user)

            vendor = Vendor(
                user_id=vendor_user.user_id,
                business_name=f"{QA_TAG} Vendor Business",
                license_number=f"{QA_TAG}-LICENSE-001",
                status="approved",
            )
            db.session.add(vendor)
            db.session.flush()
            created["vendor"] = vendor

            inspector_user = User(
                role_id=inspector_role.role_id,
                full_name=f"{QA_TAG} Inspector",
                email=f"{QA_TAG.lower()}-inspector@localhost.test",
                status="active",
                auth_provider="local",
            )
            inspector_user.set_password("QaTest!2026")
            db.session.add(inspector_user)
            db.session.flush()
            created["users"].append(inspector_user)

            inspector = Inspector(
                user_id=inspector_user.user_id,
                employee_code=f"{QA_TAG}-INSP-001",
            )
            db.session.add(inspector)
            db.session.flush()
            created["inspector"] = inspector

            student_user = User(
                role_id=student_role.role_id,
                full_name=f"{QA_TAG} Student",
                email=f"{QA_TAG.lower()}999-99-999@diu.edu.bd",
                status="active",
                auth_provider="local",
            )
            student_user.set_password("QaTest!2026")
            db.session.add(student_user)
            db.session.flush()
            created["users"].append(student_user)

            def make_stall(suffix, lat, lng):
                stall = Stall(
                    vendor_id=vendor.vendor_id,
                    area_id=area.area_id,
                    stall_name=f"{QA_TAG} Stall {suffix}",
                    stall_code=f"{QA_TAG}-{suffix}",
                    address="123 Test Street",
                    latitude=lat,
                    longitude=lng,
                    status="active",
                )
                db.session.add(stall)
                db.session.flush()
                created["stalls"].append(stall)
                return stall

            def make_inspection(stall, score, risk_level, days_ago=1):
                inspection = Inspection(
                    stall_id=stall.stall_id,
                    inspector_id=inspector.inspector_id,
                    inspection_date=datetime.utcnow() - timedelta(days=days_ago),
                    overall_score=score,
                    risk_level=risk_level,
                    status="approved",
                )
                db.session.add(inspection)
                db.session.flush()
                created["inspections"].append(inspection)
                return inspection

            # -- Fixture 1: very close to origin (<50m) -- exercises the
            #    ACOS(...) LEAST/GREATEST clamp; without it this is exactly
            #    the row most likely to vanish from results.
            lat_close, lng_close = _destination_point(ORIGIN_LAT, ORIGIN_LNG, 0, 0.03)
            stall_close = make_stall("CLOSE", lat_close, lng_close)
            make_inspection(stall_close, 92.0, "low")  # grade A -> green

            # -- Fixture 2: 2 km away, amber grade.
            lat_2km, lng_2km = _destination_point(ORIGIN_LAT, ORIGIN_LNG, 90, 2.0)
            stall_2km = make_stall("2KM", lat_2km, lng_2km)
            make_inspection(stall_2km, 60.0, "medium")  # grade C -> amber

            # -- Fixture 3: 8 km away -- must be excluded at radius_km=5.
            lat_8km, lng_8km = _destination_point(ORIGIN_LAT, ORIGIN_LNG, 180, 8.0)
            stall_8km = make_stall("8KM", lat_8km, lng_8km)
            make_inspection(stall_8km, 95.0, "low")

            # -- Fixture 4: NULL lat/lng -- must never appear at any radius.
            stall_null = make_stall("NULLLOC", None, None)
            make_inspection(stall_null, 90.0, "low")

            # -- Fixture 5: has coordinates, zero inspections -- must
            #    appear with hygiene_grade null / marker_color gray, not
            #    omitted or erroring.
            lat_noinsp, lng_noinsp = _destination_point(ORIGIN_LAT, ORIGIN_LNG, 45, 1.0)
            make_stall("NOINSP", lat_noinsp, lng_noinsp)

            # -- Fixture 6: good grade but flagged high risk -- risk
            #    status must override the grade-derived color to red.
            lat_hr, lng_hr = _destination_point(ORIGIN_LAT, ORIGIN_LNG, 270, 1.5)
            stall_highrisk = make_stall("HIGHRISK", lat_hr, lng_hr)
            make_inspection(stall_highrisk, 90.0, "high")  # grade A but risk=high

            # -- Fixture 7: 150 stalls clustered just inside the 5km
            #    radius (4.5-4.95 km out) to exercise LIMIT 100. Placed
            #    farther out than every other fixture above (all <= 2 km)
            #    so they can never crowd the named fixtures out of the
            #    nearest-100 cutoff -- this isolates "does LIMIT 100 cap
            #    the result set" from "are the named fixtures present",
            #    which a denser/closer cluster would conflate.
            for i in range(150):
                lat_i, lng_i = _destination_point(
                    ORIGIN_LAT, ORIGIN_LNG, (i * 37) % 360, 4.5 + (i % 20) * 0.02
                )
                stall_i = make_stall(f"BULK{i:03d}", lat_i, lng_i)
                make_inspection(stall_i, 80.0, "low")

            db.session.commit()

            client = app.test_client()
            _login(client, student_user.user_id)

            def fetch(radius_km=5, **extra):
                params = f"lat={ORIGIN_LAT}&lng={ORIGIN_LNG}&radius_km={radius_km}"
                for key, value in extra.items():
                    params += f"&{key}={value}"
                response = client.get(f"/customer/api/stalls/nearby?{params}")
                assert response.status_code == 200, (
                    f"expected 200, got {response.status_code}: {response.get_data(as_text=True)}"
                )
                return response.get_json()

            # -- radius=5: close/2km/highrisk/noinsp in range; 8km and
            #    null-location excluded; plus the 150 bulk stalls capped
            #    at LIMIT 100.
            data = fetch(radius_km=5)
            by_code = {s["stall_id"]: s for s in data["stalls"]}
            stall_id_by_code = {s.stall_code: s.stall_id for s in created["stalls"]}

            assert data["count"] == 100, f"expected LIMIT 100, got {data['count']}"
            assert len(data["stalls"]) == 100

            returned_ids = {s["stall_id"] for s in data["stalls"]}
            assert stall_id_by_code[stall_null.stall_code] not in returned_ids, (
                "NULL-location stall must never appear"
            )
            assert stall_id_by_code[stall_8km.stall_code] not in returned_ids, (
                "8km stall must be excluded at radius_km=5"
            )

            close_id = stall_id_by_code[stall_close.stall_code]
            assert close_id in returned_ids, "closest stall must survive the ACOS clamp, not vanish"
            close_row = by_code[close_id]
            assert close_row["distance_km"] < 0.05, close_row["distance_km"]
            assert close_row["marker_color"] == "green"

            twokm_id = stall_id_by_code[stall_2km.stall_code]
            assert twokm_id in returned_ids
            twokm_row = by_code[twokm_id]
            assert abs(twokm_row["distance_km"] - 2.0) <= 0.05, twokm_row["distance_km"]
            assert twokm_row["marker_color"] == "amber"

            highrisk_id = stall_id_by_code[stall_highrisk.stall_code]
            assert highrisk_id in returned_ids
            highrisk_row = by_code[highrisk_id]
            assert highrisk_row["hygiene_grade"] == "A"
            assert highrisk_row["is_high_risk"] is True
            assert highrisk_row["marker_color"] == "red", (
                "risk status must override an otherwise-green grade"
            )

            # Ordering: nearest first.
            distances = [s["distance_km"] for s in data["stalls"]]
            assert distances == sorted(distances), "results must be ordered nearest-first"

            # -- Small radius: only the <50m stall should qualify, and the
            #    no-inspection stall (1km away) should still appear at a
            #    radius that includes it, with a null grade / gray marker.
            data_small = fetch(radius_km=0.1)
            assert data_small["count"] == 1
            assert data_small["stalls"][0]["stall_id"] == close_id

            data_1_2 = fetch(radius_km=1.2)
            noinsp_id = stall_id_by_code["QA-NEARBY-NOINSP"]
            noinsp_rows = [s for s in data_1_2["stalls"] if s["stall_id"] == noinsp_id]
            assert len(noinsp_rows) == 1, "uninspected stall must appear, not be omitted"
            assert noinsp_rows[0]["hygiene_grade"] is None
            assert noinsp_rows[0]["marker_color"] == "gray"

            # -- radius_km omitted -> defaults to 5, request still succeeds.
            response = client.get(f"/customer/api/stalls/nearby?lat={ORIGIN_LAT}&lng={ORIGIN_LNG}")
            assert response.status_code == 200
            assert response.get_json()["radius_km"] == 5

            # -- radius_km above the server cap -> clamped, not rejected.
            response = client.get(
                f"/customer/api/stalls/nearby?lat={ORIGIN_LAT}&lng={ORIGIN_LNG}&radius_km=1000"
            )
            assert response.status_code == 200
            clamped = response.get_json()
            assert clamped["radius_km"] == 25, clamped["radius_km"]

            # -- Security: response shape only exposes the documented
            #    fields -- no vendor_id or other internal columns leaked.
            sample = data["stalls"][0]
            allowed_keys = {
                "stall_id", "name", "address", "latitude", "longitude",
                "distance_km", "hygiene_grade", "overall_score",
                "inspection_date", "is_high_risk", "marker_color", "detail_url",
            }
            assert set(sample.keys()) == allowed_keys, set(sample.keys())

            print("live_nearby_smoke: all assertions passed")

        finally:
            db.session.rollback()
            for inspection in created["inspections"]:
                db.session.delete(db.session.get(Inspection, inspection.inspection_id) or inspection)
            db.session.flush()
            for stall in created["stalls"]:
                obj = db.session.get(Stall, stall.stall_id)
                if obj:
                    db.session.delete(obj)
            db.session.flush()
            if created["inspector"]:
                obj = db.session.get(Inspector, created["inspector"].inspector_id)
                if obj:
                    db.session.delete(obj)
            if created["vendor"]:
                obj = db.session.get(Vendor, created["vendor"].vendor_id)
                if obj:
                    db.session.delete(obj)
            db.session.flush()
            for user in created["users"]:
                obj = db.session.get(User, user.user_id)
                if obj:
                    db.session.delete(obj)
            if created["area"]:
                obj = db.session.get(Area, created["area"].area_id)
                if obj:
                    db.session.delete(obj)
            db.session.commit()


if __name__ == "__main__":
    run()
