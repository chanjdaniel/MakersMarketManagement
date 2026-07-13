"""Applicant-facing endpoints for the public application flow.

This module serves public routes for the applicant email-key login flow and
application management. Every route is authentication-free -- the applicant is
identified by a short-lived application-scoped JWT once they verify their email key.

Storage contract: application documents are persisted through ``api.applications``
(the single owner of the ``applications`` collection) so the D9 form lock, which
counts documents in that same collection by ``market_id``, sees them immediately.

The login challenge -- the emailed code and the attempts spent against it -- is *not* stored on the
application. It is a document of its own, keyed by (market, email), in a collection this module
owns. That is a security boundary, not a filing preference: a challenge that lived on the
application could only exist where an application does, so every refusal that reads it would answer
"this address has applied" to anyone who asked. See ``_challenge_for``.
"""

import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from pymongo.errors import PyMongoError

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
from market_documents import (
    market_doc_field,
    market_doc_filter,
    market_name_slug,
    published_market_by_slug,
)
import api.applications as ApplicationsApi

db = get_database()
markets_collection = db["markets"]
login_codes_collection = db["applicant_login_codes"]
from utils.tokens import generate_otp
from utils.email import send_otp_email
from utils.application_token import generate_application_token, verify_application_token
from utils.captcha import verify_recaptcha
from utils.rate_limit import rate_limit_exceeded

logger = logging.getLogger(__name__)

MAX_OTP_ATTEMPTS = 5
OTP_EXPIRY_MINUTES = 5

# The shortest interval between two codes for the same address. This endpoint is public and
# unauthenticated, and it sends mail to whatever address it is handed, so without a floor it is an
# email relay anyone can point at anyone.
KEY_RESEND_COOLDOWN_SECONDS = 60

# What bounds this surface *across* addresses, which the per-address cooldown cannot: it is keyed on
# the address, so a caller that names a thousand of them is throttled by it a thousand times over,
# which is to say not at all. Unbounded, that caller sends a thousand pieces of mail from the
# product's domain and puts a thousand empty applications on the organizer's list -- which also
# trips the D9 form lock, freezing a form the organizer is still writing. The captcha is what stops
# a script from being one of those callers; the per-IP budget is what bounds the ones that get past
# it; the global budget is the ceiling on how much mail the product will send in an hour, whoever
# asks for it, because domain reputation is a single shared resource.
#
# The budgets are generous on purpose: applicants share IPs (a convention hall's wifi is one
# address), so a limit tight enough to be interesting to an attacker who has already solved a
# captcha would lock a room full of vendors out of their own applications.
REQUEST_KEY_IP_LIMIT = 20
REQUEST_KEY_IP_WINDOW_SECONDS = 3600
REQUEST_KEY_GLOBAL_LIMIT = 1000
REQUEST_KEY_GLOBAL_WINDOW_SECONDS = 3600

# Guessing is bounded per code by ``MAX_OTP_ATTEMPTS`` and per address by the resend cooldown, and
# this is what bounds it per *caller*: without it a script cycles request + guess + request against
# one address for as long as it likes.
VERIFY_KEY_IP_LIMIT = 60
VERIFY_KEY_IP_WINDOW_SECONDS = 3600

RATE_LIMITED_ERROR = (
    "Too many requests from this location. Please wait a few minutes and try again."
)

CAPTCHA_REQUIRED_ERROR = (
    "We could not verify that this request came from a browser. Please reload the page and "
    "try again."
)

# A number answer is stored in a BSON document, and BSON integers are 64-bit. A finite float such
# as ``1e300`` is a number by every test above this bound and still cannot be written: the driver
# raises at encode time, long after validation said yes, and the applicant gets a 500 where the
# form should have said no. The range is the storage's, so the refusal is the validator's.
INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1

# An answer is a form response, not a payload channel. Without a bound, every declared text key is
# an unbounded write into the applications collection: the app-wide 50 MB body limit is the only
# ceiling, and a document that grows past Mongo's 16 MB fails the write with a 500.
MAX_TEXT_LENGTH = 5000

TEXT_FIELD_TYPES = ("text", "email", "date")

