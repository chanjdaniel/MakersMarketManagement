"""The identity a rate limit is keyed on: which IP this deployment may believe is the caller's.

``request.remote_addr`` is the immediate peer, which is the client only when nothing sits in front
of Flask. Behind a reverse proxy, a load balancer, or a serverless ingress it is the *proxy*, the
same address for every caller in the world -- and a per-IP budget keyed on it is not a limit on an
attacker, it is a product-wide cap that the first burst of traffic spends on everyone's behalf. A
rate limit keyed on the wrong identity is worse than no rate limit at all.

The fix is not to trust ``X-Forwarded-For``: any caller can send that header, so trusting it whole
lets an attacker mint a fresh identity per request and walk around the budget entirely. Only the
hops the deployment actually owns may be trusted, and only the deployment knows how many those are,
so it has to say: ``TRUSTED_PROXY_HOPS`` is the number of proxies of its own that a request passes
through, and ProxyFix reads exactly that many entries from the right-hand end of the header -- the
end the trusted proxies appended, which is the part a client cannot forge.

Unset is not "zero", it is "unknown", and an unknown value here silently produces one of the two
failures above. So it fails closed, at boot, naming the variable: 0 is a legitimate value and an
operator who means it can say so. The only process exempt from saying so is one that has explicitly
declared itself a local development one -- see ``utils.deployment`` for why that, and not
``FLASK_ENV``, is the escape hatch.
"""

import os

from werkzeug.middleware.proxy_fix import ProxyFix

from utils.deployment import (
    INSECURE_LOCAL_DEV_VAR,
    insecure_local_dev,
    warn_insecure_local_dev,
)

TRUSTED_PROXY_HOPS_VAR = "TRUSTED_PROXY_HOPS"


class TrustedProxyConfigError(RuntimeError):
    """The deployment has not said how many proxies of its own a request passes through."""


def trusted_proxy_hops() -> int:
    """How many proxies in front of this app are the deployment's own, and therefore trustworthy.

    Raises:
        TrustedProxyConfigError: when the value is missing on anything but an opted-in local
            development process, or when it is set to something that is not a hop count.
    """
    raw = os.getenv(TRUSTED_PROXY_HOPS_VAR, "").strip()

    if not raw:
        if not insecure_local_dev():
            raise TrustedProxyConfigError(
                f"{TRUSTED_PROXY_HOPS_VAR} is not set. It is the number of proxies of this "
                f"deployment's own that a request passes through before it reaches Flask "
                f"(a reverse proxy, load balancer, or serverless ingress each count as one). "
                f"Without it the public applicant endpoints key their rate limits on the proxy's "
                f"address rather than the caller's, which locks out every real applicant while "
                f"bounding an attacker not at all. Set it to 0 only if Flask is exposed directly, "
                f"or set {INSECURE_LOCAL_DEV_VAR}=true if this really is a local development "
                f"machine."
            )
        warn_insecure_local_dev(f"the trusted-proxy hop count ({TRUSTED_PROXY_HOPS_VAR})")
        return 0

    try:
        hops = int(raw)
    except ValueError as exc:
        raise TrustedProxyConfigError(
            f"{TRUSTED_PROXY_HOPS_VAR} must be a whole number of proxies, not {raw!r}."
        ) from exc

    if hops < 0:
        raise TrustedProxyConfigError(
            f"{TRUSTED_PROXY_HOPS_VAR} must be zero or more, not {hops}."
        )

    return hops


def apply_trusted_proxy_fix(app) -> int:
    """Make ``request.remote_addr`` the caller's address on this deployment. Returns the hop count.

    With no trusted hops the peer address is the caller's already, and nothing is wrapped: leaving
    ProxyFix out of that path is what keeps a forwarded header from being read where there is no
    proxy entitled to have set one.
    """
    hops = trusted_proxy_hops()
    if hops:
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=hops, x_proto=hops, x_host=0, x_port=0, x_prefix=0,
        )
    return hops
