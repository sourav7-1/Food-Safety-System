from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import (
    Inspection,
    InspectionCriterion,
    InspectionScore,
    Inspector,
    Stall,
)
from routes import role_required


inspector_bp = Blueprint(
    "inspection_workflow",
    __name__,
    url_prefix="/inspector/inspections",
)


def _current_inspector():
    inspector = Inspector.query.filter_by(
        user_id=current_user.user_id
    ).first()
    if inspector is None:
        abort(403)
    return inspector


def _available_stalls(inspector):
    query = Stall.query.filter_by(status="active")
    if inspector.assigned_area_id is not None:
        query = query.filter_by(area_id=inspector.assigned_area_id)
    return query.order_by(Stall.stall_name).all()


def _parse_inspection_date(value):
    if not value:
        return datetime.now()
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


@inspector_bp.route("/")
@login_required
@role_required("inspector")
def inspections():
    inspector = _current_inspector()
    records = (
        Inspection.query.filter_by(inspector_id=inspector.inspector_id)
        .join(Inspection.stall)
        .order_by(Inspection.inspection_date.desc())
        .all()
    )
    return render_template(
        "inspector/list.html",
        inspections=records,
        inspector=inspector,
    )


@inspector_bp.route("/new", methods=["GET", "POST"])
@login_required
@role_required("inspector")
def create():
    inspector = _current_inspector()
    criteria = (
        InspectionCriterion.query.filter_by(is_active=True)
        .order_by(InspectionCriterion.criteria_id)
        .all()
    )
    stalls = _available_stalls(inspector)

    if request.method == "POST":
        try:
            stall_id = int(request.form.get("stall_id", ""))
            stall = db.session.get(Stall, stall_id)
            if stall is None or stall.status != "active":
                raise ValueError("Select an active stall.")
            if (
                inspector.assigned_area_id is not None
                and stall.area_id != inspector.assigned_area_id
            ):
                raise ValueError(
                    "That stall is outside your assigned inspection area."
                )
            if not criteria:
                raise ValueError(
                    "No active inspection criteria are configured."
                )

            inspection_date = _parse_inspection_date(
                request.form.get("inspection_date")
            )
            latest_existing = (
                Inspection.query.filter(
                    Inspection.stall_id == stall.stall_id,
                    Inspection.status.in_(("submitted", "approved")),
                )
                .order_by(Inspection.inspection_date.desc())
                .first()
            )
            if (
                latest_existing is not None
                and inspection_date < latest_existing.inspection_date
            ):
                raise ValueError(
                    "Inspection date cannot be earlier than this stall's "
                    "most recent inspection ("
                    + latest_existing.inspection_date.strftime(
                        "%Y-%m-%d %H:%M"
                    )
                    + ")."
                )

            submitted_scores = []
            for criterion in criteria:
                raw_score = request.form.get(
                    f"score_{criterion.criteria_id}", ""
                ).strip()
                if raw_score == "":
                    raise ValueError(
                        f"Score is required for {criterion.criteria_name}."
                    )
                try:
                    score = Decimal(raw_score)
                except InvalidOperation as error:
                    raise ValueError(
                        f"Enter a valid score for {criterion.criteria_name}."
                    ) from error
                if score < 0 or score > criterion.max_score:
                    raise ValueError(
                        f"{criterion.criteria_name} must be between 0 and "
                        f"{criterion.max_score}."
                    )
                submitted_scores.append(
                    (
                        criterion,
                        score,
                        request.form.get(
                            f"comments_{criterion.criteria_id}", ""
                        ).strip()
                        or None,
                    )
                )

            inspection = Inspection(
                stall_id=stall.stall_id,
                inspector_id=inspector.inspector_id,
                inspection_date=inspection_date,
                status="submitted",
                remarks=request.form.get("remarks", "").strip() or None,
            )
            db.session.add(inspection)
            db.session.flush()

            for criterion, score, comments in submitted_scores:
                db.session.add(
                    InspectionScore(
                        inspection_id=inspection.inspection_id,
                        criteria_id=criterion.criteria_id,
                        score=score,
                        comments=comments,
                    )
                )

            # Flush every score insert so MySQL validation and total-score
            # triggers run before risk calculation.
            db.session.flush()
            db.session.refresh(inspection)

            procedure_result = db.session.execute(
                text(
                    """
                    CALL calculate_stall_risk(
                      :stall_id,
                      @calculated_risk_level,
                      @calculated_risk_score,
                      @calculated_reinspection_date
                    )
                    """
                ),
                {"stall_id": stall.stall_id},
            )
            procedure_result.close()
            risk_result = db.session.execute(
                text(
                    """
                    SELECT
                      @calculated_risk_level AS risk_level,
                      @calculated_risk_score AS risk_score,
                      @calculated_reinspection_date AS reinspection_date
                    """
                )
            ).mappings().one()

            if risk_result["risk_level"] is None:
                raise RuntimeError(
                    "MySQL risk procedure returned no risk result."
                )

            inspection.risk_level = risk_result["risk_level"]
            inspection.reinspection_date = risk_result[
                "reinspection_date"
            ]
            db.session.commit()

            flash(
                "Inspection submitted and risk calculated successfully.",
                "success",
            )
            return redirect(
                url_for(
                    "inspection_workflow.detail",
                    inspection_id=inspection.inspection_id,
                )
            )
        except (ValueError, SQLAlchemyError, RuntimeError) as error:
            db.session.rollback()
            flash(
                f"Inspection was not submitted. {error}",
                "danger",
            )

    return render_template(
        "inspector/form.html",
        inspector=inspector,
        criteria=criteria,
        stalls=stalls,
        default_inspection_date=datetime.now().strftime("%Y-%m-%dT%H:%M"),
    )


@inspector_bp.route("/<int:inspection_id>")
@login_required
@role_required("inspector")
def detail(inspection_id):
    inspector = _current_inspector()
    inspection = Inspection.query.filter_by(
        inspection_id=inspection_id,
        inspector_id=inspector.inspector_id,
    ).first_or_404()
    grade = db.session.execute(
        text("SELECT get_hygiene_grade(:score)"),
        {"score": inspection.overall_score},
    ).scalar_one()
    return render_template(
        "inspector/detail.html",
        inspection=inspection,
        grade=grade,
    )