# The login email is the application's primary key, so it is held to the same shape as a declared
# ``email`` answer: one rule, one place, so the address an applicant signs in with cannot be one the
# form itself would refuse.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# The states of a review the organizer has not finished delivering. A reviewer recording a verdict
# is not the organizer sending it, and until the organizer acts outward - which as of this build is
# ``assignment_sent`` - the applicant is told only that the application is under review.
#
# This has to be enforced here, on the way out of the process, because anything the applicant's
# browser receives, the applicant can read: a client-side label mapped over a payload that carries
# ``reviewer_rejected`` still ships the rejection in the response body and into the page markup.
# There is no applicant-facing payload that does not pass through ``_application_response``, so this
# is the one place that decides, and nothing downstream of it may reintroduce the raw value.
REVIEW_IN_PROGRESS_STATUSES = frozenset({
    ApplicationStatus.UNDER_REVIEW,
    ApplicationStatus.REVIEWER_APPROVED,
    ApplicationStatus.REVIEWER_REJECTED,
    ApplicationStatus.UNASSIGNED,
    ApplicationStatus.ASSIGNED,
})

# One response for "there is no pending code", whatever the reason. Whether an application exists
# for an address is the organizer's private data, so a public endpoint cannot answer it - and a
# refusal that names a missing application answers it to anyone who asks. A missing application and
# an application whose code has expired or was already spent are indistinguishable from here on out.
NO_PENDING_CODE_ERROR = (
    "There is no pending verification code for this email address. It may have expired, or the "
    "address may not be the one you requested a code for. Please request a new code."
)

# The one answer ``request_applicant_key`` gives once the market resolves: a code was sent if there
# was an application to send it for, and the caller cannot tell which happened.
KEY_REQUEST_ACCEPTED_MESSAGE = (
    "If an application exists for this email, a verification code has been sent."
)

# A code whose attempt budget is spent is dead. Requesting another one is what fixes that -- the new
# code carries its own budget -- so that is what the applicant is told to do, and it is advice that
# works: the only wait is the resend cooldown.
ATTEMPTS_EXHAUSTED_ERROR = (
    "Too many incorrect attempts. This code is no longer usable. Please request a new code."
)

# ── slug helpers ───────────────────────────────────────────────────────────


def _get_market_doc_by_slug(market_slug: str) -> Optional[Dict[str, Any]]:
    """Find the published market whose slugified name matches the given slug."""
    return published_market_by_slug(markets_collection, market_slug)


def _get_market_phase(doc: Dict[str, Any]) -> MarketPhase:
    """Get the effective phase of a market document."""
    return phase_from_market_document(doc)


def _market_for_applicant(
    market_slug: str, token_payload: Dict[str, Any],
) -> Tuple[Optional[Tuple[Dict[str, Any], int]], Optional[Dict[str, Any]]]:
    """The market this request acts on, refused unless the token was issued for that same market.

    An applicant session is scoped to one market, because an application is: the token carries the
    market it was minted for, and every applicant route names the market it acts on. Resolving the
    target from the token alone lets a session for one market act on another - the applicant fills
    in market B's form, the write lands on market A's application, and where the two forms share a
    field key (``business_name``, ``email``) it silently overwrites a submitted application with
    another market's answers. So the route names the market and the server is the authority that the
    two agree; the front-end guard only keeps the UI from inviting the action.

    The market is loaded by the token's ``market_id`` rather than by slug, because the slug lookup
    only sees published markets and this has to answer for the market the applicant is actually
    signed in to whatever phase it has since moved to - that is the phase gate's question to answer,
    with the phase named, not this one's to hide behind a 404.

    Returns ``(refusal, None)`` or ``(None, market_doc)``.

    Anti-F6: the refusal says the session is for a different market, not merely "forbidden".
    """
    if not market_slug or not market_slug.strip():
        return ({"error": "Market identifier is required."}, 400), None

    market_id = token_payload.get("market_id", "")
    market_doc = markets_collection.find_one(market_doc_filter("id", market_id))
    if not market_doc:
        return ({"error": "Market not found."}, 404), None

    if market_name_slug(market_doc.get("name", "")) != market_slug.strip().lower():
        return ({
            "error": "You are signed in for a different market. "
                     "Please sign in again to work on this market's application.",
        }, 403), None

    return None, market_doc


