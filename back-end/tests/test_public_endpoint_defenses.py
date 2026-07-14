"""The boot-time contract this app's public surface rests on, and how it refuses.

Five variables carry endpoints that are unauthenticated, write to the database, send mail from this
domain, and answer the organizer's browser with their session attached - and all five fail *silently*
when unset. So the process refuses to start without them - and the refusal has to be one refusal,
naming all of them. A check that stopped at the first would hand an operator one variable per
redeploy, which turns one loud failure into five and invites the last to be met by giving up.

Four of them are defenses. The fifth is the mail key, and it is here because it fails in the same
shape: an applicant's only way in is the one-time code, no layer on that path may report a failed
send (that would say who has applied), and so a deployment without it serves a sign-in nobody can
complete while telling every applicant a code is on the way.

Two unique indexes are part of the same contract, and fail the same way: they are what make an
applicant one applicant and an address one login challenge, they cannot be enforced anywhere but the
database, and a process that could not build them would serve on without them and say nothing.
"""
import pytest
from pymongo.errors import PyMongoError

from conftest import skip_without_real_dependencies

skip_without_real_dependencies()

import app as app_module
import api.applicants as ApplicantsApi
import api.applications as ApplicationsApi
import utils.captcha as captcha_mod
import utils.email as email_mod

from utils.captcha import RECAPTCHA_SECRET_KEY_VAR
from utils.cors import CORS_ALLOWED_ORIGINS_VAR
from utils.deployment import INSECURE_LOCAL_DEV_VAR
from utils.email import RESEND_API_KEY_VAR
from utils.proxy import TRUSTED_PROXY_HOPS_VAR
from utils.secret_key import SECRET_KEY_VAR

ALL_VARS = (
    RECAPTCHA_SECRET_KEY_VAR,
    RESEND_API_KEY_VAR,
    SECRET_KEY_VAR,
    TRUSTED_PROXY_HOPS_VAR,
    CORS_ALLOWED_ORIGINS_VAR,
)


@pytest.fixture
def deployed(monkeypatch):
    """Anything that has not declared itself a local development machine - every deployment."""
    monkeypatch.delenv(INSECURE_LOCAL_DEV_VAR, raising=False)
    monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", None)
    monkeypatch.setattr(email_mod, "resend_initialized", False)
    monkeypatch.delenv(SECRET_KEY_VAR, raising=False)
    monkeypatch.delenv(TRUSTED_PROXY_HOPS_VAR, raising=False)
    monkeypatch.delenv(CORS_ALLOWED_ORIGINS_VAR, raising=False)


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
    monkeypatch.setattr(email_mod, "resend_initialized", True)
    monkeypatch.setenv(SECRET_KEY_VAR, "a-real-signing-secret")
    monkeypatch.setenv(CORS_ALLOWED_ORIGINS_VAR, "https://app.example.com")

    with pytest.raises(app_module.PublicEndpointDefenseError) as exc:
        app_module.verify_public_endpoint_defenses()

    message = str(exc.value)
    assert TRUSTED_PROXY_HOPS_VAR in message
    assert RECAPTCHA_SECRET_KEY_VAR not in message
    assert RESEND_API_KEY_VAR not in message
    assert SECRET_KEY_VAR not in message
    assert CORS_ALLOWED_ORIGINS_VAR not in message


def test_a_deployment_that_cannot_mail_the_login_code_does_not_serve(deployed, monkeypatch):
    """An applicant has no password and no account: with no mail key there is no way in at all.

    Nothing on that path may say so - a response that reported the send would report who has applied
    - so the only place it can be said is here, before anybody is told a code is on the way.
    """
    monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "prod-secret")
    monkeypatch.setenv(SECRET_KEY_VAR, "a-real-signing-secret")
    monkeypatch.setenv(TRUSTED_PROXY_HOPS_VAR, "0")
    monkeypatch.setenv(CORS_ALLOWED_ORIGINS_VAR, "https://app.example.com")

    with pytest.raises(app_module.PublicEndpointDefenseError) as exc:
        app_module.verify_public_endpoint_defenses()

    assert RESEND_API_KEY_VAR in str(exc.value)


def test_a_local_development_machine_still_boots_without_a_mail_key(monkeypatch):
    """The escape hatch covers the mail key too: e2e runs with DISABLE_EMAIL and no Resend account."""
    monkeypatch.setenv(INSECURE_LOCAL_DEV_VAR, "true")
    monkeypatch.setattr(email_mod, "resend_initialized", False)

    email_mod.assert_mailer_configured()


def test_a_configured_deployment_boots_and_gets_its_signing_secret(deployed, monkeypatch):
    monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "prod-secret")
    monkeypatch.setattr(email_mod, "resend_initialized", True)
    monkeypatch.setenv(SECRET_KEY_VAR, "a-real-signing-secret")
    # Zero hops is a legitimate answer - Flask exposed directly - and it is the one that leaves the
    # WSGI stack of the imported app untouched.
    monkeypatch.setenv(TRUSTED_PROXY_HOPS_VAR, "0")
    monkeypatch.setenv(CORS_ALLOWED_ORIGINS_VAR, "https://app.example.com")

    assert app_module.verify_public_endpoint_defenses() == "a-real-signing-secret"


class TestTheIndexesTheApplicantEndpointsRestOn:
    """An index that will not build is a guarantee the process does not have, so it does not start.

    In production an index that will not build almost always means the collection already holds what
    the index forbids - two applications for one applicant, two live codes for one address - which is
    a state to stop and repair, not one to serve more public traffic into.
    """

    @pytest.fixture(autouse=True)
    def unbuilt(self, monkeypatch):
        """Importing app.py already built these; boot again from a process that has not."""
        monkeypatch.setattr(ApplicationsApi, "_indexes_ready", False)
        monkeypatch.setattr(ApplicantsApi, "_login_code_indexes_ready", False)

    def _unbuildable(self, collection, monkeypatch):
        def boom(*_args, **_kwargs):
            raise PyMongoError("E11000 duplicate key error: index build failed")

        monkeypatch.setattr(collection, "create_index", boom)

    def test_boot_refuses_when_the_application_identity_index_will_not_build(
        self, applications, monkeypatch,
    ):
        self._unbuildable(applications, monkeypatch)

        with pytest.raises(ApplicationsApi.ApplicationIndexError):
            app_module.verify_applicant_identity_indexes()

    def test_boot_refuses_when_the_login_challenge_index_will_not_build(
        self, login_codes, monkeypatch,
    ):
        self._unbuildable(login_codes, monkeypatch)

        with pytest.raises(ApplicantsApi.LoginChallengeIndexError):
            app_module.verify_applicant_identity_indexes()

    def test_a_database_that_can_hold_them_boots(self, applications, login_codes):
        app_module.verify_applicant_identity_indexes()

        assert ApplicationsApi._indexes_ready is True
        assert ApplicantsApi._login_code_indexes_ready is True
