"""The key that every session cookie and every applicant token in this product is signed with.

A signing secret with a fallback is not a secret. The fallback that used to live here was a literal
committed to this repository, so on any deployment that forgot ``SECRET_KEY`` the key protecting the
product was a string anyone could read off the source: an applicant token carrying any
``{application_id, market_id, email}`` could be minted at will and spent against the public
applicant endpoints, walking past the one-time code, the captcha, and every rate limit in front of
them, and the organizer's Flask session cookie was signed with the same string.

So there is no fallback. ``SECRET_KEY`` is required, it is checked at boot alongside the other
public-endpoint defenses, and the refusal names the variable -- the same shape as the reCAPTCHA
secret and the trusted-hop count, and for the same reason: a security control keyed on a variable
whose default is the insecure value is not a control.

The local-development escape hatch (see ``utils.deployment``) does not restore a fallback either. It
mints a *random* secret for the life of the process, which is the part that matters: a value nobody
can predict cannot be forged against, and a value that changes every boot cannot quietly become the
key a deployment ships with. The cost is that a restart invalidates the sessions and applicant tokens
that process issued, which is the correct price for a machine that has declined to configure a key.
"""

import logging
import os
import secrets

from utils.deployment import (
    INSECURE_LOCAL_DEV_VAR,
    insecure_local_dev,
    warn_insecure_local_dev,
)

logger = logging.getLogger(__name__)

SECRET_KEY_VAR = "SECRET_KEY"

_ephemeral_secret = None


class SecretKeyNotConfiguredError(RuntimeError):
    """There is no signing secret, so every token this process issued would be forgeable."""


def signing_secret() -> str:
    """The secret this process signs session cookies and applicant tokens with.

    Raises:
        SecretKeyNotConfiguredError: when no secret is configured and this is not an opted-in
            local development process.
    """
    configured = os.getenv(SECRET_KEY_VAR, "").strip()
    if configured:
        return configured

    if insecure_local_dev():
        return _ephemeral_dev_secret()

    raise SecretKeyNotConfiguredError(
        f"{SECRET_KEY_VAR} is not set. It signs the Flask session cookie and the application-scoped "
        f"tokens the public applicant endpoints authenticate with, so a process without one has no "
        f"way to tell a token it issued from a token an attacker wrote -- and a token an attacker "
        f"wrote reads and overwrites any applicant's application, past the one-time code, the "
        f"captcha, and every rate limit. There is deliberately no default: a fallback secret in a "
        f"repository is a published key. Set {SECRET_KEY_VAR} to a long random string (for example "
        f"`python -c 'import secrets; print(secrets.token_urlsafe(48))'`), or set "
        f"{INSECURE_LOCAL_DEV_VAR}=true if this really is a local development machine."
    )


def assert_signing_secret_configured() -> None:
    """Refuse to boot without a signing secret. Called from the public-endpoint defense check."""
    signing_secret()


def _ephemeral_dev_secret() -> str:
    """A random secret for this process only, so an unconfigured dev machine still has a real key.

    Cached, because a key regenerated per call would invalidate the token it signed a moment ago.
    """
    global _ephemeral_secret
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(48)
        warn_insecure_local_dev(f"a configured signing secret ({SECRET_KEY_VAR})")
        logger.warning(
            "Signing with a random secret generated for this process. Sessions and applicant "
            "tokens will not survive a restart. Set %s to keep them across restarts.",
            SECRET_KEY_VAR,
        )
    return _ephemeral_secret
