"""Applicant-facing endpoints for the public application flow.

This module serves public routes for the applicant email-key login flow and
application management. Every route is authentication-free -- the applicant is
identified by a short-lived application-scoped JWT once they verify their email key.

Storage contract: application documents are persisted through ``api.applications``
(the single owner of the ``applications`` collection) so the D9 form lock, which
counts documents in that same collection by ``market_id``, sees them immediately.
"""

import re
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from db_config import get_database
from datatypes import (
    Application,
    ApplicationForm,
    ApplicationStatus,
    ApplicationType,
    FormField,
    MarketPhase,
    phase_from_market_document,
)
from market_documents import non_draft_market_prefilter
import api.applications as ApplicationsApi

db = get_database()
markets_collection = db["markets"]
from utils.tokens import generate_otp, get_otp_expiry, verify_token_expiry
from utils.email import send_otp_email
from utils.application_token import generate_application_token, verify_application_token

logger = logging.getLogger(__name__)

MAX_OTP_ATTEMPTS = 5
OTP_EXPIRY_MINUTES = 5

# ── slug helpers ───────────────────────────────────────────────────────────


def _slugify(name: str) -> str:
    """Slugify a market name for use in public URLs. Matches attendance.py."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s


def _get_market_doc_by_slug(market_slug: str) -> Optional[Dict[str, Any]]:
    """Find a market whose slugified name matches the given slug.

    Reuses the same prefilter + phase check pattern as
    ``attendance.get_published_market_by_slug``.
    """
    if not market_slug:
        return None
    target = market_slug.strip().lower()
    for doc in markets_collection.find(non_draft_market_prefilter()):
        if _slugify(doc.get("name", "")) != target:
            continue
        if phase_from_market_document(doc) == MarketPhase.DRAFT:
            continue
        return doc
    return None


def _get_market_phase(doc: Dict[str, Any]) -> MarketPhase:
    """Get the effective phase of a market document."""
    return phase_from_market_document(doc)


# ── application helpers ─────────────────────────────────────────────────────


def _find_or_create_application(
    market_id: str, email: str,
) -> Application:
    """Return the existing main application for this market + email, or create a draft one."""
    existing = ApplicationsApi.applications_collection.find_one({
        ApplicationsApi.MARKET_ID_FIELD: market_id,
        "applicant_email": email,
        "application_type": ApplicationType.MAIN.value,
    })
    if existing:
        return Application(**existing)

    app = Application(
        market_id=market_id,
        applicant_email=email,
        form_data={},
        status=ApplicationStatus.OPEN,
        application_type=ApplicationType.MAIN,
    )
    ApplicationsApi.applications_collection.insert_one(app.model_dump())
    return app


def _validate_form_data(form_data: Dict[str, Any], fields: list) -> Optional[str]:
    """Validate form data against the form fields. Returns an error message or None.

    Every field type the builder can produce must validate -- no per-field special-casing.
    """
    for field in fields:
        key = field.get("key", "")
        label = field.get("label", key)
        required = field.get("required", False)
        ft = field.get("type", "text")
        value = form_data.get(key)

        if required and (value is None or (isinstance(value, str) and value.strip() == "")):
            return f'"{label}" is required.'

        if value is not None and value != "":
            if ft == "email":
                if isinstance(value, str) and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value.strip()):
                    return f'"{label}" must be a valid email address.'
            elif ft == "number":
                try:
                    float(value)
                except (ValueError, TypeError):
                    return f'"{label}" must be a number.'
            elif ft == "select":
                options = field.get("options", [])
                if value not in options:
                    return f'"{label}" has an invalid selection.'
            elif ft == "multi_select":
                options = field.get("options", [])
                if isinstance(value, list):
                    for v in value:
                        if v not in options:
                            return f'"{label}" contains an invalid selection: "{v}".'
                else:
                    return f'"{label}" must be a list of selections.'
            elif ft == "checkbox":
                if not isinstance(value, bool):
                    return f'"{label}" must be true or false.'
            elif ft == "date":
                if isinstance(value, str):
                    try:
                        datetime.fromisoformat(value.strip())
                    except (ValueError, TypeError):
                        return f'"{label}" must be a valid date (YYYY-MM-DD).'
    return None


# ── public endpoints ────────────────────────────────────────────────────────


def request_applicant_key(market_slug: str, email: str) -> Tuple[Dict[str, Any], int]:
    """Stage 1 of the applicant login flow: send a one-time key to the applicant's email.

    Returns a generic success message regardless of whether an application was found
    or created, to prevent email enumeration.

    Args:
        market_slug: The URL-safe slug of the market.
        email: The applicant's email address.

    Returns:
        Tuple of (response_body, status_code).

    Anti-F6: refusal messages name the exact problem.
    """
    if not market_slug or not market_slug.strip():
        return {"error": "Market identifier is required."}, 400
    if not email or not email.strip():
        return {"error": "Email address is required."}, 400
    email = email.strip().lower()

    market_doc = _get_market_doc_by_slug(market_slug)
    if not market_doc:
        return {"error": "Market not found. Check the URL and try again."}, 404

    market_id = market_doc.get("id", "")
    phase = _get_market_phase(market_doc)

    # The form and API are visible only when applications are open
    if phase != MarketPhase.APPLICATIONS_OPEN:
        phase_label = phase.value.replace("_", " ").title()
        return {
            "error": f"Applications are not currently open for this market. "
                     f"The market is in the {phase_label} phase.",
        }, 403

    app = _find_or_create_application(market_id, email)

    # Generate and store OTP
    otp = generate_otp()
    app.otp = otp
    app.otp_expires = get_otp_expiry(minutes=OTP_EXPIRY_MINUTES)
    app.otp_attempts = 0
    ApplicationsApi.applications_collection.update_one(
        {"id": app.id},
        {"$set": {
            "otp": app.otp,
            "otp_expires": app.otp_expires,
            "otp_attempts": app.otp_attempts,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    # Send email (fire-and-forget -- the message is generic either way)
    send_otp_email(email, otp)

    return {
        "message": "If an application exists for this email, a verification code has been sent.",
    }, 200


def verify_applicant_key(
    market_slug: str, email: str, key: str,
) -> Tuple[Dict[str, Any], int]:
    """Stage 2 of the applicant login flow: verify the one-time key.

    On success returns a short-lived application-scoped JWT + application data.
    On failure returns a specific error message describing exactly what went wrong.

    Args:
        market_slug: The URL-safe slug of the market.
        email: The applicant's email address.
        key: The 6-digit verification code.

    Returns:
        Tuple of (response_body, status_code).

    Anti-F6: every refusal names exactly what is wrong and what to do.
    """
    if not market_slug or not market_slug.strip():
        return {"error": "Market identifier is required."}, 400
    if not email or not email.strip():
        return {"error": "Email address is required."}, 400
    if not key or not key.strip():
        return {"error": "Verification code is required."}, 400

    email = email.strip().lower()
    key = key.strip()

    market_doc = _get_market_doc_by_slug(market_slug)
    if not market_doc:
        return {"error": "Market not found. Check the URL and try again."}, 404

    market_id = market_doc.get("id", "")

    app_doc = ApplicationsApi.applications_collection.find_one({
        ApplicationsApi.MARKET_ID_FIELD: market_id,
        "applicant_email": email,
        "application_type": ApplicationType.MAIN.value,
    })

    if not app_doc:
        return {
            "error": "No application found for this email. "
                     "Please visit the application page to apply first.",
        }, 404

    app = Application(**app_doc)

    # Check expiry
    if not app.otp_expires or not verify_token_expiry(app.otp_expires):
        return {
            "error": "This verification code has expired. Please request a new one.",
        }, 401

    # Check attempt limit
    if app.otp_attempts >= MAX_OTP_ATTEMPTS:
        return {
            "error": "Too many incorrect attempts. Please request a new code.",
        }, 429

    # Check key
    if app.otp != key:
        new_attempts = app.otp_attempts + 1
        ApplicationsApi.applications_collection.update_one(
            {"id": app.id},
            {"$set": {"otp_attempts": new_attempts}},
        )
        remaining = MAX_OTP_ATTEMPTS - new_attempts
        if remaining <= 0:
            return {
                "error": "Too many incorrect attempts. Please request a new code.",
            }, 429
        return {
            "error": f"Incorrect code. You have {remaining} attempt{'s' if remaining != 1 else ''} remaining.",
        }, 401

    # Success -- clear OTP fields
    token = generate_application_token(app.id, market_id, email)
    ApplicationsApi.applications_collection.update_one(
        {"id": app.id},
        {"$set": {
            "otp": None,
            "otp_expires": None,
            "otp_attempts": 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    return {
        "token": token,
        "application": _application_response(app),
    }, 200


def get_applicant_application(token_payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """Return the authenticated applicant's application data.

    Args:
        token_payload: Decoded JWT payload from ``verify_application_token``.

    Returns:
        Tuple of (response_body, status_code).
    """
    app_id = token_payload.get("application_id", "")
    app_doc = ApplicationsApi.applications_collection.find_one({"id": app_id})
    if not app_doc:
        return {"error": "Application not found."}, 404

    app = Application(**app_doc)
    return {"application": _application_response(app)}, 200


def save_applicant_application(
    token_payload: Dict[str, Any], form_data: Dict[str, Any],
) -> Tuple[Dict[str, Any], int]:
    """Save or update the authenticated applicant's application.

    Validates the form data against the market's application form fields.
    Refuses submission when the market is not in ``applications_open``.

    Args:
        token_payload: Decoded JWT payload from ``verify_application_token``.
        form_data: The form answers keyed by field keys.

    Returns:
        Tuple of (response_body, status_code).

    Anti-F6: validation errors name the specific field and problem.
    """
    app_id = token_payload.get("application_id", "")
    market_id = token_payload.get("market_id", "")

    app_doc = ApplicationsApi.applications_collection.find_one({"id": app_id})
    if not app_doc:
        return {"error": "Application not found."}, 404

    # Check market phase
    market_doc = markets_collection.find_one({"id": market_id})
    if not market_doc:
        return {"error": "Market not found."}, 404

    phase = phase_from_market_document(market_doc)
    if phase != MarketPhase.APPLICATIONS_OPEN:
        phase_label = phase.value.replace("_", " ").title()
        return {
            "error": f"Applications are no longer open for this market. "
                     f"The market is in the {phase_label} phase.",
        }, 403

    # Validate form data against the application form fields
    application_form = market_doc.get("applicationForm")
    if application_form and application_form.get("fields"):
        error = _validate_form_data(form_data, application_form["fields"])
        if error:
            return {"error": error}, 422

    now = datetime.now(timezone.utc).isoformat()
    ApplicationsApi.applications_collection.update_one(
        {"id": app_id},
        {"$set": {
            "form_data": form_data,
            "status": ApplicationStatus.OPEN.value,
            "submitted_at": app_doc.get("submitted_at") or now,
            "updated_at": now,
        }},
    )

    # Return the updated application
    updated_doc = ApplicationsApi.applications_collection.find_one({"id": app_id})
    app = Application(**updated_doc) if updated_doc else Application(**app_doc)
    return {"application": _application_response(app)}, 200


def get_public_application_form(market_slug: str) -> Tuple[Dict[str, Any], int]:
    """Return the public application form for a market.

    Accessible without authentication. Returns the form only when the market
    phase allows applicants to see it.

    Args:
        market_slug: The URL-safe slug of the market.

    Returns:
        Tuple of (response_body, status_code).

    Anti-F6: when the form is not available, the reason is clear.
    """
    if not market_slug or not market_slug.strip():
        return {"error": "Market identifier is required."}, 400

    market_doc = _get_market_doc_by_slug(market_slug)
    if not market_doc:
        return {"error": "Market not found. Check the URL and try again."}, 404

    phase = _get_market_phase(market_doc)
    application_form = market_doc.get("applicationForm")

    if application_form:
        # Return the form with field-level details (camelCase for front-end)
        fields = []
        for i, f in enumerate(application_form.get("fields", [])):
            fields.append({
                "key": f.get("key", ""),
                "label": f.get("label", ""),
                "type": f.get("type", "text"),
                "required": f.get("required", False),
                "options": f.get("options", []),
                "helpText": f.get("helpText"),
                "order": f.get("order", i),
            })

        return {
            "application_form": {
                "fields": fields,
            },
            "phase": phase.value,
            "is_open": phase == MarketPhase.APPLICATIONS_OPEN,
            "phase_label": phase.value.replace("_", " ").title(),
        }, 200

    return {
        "application_form": None,
        "phase": phase.value,
        "is_open": phase == MarketPhase.APPLICATIONS_OPEN,
        "phase_label": phase.value.replace("_", " ").title(),
    }, 200


# ── internal helpers ────────────────────────────────────────────────────────


def _application_response(app: Application) -> Dict[str, Any]:
    """Return a camelCase dictionary for the front-end."""
    return {
        "id": app.id,
        "marketId": app.market_id,
        "applicantEmail": app.applicant_email,
        "formData": app.form_data,
        "status": app.status.value,
        "applicationType": app.application_type.value,
        "mainApplicationId": app.main_application_id,
        "submittedAt": app.submitted_at,
        "updatedAt": app.updated_at,
    }


def authenticate_request(authorization_header: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse the ``Authorization: Bearer <token>`` header and return the payload.

    Called by the route handlers to authenticate applicant requests.

    Args:
        authorization_header: The raw ``Authorization`` header value.

    Returns:
        Decoded token payload dict or None if invalid.
    """
    if not authorization_header:
        return None
    parts = authorization_header.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return verify_application_token(parts[1])
