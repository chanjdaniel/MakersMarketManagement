"""The one switch that lets this process run without the defenses its public endpoints need.

The applicant login endpoints are unauthenticated, they write to the database, and they send mail
from the product's domain. Four pieces of configuration are what keep this app's public surface
from being an open relay, and ``verify_public_endpoint_defenses`` (``app.py``) requires all four:

- ``RECAPTCHA_SECRET_KEY``, the gate that keeps a script off the applicant endpoints.
- ``TRUSTED_PROXY_HOPS``, the count of proxies of our own whose forwarded address the rate limits
  may believe.
- ``SECRET_KEY``, which signs the session cookie and the applicant token, and so is what makes an
  applicant token mean anything at all.
- ``CORS_ALLOWED_ORIGINS``, the list of browser origins allowed to send the organizer's session
  cookie to the API beside them.

All four fail *silently* when unset - the captcha passes every caller; the limits key on the
proxy's address, which is one shared budget for the whole world; a token signed with a published
key is a token anyone can write; and a credentialed CORS policy with no origin list reflects
whatever ``Origin`` the caller sent.

So none of them may be optional by default. Gating those checks on ``FLASK_ENV == "production"``
was the shape of the bug rather than the fix: the repo's own image sets ``FLASK_ENV=development``
and nothing overrides it, so a deployment built from that image was exempt from every one of them
and said nothing about it. A security control gated on a variable whose default is the insecure
value is not a control.

It is inverted here. The checks hold for every process, and it is the *escape hatch* that has to be
asked for: a developer running the stack on a laptop sets ``ALLOW_INSECURE_LOCAL_DEV`` and gets a
warning naming every defense it turns off. A deployment that forgets to set the four variables does
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
        "%s is off because %s is set. That is a local-development escape hatch: the public "
        "applicant endpoints are unauthenticated, they write to the database, and they send mail "
        "from this domain. Never set %s on a deployed environment.",
        defense, INSECURE_LOCAL_DEV_VAR, INSECURE_LOCAL_DEV_VAR,
    )