# ── application helpers ─────────────────────────────────────────────────────


def _normalized_email(value: Any) -> Tuple[Optional[Tuple[Dict[str, Any], int]], str]:
    """The address an applicant is identified by, refused unless it is one.

    The login email is the application's primary key, and it is the one email this module used not
    to check: an address the form itself would refuse as an answer was accepted as the identity the
    answers are filed under. A typo then persists an application nobody can sign in to, tells the
    applicant a code is on the way, and leaves a document with an unreachable address on the
    organizer's applicant list.

    Returns ``(refusal, "")`` or ``(None, email)``.

    Anti-F6: the refusal quotes the address back and says it is the address that is wrong.
    """
    if not isinstance(value, str) or not value.strip():
        return ({"error": "Email address is required."}, 400), ""

    email = value.strip().lower()
    if not EMAIL_PATTERN.match(email):
        return ({
            "error": f'"{email}" is not a valid email address. Check it and try again.',
        }, 400), ""

    return None, email


def _find_application(market_id: str, email: str) -> Optional[Application]:
    """The existing main application for this market + email, if there is one."""
    existing = ApplicationsApi.applications_collection.find_one({
        ApplicationsApi.MARKET_ID_FIELD: market_id,
        "applicant_email": email,
        "application_type": ApplicationType.MAIN.value,
    })
    return Application(**existing) if existing else None


_login_code_indexes_ready = False


def _ensure_login_code_indexes() -> None:
    """The two invariants of the challenge store, enforced where they can actually hold.

    The address is the key, and the store is written by an upsert on a public endpoint, so the
    uniqueness has to be the database's: two concurrent requests for the same address would
    otherwise both find no document and both insert one, leaving an address with two live codes and
    two attempt budgets - which is a doubled guess budget for anyone who asks for two codes at once.

    The TTL is what keeps the collection from growing for as long as the product runs: a challenge
    is dead the moment it expires, and a dead one is of no use to anybody.

    Built lazily rather than at import: an index build is a network call, and this module is
    imported by tooling and tests that never reach the database.
    """
    global _login_code_indexes_ready
    if _login_code_indexes_ready:
        return
    try:
        login_codes_collection.create_index(
            [("market_id", 1), ("email", 1)], unique=True, name="market_email_unique",
        )
        login_codes_collection.create_index("purge_at", expireAfterSeconds=0)
        _login_code_indexes_ready = True
    except PyMongoError as exc:  # pragma: no cover - index creation is best effort
        logger.warning("Could not create the applicant login-code indexes: %s", exc)


