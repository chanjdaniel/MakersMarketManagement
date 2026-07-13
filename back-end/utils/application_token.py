"""Application-scoped JWT utility for the applicant email-key login flow.

Generates short-lived (30 min) tokens that carry the application id, market id,
and applicant email. The token is signed with the application's ``SECRET_KEY``
and verified on every applicant endpoint request. No Flask session is created.

Token payload::

    {
        "application_id": str,
        "market_id": str,
        "email": str,
        "exp": int (unix timestamp)
    }
"""
import os
import time
from typing import Optional, Dict, Any

import jwt

SECRET_KEY = os.getenv("SECRET_KEY", "TEMP_KEY_CHANGE_IN_PRODUCTION")

APPLICATION_TOKEN_EXPIRY_SECONDS = 30 * 60  # 30 minutes


def generate_application_token(
    application_id: str, market_id: str, email: str,
) -> str:
    """Generate a signed JWT for an authenticated applicant.

    Args:
        application_id: The Application document id.
        market_id: The Market id this application belongs to.
        email: The applicant's email address.

    Returns:
        A signed JWT string.
    """
    now = int(time.time())
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "market_id": market_id,
        "email": email,
        "iat": now,
        "exp": now + APPLICATION_TOKEN_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def verify_application_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode an application-scoped JWT.

    Args:
        token: The JWT string from the ``Authorization: Bearer`` header.

    Returns:
        The decoded payload dict on success, or ``None`` when the token is
        expired, malformed, or otherwise invalid.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        # exp is checked by jwt.decode, but double-check
        if "application_id" not in payload or "email" not in payload:
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
