"""The one switch that lets this process run without what its public endpoints need.

The signup, verification, password-reset and OTP endpoints are unauthenticated, they write to the
database, and they send mail from the product's domain. Four pieces of configuration are what keep
this app's public surface from being an open relay - or, in the last case, from being a locked door
- and ``check_public_endpoint_defenses`` (``app.py``) requires all four:

- ``RECAPTCHA_SECRET_KEY``, the gate that keeps a script off the public signup endpoint.
- ``SECRET_KEY``, which signs the organizer's session cookie, and so is what makes a session mean
  anything at all.
- ``CORS_ALLOWED_ORIGINS``, the list of browser origins allowed to send that session cookie to the
  organizer API.
- ``RESEND_API_KEY``, which delivers the verification link, the password-reset link, and the OTP -
  every route by which an organizer account is reached.

Three of them fail *silently* when unset: the captcha passes every caller, a session signed with a
published key is a session anyone can forge, and a credentialed CORS policy with no origin list
reflects whatever ``Origin`` the caller sent. The mail key fails the opposite way and belongs here
for that reason - unset, it fails every registration, reset and OTP with a 500 naming nothing, which
is a variable an operator would otherwise have to find one broken signup at a time.

So none of them may be optional by default. Gating those checks on ``FLASK_ENV == "production"``
was the shape of the bug rather than the fix: the repo's own image sets ``FLASK_ENV=development``
and nothing overrides it, so a deployment built from that image was exempt from every one of them
and said nothing about it. A security control gated on a variable whose default is the insecure
value is not a control.

It is inverted here. The checks hold for every process, and it is the *escape hatch* that has to be
asked for: a developer running the stack on a laptop sets ``ALLOW_INSECURE_LOCAL_DEV`` and gets a
warning naming everything it turns off. A deployment that forgets to set the four variables does
not boot at all, which is the only way an unconfigured deployment can be made impossible rather
than merely discouraged. The same four are listed in ``docs/RELEASING.md`` and ``.env.example``;
keep those in step with the check, because a deploy checklist that is wrong is worse than one that
is absent - it will be trusted.
"""

import logging
import os

logger = logging.getLogger(__name__)

INSECURE_LOCAL_DEV_VAR = "ALLOW_INSECURE_LOCAL_DEV"

_TRUTHY = ("true", "1")


def insecure_local_dev() -> bool:
    """Whether this process has been told, explicitly, that it is a local development one."""
    return os.getenv(INSECURE_LOCAL_DEV_VAR, "").strip().lower() in _TRUTHY


def warn_insecure_local_dev(defense: str) -> None:
    """Name the defense that is off and the variable that turned it off, every time it is skipped."""
    logger.warning(
        "%s is off because %s is set. That is a local-development escape hatch: the public signup, "
        "verification, password-reset and OTP endpoints are unauthenticated, they write to the "
        "database, and they send mail from this domain. Never set %s on a deployed environment.",
        defense, INSECURE_LOCAL_DEV_VAR, INSECURE_LOCAL_DEV_VAR,
    )