def _as_utc(value: Any) -> Optional[datetime]:
    """A stored timestamp as an aware UTC datetime. Mongo hands back naive ones."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _challenge_for(market_id: str, email: str) -> Optional[Dict[str, Any]]:
    """The live login challenge for this address, or ``None`` if there is not one.

    A challenge exists for any address that has asked for a code, whether or not an application
    exists for it. That is the whole point of it being its own document: an attempt counter that
    lived on the application would be present for an applicant and absent for a stranger, and every
    refusal that reads it -- "incorrect code, 4 attempts remaining" against "there is no pending
    code" -- would then answer, to an unauthenticated caller, which addresses are on the organizer's
    applicant list.

    An expired challenge is not a live one, so it is not returned: a dead code and no code at all
    are the same state, and this is where they become it.
    """
    doc = login_codes_collection.find_one({"market_id": market_id, "email": email})
    if not doc:
        return None
    expires_at = _as_utc(doc.get("expires_at"))
    if not expires_at or expires_at <= datetime.now(timezone.utc):
        return None
    return doc


def _issue_challenge(market_id: str, email: str, code: Optional[str]) -> None:
    """Replace this address's challenge with a fresh one, carrying a fresh attempt budget.

    The budget belongs to the code, not to the address. Carrying a spent budget forward onto a new
    code hands anyone who knows an applicant's address a way to lock them out of their own
    application: burn the five attempts the moment the code is mailed, and every code the applicant
    asks for after that is born dead. Resetting is safe because the new code goes to the applicant's
    inbox, not to the caller's -- what bounds guessing is the code's entropy, the per-code attempt
    cap, the resend cooldown, and the per-IP budgets, none of which a reset touches.

    ``code`` is ``None`` when there is no application to mail a code to. The challenge is still
    written, and it still counts attempts, so that a caller cannot tell the two apart: no string a
    caller submits equals ``None``, so such a challenge simply refuses every guess, exactly as a
    real one refuses a wrong guess.
    """
    _ensure_login_code_indexes()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=OTP_EXPIRY_MINUTES)
    login_codes_collection.update_one(
        {"market_id": market_id, "email": email},
        {"$set": {
            "market_id": market_id,
            "email": email,
            "code": code,
            "attempts": 0,
            "issued_at": now,
            "expires_at": expires_at,
            "purge_at": expires_at,
        }},
        upsert=True,
    )


def _spend_challenge_attempt(market_id: str, email: str) -> None:
    login_codes_collection.update_one(
        {"market_id": market_id, "email": email},
        {"$inc": {"attempts": 1}},
    )


def _clear_challenge(market_id: str, email: str) -> None:
    login_codes_collection.delete_one({"market_id": market_id, "email": email})


def _create_application(market_id: str, email: str) -> Application:
    """Start a new main application for this market + email."""
    app = Application(
        market_id=market_id,
        applicant_email=email,
        form_data={},
        status=ApplicationStatus.OPEN,
        application_type=ApplicationType.MAIN,
    )
    ApplicationsApi.applications_collection.insert_one(app.model_dump())
    return app


def _is_answered(value: Any, field_type: str) -> bool:
    """Whether a submitted value counts as an answer for a field of this type.

    "Present in the payload" is not the same as "answered", and the difference is type-shaped:
    an unticked mandatory consent checkbox arrives as ``False`` and an untouched mandatory
    multi_select as ``[]``, both of which are non-null, non-empty-string values that a purely
    null/blank test waves through. This is the one place that decides the question, so a required
    field cannot be satisfied by a value that means "the applicant did not answer".
    """
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, list):
        return len(value) > 0
    if field_type == "checkbox":
        return value is True
    return True


class NumberOutOfRange(ValueError):
    """A finite number that no BSON document can hold. See ``INT64_MIN``/``INT64_MAX``."""


def _as_number(value: Any) -> Any:
    """The numeric value of an answer to a ``number`` field. Raises if it is not one.

    The applicant's browser sends every input as text, so a ``number`` field arrives as ``"3"``.
    Accepting that and storing it verbatim persists a field the form declares as a number under a
    string, and every later reader - the reviewer UI, an export, the application-to-solver adapter
    - inherits it: a compare or a sort on it is silently lexicographic. A bool is rejected rather
    than folded to 1/0, and a non-finite float is rejected because it is not a value a document
    can hold. Magnitude is the same question as finiteness: a number outside the 64-bit range is
    also not a value a document can hold, and this is the last place that can say so before the
    driver does, at encode time, as a 500.
    """
    if isinstance(value, bool):
        raise TypeError("a boolean is not a number")

    # An integer answer is parsed as one, not by way of a float: ``float("9223372036854775807")``
    # is 2**63, so a round-trip through a float refuses the largest number that does fit and would
    # store the one that does not.
    if isinstance(value, int):
        number: Any = value
    elif isinstance(value, str):
        text = value.strip()
        try:
            number = int(text)
        except ValueError:
            number = float(text)
    else:
        number = float(value)

    if isinstance(number, float):
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError("not a finite number")
    if not INT64_MIN <= number <= INT64_MAX:
        raise NumberOutOfRange("outside the storable range")
    if isinstance(number, float) and number.is_integer():
        return int(number)
    return number


def _unanswered_value(field_type: str) -> Any:
    """What an unanswered field of this type stores.

    An unanswered value is still a stored value, so it is the field's own empty one rather than
    whatever the request happened to carry. Echoing the incoming value back into the document is
    the same hole as not checking an answered one: a text field handed ``[]`` reads as unanswered
    and would store a list under a key the form declares as text. A number has no empty scalar,
    so it stores nothing at all -- ``""`` is not a number.
    """
    if field_type == "number":
        return None
    if field_type == "checkbox":
        return False
    if field_type == "multi_select":
        return []
    return ""


def _checked_value(field: Dict[str, Any], value: Any) -> Tuple[Optional[str], Any]:
    """Check one answered value against its field, and return the value as it should be stored.

    Every field type the builder can produce must validate -- no per-field special-casing -- and
    every one of them constrains the *type* of what it accepts, not just its shape when it happens
    to arrive as the expected one. A branch that checks a value only ``if isinstance(value, str)``
    is not a check: everything that is not a string falls straight through it and is stored
    verbatim, so a field the form declares as text can hold an arbitrary nested object, and every
    later reader - the reviewer UI, an export, the application-to-solver adapter - inherits a value
    whose type contradicts the form. Anything this build cannot validate it refuses rather than
    stores, because storing an unvalidated value is the thing this function exists to prevent.
    """
    label = field.get("label", field.get("key", ""))
    ft = field.get("type", "text")

    if ft in TEXT_FIELD_TYPES:
        if not isinstance(value, str):
            return f'"{label}" must be text.', None
        if len(value) > MAX_TEXT_LENGTH:
            return (
                f'"{label}" is too long. It must be at most {MAX_TEXT_LENGTH} characters.',
                None,
            )
        if ft == "email" and not EMAIL_PATTERN.match(value.strip()):
            return f'"{label}" must be a valid email address.', None
        if ft == "date":
            # The check is the format the refusal promises, not merely one ``fromisoformat`` can
            # parse: that accepts "20240101" and a full datetime too, so the value stored under a
            # key the form declares as a date would be neither, and a compare across the mixed
            # forms it lets through is lexicographic and wrong. The canonical date is stored so
            # every later reader gets the one shape.
            try:
                parsed = datetime.strptime(value.strip(), "%Y-%m-%d")
            except ValueError:
                return f'"{label}" must be a valid date (YYYY-MM-DD).', None
            return None, parsed.date().isoformat()
    elif ft == "number":
        try:
            return None, _as_number(value)
        except NumberOutOfRange:
            return (
                f'"{label}" is too large. It must be between {INT64_MIN} and {INT64_MAX}.',
                None,
            )
        except (ValueError, TypeError, OverflowError):
            return f'"{label}" must be a number.', None
    elif ft == "select":
        if value not in field.get("options", []):
            return f'"{label}" has an invalid selection.', None
    elif ft == "multi_select":
        options = field.get("options", [])
        if not isinstance(value, list):
            return f'"{label}" must be a list of selections.', None
        seen = []
        for v in value:
            if v not in options:
                return f'"{label}" contains an invalid selection: "{v}".', None
            # Selecting one option twice is not an answer the form can express, and without this
            # the list is bounded only by the request body: the same valid option, a million times.
            if v in seen:
                return f'"{label}" repeats the selection "{v}".', None
            seen.append(v)
    elif ft == "checkbox":
        if not isinstance(value, bool):
            return f'"{label}" must be true or false.', None
    else:
        return (
            f'"{label}" has a field type this application cannot accept ({ft}). '
            f'Contact the market organizer.',
            None,
        )

    return None, value


def _validated_form_data(
    form_data: Dict[str, Any], fields: list,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Validate the submitted answers against the market's form, and return what to store.

    Validating and projecting are one pass over the declared fields, so the document that is
    stored is exactly the one that was checked. Two passes could disagree, and both ways of
    disagreeing are bugs that have already been written here: a key the form never declared is
    never validated, and storing it anyway lets an applicant write arbitrary keys of arbitrary
    size into the applications collection; and a value that is checked as a number but stored as
    the string it arrived as is a field whose stored type contradicts the form. A market with no
    form declares no fields and therefore stores no answers.

    Returns ``(error_message, {})`` on the first field that fails, ``(None, stored)`` otherwise.

    Anti-F6: the error names the offending field and what is wrong with it.
    """
    stored: Dict[str, Any] = {}
    for field in fields:
        key = field.get("key", "")
        label = field.get("label", key)
        ft = field.get("type", "text")
        value = form_data.get(key)
        answered = _is_answered(value, ft)

        if field.get("required", False) and not answered:
            return f'"{label}" is required.', {}

        if key not in form_data:
            continue

        if not answered:
            stored[key] = _unanswered_value(ft)
            continue

        error, checked = _checked_value(field, value)
        if error:
            return error, {}
        stored[key] = checked

    return None, stored


