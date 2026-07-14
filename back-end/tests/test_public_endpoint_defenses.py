"""The boot-time contract this app's public surface rests on, and how it refuses.

Four variables carry endpoints that are unauthenticated, write to the database, send mail from this
domain, and answer the organizer's browser with their session attached. So the process refuses to
start without them - and the refusal has to be one refusal, naming all of them. A check that stopped
at the first would hand an operator one variable per redeploy, which turns one loud failure into
four and invites the last to be met by giving up.

Three of them are defenses, and their absence is never reported anywhere. The fourth is the mail key,
whose absence is reported everywhere and diagnosed nowhere: every registration, reset and OTP answers
500, and none of them names the variable. Both belong in the same refusal, for opposite reasons.

Asking the question must not answer it: the check reads configuration, and installing what it found
is a separate call. flask-cors adds an ``after_request`` handler per invocation, so a check that
configured the app as a side effect left one behind every time it was asked.
"""
import pytest

from conftest import skip_without_real_dependencies

skip_without_real_dependencies()

import app as app_module
import utils.captcha as captcha_mod
import utils.email as email_mod

from flask import Flask

from utils.captcha import RECAPTCHA_SECRET_KEY_VAR
from utils.cors import CORS_ALLOWED_ORIGINS_VAR
from utils.deployment import INSECURE_LOCAL_DEV_VAR
from utils.email import RESEND_API_KEY_VAR
from utils.secret_key import SECRET_KEY_VAR

ALL_VARS = (
    RECAPTCHA_SECRET_KEY_VAR,
    RESEND_API_KEY_VAR,
    SECRET_KEY_VAR,
    CORS_ALLOWED_ORIGINS_VAR,
)


@pytest.fixture
def deployed(monkeypatch):
    """Anything that has not declared itself a local development machine - every deployment."""
    monkeypatch.delenv(INSECURE_LOCAL_DEV_VAR, raising=False)
    monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", None)
    monkeypatch.setattr(email_mod, "resend_initialized", False)
    monkeypatch.delenv(SECRET_KEY_VAR, raising=False)
    monkeypatch.delenv(CORS_ALLOWED_ORIGINS_VAR, raising=False)


@pytest.fixture
def configured(deployed, monkeypatch):
    """A deployment that has been told everything the check asks for."""
    monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "prod-secret")
    monkeypatch.setattr(email_mod, "resend_initialized", True)
    monkeypatch.setenv(SECRET_KEY_VAR, "a-real-signing-secret")
    monkeypatch.setenv(CORS_ALLOWED_ORIGINS_VAR, "https://app.example.com")


def test_the_refusal_names_every_missing_variable(deployed):
    with pytest.raises(app_module.PublicEndpointDefenseError) as exc:
        app_module.check_public_endpoint_defenses()

    message = str(exc.value)
    for variable in ALL_VARS:
        assert variable in message, f"{variable} is missing and the operator is not told so"


def test_the_refusal_points_at_the_deploy_documentation(deployed):
    """The contract is new, and an operator promoting `dev` has to be able to find what it wants."""
    with pytest.raises(app_module.PublicEndpointDefenseError) as exc:
        app_module.check_public_endpoint_defenses()

    assert "docs/RELEASING.md" in str(exc.value)


def test_one_missing_variable_is_still_a_refusal(deployed, monkeypatch):
    monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "prod-secret")
    monkeypatch.setattr(email_mod, "resend_initialized", True)
    monkeypatch.setenv(SECRET_KEY_VAR, "a-real-signing-secret")

    with pytest.raises(app_module.PublicEndpointDefenseError) as exc:
        app_module.check_public_endpoint_defenses()

    message = str(exc.value)
    assert CORS_ALLOWED_ORIGINS_VAR in message
    assert RECAPTCHA_SECRET_KEY_VAR not in message
    assert RESEND_API_KEY_VAR not in message
    assert SECRET_KEY_VAR not in message


def test_a_deployment_that_cannot_send_mail_does_not_serve(deployed, monkeypatch):
    """Every route into an organizer account is a piece of mail: verification, reset, OTP.

    With no key, registration rolls the account back and answers 500, and the operator is left to
    infer the variable from a broken signup. It is named here instead, once, before anybody tries.
    """
    monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "prod-secret")
    monkeypatch.setenv(SECRET_KEY_VAR, "a-real-signing-secret")
    monkeypatch.setenv(CORS_ALLOWED_ORIGINS_VAR, "https://app.example.com")

    with pytest.raises(app_module.PublicEndpointDefenseError) as exc:
        app_module.check_public_endpoint_defenses()

    assert RESEND_API_KEY_VAR in str(exc.value)


def test_a_local_development_machine_still_boots_without_a_mail_key(monkeypatch):
    """The escape hatch covers the mail key too: e2e runs with DISABLE_EMAIL and no Resend account."""
    monkeypatch.setenv(INSECURE_LOCAL_DEV_VAR, "true")
    monkeypatch.setattr(email_mod, "resend_initialized", False)

    email_mod.assert_mailer_configured()


def test_a_configured_deployment_boots_and_reports_what_it_found(configured):
    defenses = app_module.check_public_endpoint_defenses()

    assert defenses.signing_secret == "a-real-signing-secret"
    assert defenses.origins == ["https://app.example.com"]


def test_asking_whether_a_deployment_is_configured_does_not_configure_it(configured):
    """The check is a check. It used to install ProxyFix and a flask-cors handler on the module's
    own app object as a side effect, so every caller - the test suite included - stacked another
    handler onto the running app and left the last caller's origin list behind it."""
    app = Flask(__name__)
    before = (app.wsgi_app, len(app.after_request_funcs.get(None, [])))

    app_module.check_public_endpoint_defenses()
    app_module.check_public_endpoint_defenses()

    assert (app.wsgi_app, len(app.after_request_funcs.get(None, []))) == before


def test_configuring_is_what_installs_the_policy(configured):
    """The mutation lives in the call named for it, and installs the handler exactly once."""
    app = Flask(__name__)
    defenses = app_module.check_public_endpoint_defenses()

    app_module.configure_public_endpoint_defenses(app, defenses)

    assert len(app.after_request_funcs.get(None, [])) == 1
    assert app.config["SECRET_KEY"] == "a-real-signing-secret"
