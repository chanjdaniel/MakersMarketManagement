"""The boot-time contract the public applicant endpoints rest on, and how it refuses.

Three variables defend endpoints that are unauthenticated, write to the database, and send mail from
this domain, and all three fail *silently* when unset. So the process refuses to start without them -
and the refusal has to be one refusal, naming all of them. A check that stopped at the first would
hand an operator one variable per redeploy, which turns one loud failure into three and invites the
third to be met by giving up.
"""
import pytest

from conftest import skip_without_real_dependencies

skip_without_real_dependencies()

import app as app_module
import utils.captcha as captcha_mod

from utils.captcha import RECAPTCHA_SECRET_KEY_VAR
from utils.deployment import INSECURE_LOCAL_DEV_VAR
from utils.proxy import TRUSTED_PROXY_HOPS_VAR
from utils.secret_key import SECRET_KEY_VAR

ALL_VARS = (RECAPTCHA_SECRET_KEY_VAR, SECRET_KEY_VAR, TRUSTED_PROXY_HOPS_VAR)


@pytest.fixture
def deployed(monkeypatch):
    """Anything that has not declared itself a local development machine - every deployment."""
    monkeypatch.delenv(INSECURE_LOCAL_DEV_VAR, raising=False)
    monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", None)
    monkeypatch.delenv(SECRET_KEY_VAR, raising=False)
    monkeypatch.delenv(TRUSTED_PROXY_HOPS_VAR, raising=False)


def test_the_refusal_names_every_missing_variable(deployed):
    with pytest.raises(app_module.PublicEndpointDefenseError) as exc:
        app_module.verify_public_endpoint_defenses()

    message = str(exc.value)
    for variable in ALL_VARS:
        assert variable in message, f"{variable} is missing and the operator is not told so"


def test_the_refusal_points_at_the_deploy_documentation(deployed):
    """The contract is new, and an operator promoting `dev` has to be able to find what it wants."""
    with pytest.raises(app_module.PublicEndpointDefenseError) as exc:
        app_module.verify_public_endpoint_defenses()

    assert "docs/RELEASING.md" in str(exc.value)


def test_one_missing_variable_is_still_a_refusal(deployed, monkeypatch):
    monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "prod-secret")
    monkeypatch.setenv(SECRET_KEY_VAR, "a-real-signing-secret")

    with pytest.raises(app_module.PublicEndpointDefenseError) as exc:
        app_module.verify_public_endpoint_defenses()

    message = str(exc.value)
    assert TRUSTED_PROXY_HOPS_VAR in message
    assert RECAPTCHA_SECRET_KEY_VAR not in message
    assert SECRET_KEY_VAR not in message


def test_a_configured_deployment_boots_and_gets_its_signing_secret(deployed, monkeypatch):
    monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "prod-secret")
    monkeypatch.setenv(SECRET_KEY_VAR, "a-real-signing-secret")
    # Zero hops is a legitimate answer - Flask exposed directly - and it is the one that leaves the
    # WSGI stack of the imported app untouched.
    monkeypatch.setenv(TRUSTED_PROXY_HOPS_VAR, "0")

    assert app_module.verify_public_endpoint_defenses() == "a-real-signing-secret"