# ── public endpoints ────────────────────────────────────────────────────────


def request_applicant_key(
    market_slug: str,
    email: str,
    captcha_token: str = "",
    client_ip: Optional[str] = None,
) -> Tuple[Dict[str, Any], int]:
    """Stage 1 of the applicant login flow: send a one-time key to the applicant's email.

    Signing in is not applying, so the phase does not gate it. An applicant can reach their own
    application in every phase the market ever moves to: the states the dashboard exists to show
    them - under review, and later the organizer's decision - are reachable only *after*
    applications close, so a login gated on ``applications_open`` would lock every applicant out of
    the dashboard exactly when it has something to say. The token is 30 minutes and in-memory, so
    "already signed in" is not a way back in either.

    What the phase does gate is *starting* an application: a market that is not open takes no new
    ones, and creating a document for an address that never applied would put a stranger with an
    empty form on the organizer's applicant list after review has begun. That refusal is silent - a
    challenge is still written for the address, holding no code, so that nothing downstream of here
    can tell a stranger from an applicant either.

    Returns the same generic message in every phase, whether or not an application was found. Who
    applied to a market is the organizer's private data, so this endpoint cannot answer it: naming
    the phase gate only when no application exists turns the refusal into an oracle, answering 200
    for an address that applied and 403 for one that did not. The market's phase is public (the
    application page reads it from ``get_public_application_form`` and says so on screen); *which
    addresses are on its applicant list* is not, and only this endpoint knows that.

    The bounds on the surface come in three layers, and each one answers something the others
    cannot. The captcha keeps a script from being a caller at all - it is the same reCAPTCHA gate
    ``register_user_with_captcha`` puts on the organizer-side signup, because this is the same kind
    of surface. The per-IP and global budgets bound what a caller that got past it can spend, across
    *all* addresses: the resend cooldown below is keyed on one address, so it does nothing about a
    caller that names a thousand of them, and a thousand of them is a thousand pieces of mail from
    the product's domain and a thousand empty applications on the organizer's list. And the resend
    cooldown holds the mail to one message per address per minute.

    The cooldown is the one refusal that answers with the accepted message rather than a 429,
    because it is the only one keyed on the *address*: only an address with a live code can be
    cooled down, so a distinguishable refusal there is the applicant-list oracle again, through a
    side door. The captcha and rate-limit refusals are keyed on the caller, know nothing about the
    address, and so can say plainly what is wrong.

    Args:
        market_slug: The URL-safe slug of the market.
        email: The applicant's email address.
        captcha_token: The reCAPTCHA token the browser obtained for this action.
        client_ip: The caller's IP, for the per-IP budget and for the captcha's own scoring.

    Returns:
        Tuple of (response_body, status_code).

    Anti-F6: refusal messages name the exact problem.
    """
    if not market_slug or not market_slug.strip():
        return {"error": "Market identifier is required."}, 400

    refusal, email = _normalized_email(email)
    if refusal:
        return refusal

    if rate_limit_exceeded(
        "applicant_request_key_ip",
        client_ip or "unknown",
        limit=REQUEST_KEY_IP_LIMIT,
        window_seconds=REQUEST_KEY_IP_WINDOW_SECONDS,
    ):
        return {"error": RATE_LIMITED_ERROR}, 429

    if rate_limit_exceeded(
        "applicant_request_key_global",
        "",
        limit=REQUEST_KEY_GLOBAL_LIMIT,
        window_seconds=REQUEST_KEY_GLOBAL_WINDOW_SECONDS,
    ):
        return {"error": RATE_LIMITED_ERROR}, 429

    captcha_ok, _score = verify_recaptcha(captcha_token, client_ip)
    if not captcha_ok:
        return {"error": CAPTCHA_REQUIRED_ERROR}, 400

    market_doc = _get_market_doc_by_slug(market_slug)
    if not market_doc:
        return {"error": "Market not found. Check the URL and try again."}, 404

    market_id = market_doc.get("id", "")
    phase = _get_market_phase(market_doc)

    app = _find_application(market_id, email)
    if not app and phase == MarketPhase.APPLICATIONS_OPEN:
        app = _create_application(market_id, email)

    challenge = _challenge_for(market_id, email)
    if challenge is not None:
        issued_at = _as_utc(challenge.get("issued_at"))
        if issued_at is not None and datetime.now(timezone.utc) - issued_at < timedelta(
            seconds=KEY_RESEND_COOLDOWN_SECONDS
        ):
            return {"message": KEY_REQUEST_ACCEPTED_MESSAGE}, 200

    # A stranger's challenge holds no code, so no guess can ever match it, and no mail is sent for
    # it. It is still written, and it still counts attempts, because the challenge is the only thing
    # ``verify_applicant_key`` reads: an address with no challenge document would be answered
    # differently from one with a live code, and that difference is the applicant list.
    otp = generate_otp() if app else None
    _issue_challenge(market_id, email, otp)

    if otp:
        send_otp_email(email, otp)

    return {"message": KEY_REQUEST_ACCEPTED_MESSAGE}, 200


