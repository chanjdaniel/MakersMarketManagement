"""The key every session cookie in this product is signed with.

A signing secret with a fallback is not a secret. The fallback that used to live here was a literal
committed to this repository, so on any deployment that forgot ``SECRET_KEY`` the key protecting the
product was a string anyone could read off the source: a Flask session cookie naming any organizer
could be minted at will and spent against the organizer API - every market, vendor and application
that organizer can reach - with no password and no login.

So there is no fallback. ``SECRET_KEY`` is required, it is checked at boot alongside the other
public-endpoint defenses, and the refusal names the variable -- the same shape as the reCAPTCHA
secret and the origin list, and for the same reason: a security control keyed on a variable whose
default is the insecure value is not a control.

The local-development escape hatch (see ``utils.deployment``) does not restore a fallback either. It
mints a *random* secret for the life of the process, which is the part that matters: a value nobody
can predict cannot be forged against, and a value that changes every boot cannot quietly become the
key a deployment ships with. The cost is that a restart invalidates the sessions that process issued,
which is the correct price for a machine that has declined to configure a key.
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
    """The secret this process signs session cookies with.

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
        f"{SECRET_KEY_VAR} is not set. It signs the Flask session cookie the organizer API "
        f"authenticates every request with, so a process without one has no way to tell a session "
        f"it issued from a session an attacker wrote -- and a session an attacker wrote reads and "
        f"overwrites any organizer's markets, vendors and applications, with no password and no "
        f"login. There is deliberately no default: a fallback secret in a repository is a published "
        f"key. Set {SECRET_KEY_VAR} to a long random string (for example "
        f"`python -c 'import secrets; print(secrets.token_urlsafe(48))'`), or set "
        f"{INSECURE_LOCAL_DEV_VAR}=true if this really is a local development machine."
    )


def _ephemeral_dev_secret() -> str:
    """A random secret for this process only, so an unconfigured dev machine still has a real key.

    Cached, because a key regenerated per call would invalidate the token it signed a moment ago.
    """
    global _ephemeral_secret
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(48)
        warn_insecure_local_dev(f"a configured signing secret ({SECRET_KEY_VAR})")
        logger.warning(
            "Signing with a random secret generated for this process. Sessions will not survive a "
            "restart. Set %s to keep them across restarts.",
            SECRET_KEY_VAR,
        )
    return _ephemeral_secret
