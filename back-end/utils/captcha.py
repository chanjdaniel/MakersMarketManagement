"""
reCAPTCHA v3 verification utility.

The bypasses below exist so a developer can run the stack without Google credentials, and every one
of them is scoped to development. A captcha that disappears when it is not configured is not a
control: the endpoints that carry it are public, unauthenticated, and they write and send mail, so a
production deployment with no secret would serve them wide open and say nothing about it. Production
therefore refuses -- at boot, through ``assert_captcha_configured``, so the refusal names the
variable rather than arriving as a mystery 400 on an applicant's screen, and again here, so no
caller reaches a verification this process cannot actually perform.
"""

import os
import requests
from typing import Tuple, Optional

RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY")
RECAPTCHA_SECRET_KEY_VAR = "RECAPTCHA_SECRET_KEY"
RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
MIN_SCORE = 0.5  # Minimum score threshold for reCAPTCHA v3


class CaptchaNotConfiguredError(RuntimeError):
    """Production has no reCAPTCHA secret, so the captcha gate would be a no-op."""


def _is_production() -> bool:
    return os.getenv("FLASK_ENV", "") == "production"


def assert_captcha_configured() -> None:
    """Refuse to serve the captcha-gated public endpoints without a secret to verify against.

    Raises:
        CaptchaNotConfiguredError: in production when no secret is configured.
    """
    if _is_production() and not RECAPTCHA_SECRET_KEY:
        raise CaptchaNotConfiguredError(
            f"{RECAPTCHA_SECRET_KEY_VAR} is not set. The public applicant and signup endpoints are "
            f"gated on reCAPTCHA, and without a secret there is nothing to verify a token against, "
            f"so the gate would silently pass every caller -- including the scripts it exists to "
            f"keep off an endpoint that writes to the database and sends mail from this domain. "
            f"Set {RECAPTCHA_SECRET_KEY_VAR} (https://www.google.com/recaptcha/admin)."
        )


def verify_recaptcha(token: str, ip_address: Optional[str] = None) -> Tuple[bool, float]:
    """Verify reCAPTCHA v3 token.

    Args:
        token: reCAPTCHA token from frontend
        ip_address: Optional IP address of the user

    Returns:
        Tuple of (success: bool, score: float)
        - success: True if verification passed and score >= MIN_SCORE
        - score: reCAPTCHA score (0.0 to 1.0)
    """
    # Explicit test-mode bypass: DISABLE_CAPTCHA env var skips verification.
    # Only honored in non-production environments.
    if not _is_production():
        if os.getenv("DISABLE_CAPTCHA", "").lower() in ("true", "1"):
            print("Warning: DISABLE_CAPTCHA is enabled - captcha verification skipped")
            return True, 1.0

    if not RECAPTCHA_SECRET_KEY:
        if _is_production():
            # Unreachable through app.py, which refuses to boot in this state. Reached only by an
            # entrypoint that skipped that check, and an unverifiable token is not a verified one.
            print(f"Error: {RECAPTCHA_SECRET_KEY_VAR} not set in production, refusing the request")
            return False, 0.0
        # In development, allow bypass if secret key not set
        print("Warning: RECAPTCHA_SECRET_KEY not set, skipping verification")
        return True, 1.0

    if not token:
        return False, 0.0
    
    try:
        data = {
            "secret": RECAPTCHA_SECRET_KEY,
            "response": token,
        }
        
        if ip_address:
            data["remoteip"] = ip_address
        
        response = requests.post(RECAPTCHA_VERIFY_URL, data=data, timeout=5)
        result = response.json()
        
        success = result.get("success", False)
        score = result.get("score", 0.0)
        
        # Check if score meets minimum threshold
        if success and score >= MIN_SCORE:
            return True, score
        else:
            print(f"reCAPTCHA verification failed: success={success}, score={score}")
            return False, score
            
    except Exception as e:
        print(f"Error verifying reCAPTCHA: {e}")
        return False, 0.0