def verify_applicant_key(
    market_slug: str, email: str, key: str, client_ip: Optional[str] = None,
) -> Tuple[Dict[str, Any], int]:
    """Stage 2 of the applicant login flow: verify the one-time key.

    On success returns a short-lived application-scoped JWT + application data.

    Every refusal names exactly what is wrong - except that none of them may reveal whether an
    application exists for the address, and here that is not a matter of wording. It is why the
    challenge this reads is a document of its own rather than a field on the application: the
    endpoint never looks the address up on the applicant list at all, so it has nothing to leak.
    Whether the caller named an applicant or a stranger, ``request_applicant_key`` left a challenge
    behind, and the sequence of answers it gives - "incorrect code, 4 attempts remaining", then 3,
    then the 429 - is the same one, with the same statuses and the same bodies, either way.

    The application is loaded only once the code has already been proven correct, which a stranger's
    challenge - which holds no code - can never be.

    Args:
        market_slug: The URL-safe slug of the market.
        email: The applicant's email address.
        key: The 6-digit verification code.
        client_ip: The caller's IP, for the per-IP guess budget.

    Returns:
        Tuple of (response_body, status_code).

    Anti-F6: every refusal names exactly what is wrong and what to do.
    """
    if not market_slug or not market_slug.strip():
        return {"error": "Market identifier is required."}, 400

    refusal, email = _normalized_email(email)
    if refusal:
        return refusal

    if not key or not key.strip():
        return {"error": "Verification code is required."}, 400

    key = key.strip()

    if rate_limit_exceeded(
        "applicant_verify_key_ip",
        client_ip or "unknown",
        limit=VERIFY_KEY_IP_LIMIT,
        window_seconds=VERIFY_KEY_IP_WINDOW_SECONDS,
    ):
        return {"error": RATE_LIMITED_ERROR}, 429

    market_doc = _get_market_doc_by_slug(market_slug)
    if not market_doc:
        return {"error": "Market not found. Check the URL and try again."}, 404

    market_id = market_doc.get("id", "")

    challenge = _challenge_for(market_id, email)
    if challenge is None:
        return {"error": NO_PENDING_CODE_ERROR}, 401

    attempts = challenge.get("attempts", 0)
    if attempts >= MAX_OTP_ATTEMPTS:
        return {"error": ATTEMPTS_EXHAUSTED_ERROR}, 429

    # A challenge with no code refuses every guess, which is exactly what a challenge with a code
    # does to a wrong one. The comparison is the same comparison; there is no branch here that a
    # stranger takes and an applicant does not.
    if challenge.get("code") != key:
        _spend_challenge_attempt(market_id, email)
        remaining = MAX_OTP_ATTEMPTS - (attempts + 1)
        if remaining <= 0:
            return {"error": ATTEMPTS_EXHAUSTED_ERROR}, 429
        return {
            "error": f"Incorrect code. You have {remaining} attempt{'s' if remaining != 1 else ''} remaining.",
        }, 401

    app = _find_application(market_id, email)
    if not app:
        # Unreachable by guessing: a challenge only carries a code when an application existed to
        # mail it to. It is reachable if that application was deleted in the meantime, and the
        # answer is the one every other dead end gives.
        _clear_challenge(market_id, email)
        return {"error": NO_PENDING_CODE_ERROR}, 401

    token = generate_application_token(app.id, market_id, email)
    _clear_challenge(market_id, email)

    return {
        "token": token,
        "application": _application_response(app),
    }, 200


def get_applicant_application(
    market_slug: str, token_payload: Dict[str, Any],
) -> Tuple[Dict[str, Any], int]:
    """Return the authenticated applicant's application data for this market.

    Args:
        market_slug: The URL-safe slug of the market the request is acting on.
        token_payload: Decoded JWT payload from ``verify_application_token``.

    Returns:
        Tuple of (response_body, status_code).
    """
    refusal, _ = _market_for_applicant(market_slug, token_payload)
    if refusal:
        return refusal

    app_id = token_payload.get("application_id", "")
    app_doc = ApplicationsApi.applications_collection.find_one({"id": app_id})
    if not app_doc:
        return {"error": "Application not found."}, 404

    app = Application(**app_doc)
    return {"application": _application_response(app)}, 200


def save_applicant_application(
    market_slug: str, token_payload: Dict[str, Any], form_data: Dict[str, Any],
) -> Tuple[Dict[str, Any], int]:
    """Save or update the authenticated applicant's application for this market.

    Validates the form data against the market's application form fields.
    Refuses submission when the market is not in ``applications_open``, and refuses a session
    that was issued for a different market.

    Args:
        market_slug: The URL-safe slug of the market the request is acting on.
        token_payload: Decoded JWT payload from ``verify_application_token``.
        form_data: The form answers keyed by field keys.

    Returns:
        Tuple of (response_body, status_code).

    Anti-F6: validation errors name the specific field and problem.
    """
    if not isinstance(form_data, dict):
        return {"error": "Form answers must be an object keyed by field key."}, 400

    refusal, market_doc = _market_for_applicant(market_slug, token_payload)
    if refusal:
        return refusal

    app_id = token_payload.get("application_id", "")
    app_doc = ApplicationsApi.applications_collection.find_one({"id": app_id})
    if not app_doc:
        return {"error": "Application not found."}, 404

    phase = phase_from_market_document(market_doc)
    if phase != MarketPhase.APPLICATIONS_OPEN:
        phase_label = phase.value.replace("_", " ").title()
        return {
            "error": f"Applications are no longer open for this market. "
                     f"The market is in the {phase_label} phase.",
        }, 403

    # Validate form data against the application form fields
    application_form = market_doc_field(market_doc, "application_form")
    fields = (application_form or {}).get("fields") or []
    error, stored_form_data = _validated_form_data(form_data, fields)
    if error:
        return {"error": error}, 422

    now = datetime.now(timezone.utc).isoformat()
    ApplicationsApi.applications_collection.update_one(
        {"id": app_id},
        {"$set": {
            "form_data": stored_form_data,
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
    application_form = market_doc_field(market_doc, "application_form")

    form_payload = None
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
        form_payload = {"fields": fields}

    return {
        "application_form": form_payload,
        # The applicant knows the market by its name; the slug is a URL detail they never chose.
        # This is the only public endpoint that holds the market document, so it is what every
        # applicant-facing screen has to get the name from.
        "market_name": market_doc.get("name", ""),
        "phase": phase.value,
        "is_open": phase == MarketPhase.APPLICATIONS_OPEN,
        "phase_label": phase.value.replace("_", " ").title(),
    }, 200


# ── internal helpers ────────────────────────────────────────────────────────


def applicant_visible_status(status: ApplicationStatus) -> ApplicationStatus:
    """The status of an application as its applicant is allowed to know it.

    Collapses every working state of an unfinished review to ``under_review``, so that nothing the
    applicant receives distinguishes an approval from a rejection. See
    ``REVIEW_IN_PROGRESS_STATUSES``.
    """
    if status in REVIEW_IN_PROGRESS_STATUSES:
        return ApplicationStatus.UNDER_REVIEW
    return status


def _application_response(app: Application) -> Dict[str, Any]:
    """Return a camelCase dictionary for the front-end."""
    return {
        "id": app.id,
        "marketId": app.market_id,
        "applicantEmail": app.applicant_email,
        "formData": app.form_data,
        "status": applicant_visible_status(app.status).value,
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
