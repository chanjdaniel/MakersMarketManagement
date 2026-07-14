"""The key that carries every route into an organizer account, and what is not one.

Registration, verification, password reset and OTP are all a piece of mail, so a deployment with no
Resend key cannot onboard anybody - it says so one 500 at a time, naming nothing. The boot check
names it once instead.

That check used to ask only whether the variable was set, which two values answer yes to without
being a key: a blank one (the shape a forgotten variable takes in a `.env`) and a placeholder this
repository has published. `re_xxxxx` is truthy, so a copied template *passed* the check and then had
Resend reject every send. A check that can be satisfied with garbage is not a check.
"""

import pytest

from conftest import skip_without_real_dependencies

skip_without_real_dependencies()

import utils.email as email_mod
from utils.deployment import INSECURE_LOCAL_DEV_VAR
from utils.email import (
    RESEND_API_KEY_VAR,
    MailerNotConfiguredError,
    assert_mailer_configured,
    sendable_key,
)

PUBLISHED_PLACEHOLDER = "re_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

A_REAL_KEY = "re_QYt3bK9wLm2ZpR7vX4nHs6Ja"


@pytest.fixture
def local_dev(monkeypatch):
    monkeypatch.setenv(INSECURE_LOCAL_DEV_VAR, "true")


@pytest.fixture
def deployed(monkeypatch):
    """Anything that has not opted in -- which is every deployment, and the default."""
    monkeypatch.delenv(INSECURE_LOCAL_DEV_VAR, raising=False)


@pytest.fixture(autouse=True)
def mailer_state(monkeypatch):
    """The module reads its key once, at import. These are the two things it remembers."""
    monkeypatch.setattr(email_mod, "resend_api_key", "")
    monkeypatch.setattr(email_mod, "resend_initialized", False)


class TestADeploymentThatCannotSendMail:
    def test_refuses_to_start_without_a_key(self, deployed):
        with pytest.raises(MailerNotConfiguredError) as exc:
            assert_mailer_configured()

        assert RESEND_API_KEY_VAR in str(exc.value)
        assert INSECURE_LOCAL_DEV_VAR in str(exc.value)

    def test_boots_once_the_key_is_set(self, deployed, monkeypatch):
        monkeypatch.setattr(email_mod, "resend_api_key", A_REAL_KEY)
        monkeypatch.setattr(email_mod, "resend_initialized", True)

        assert_mailer_configured()

    def test_an_opted_in_local_dev_machine_still_boots_without_one(self, local_dev):
        assert_mailer_configured()


class TestAPlaceholderIsNotAKey:
    def test_boot_refuses_the_placeholder_this_repo_published(self, deployed, monkeypatch):
        monkeypatch.setattr(email_mod, "resend_api_key", PUBLISHED_PLACEHOLDER)

        with pytest.raises(MailerNotConfiguredError) as exc:
            assert_mailer_configured()

        assert RESEND_API_KEY_VAR in str(exc.value)
        assert "placeholder" in str(exc.value)

    def test_a_local_dev_machine_is_refused_it_too(self, local_dev, monkeypatch):
        """The escape hatch lets a process boot with *no* key. It is not a licence to boot with one
        Resend rejects - and the `.env` carrying that placeholder is exactly the file that gets
        copied onto a deployment."""
        monkeypatch.setattr(email_mod, "resend_api_key", PUBLISHED_PLACEHOLDER)

        with pytest.raises(MailerNotConfiguredError):
            assert_mailer_configured()

    def test_it_never_becomes_the_key_the_mailer_sends_with(self):
        """What the module asks at import before initializing the client. Initialized on a
        placeholder, it would report a configured mailer to the boot check and 500 on every send."""
        assert sendable_key(PUBLISHED_PLACEHOLDER) == ""


class TestABlankKeyIsNoKey:
    def test_whitespace_is_not_a_key(self, deployed, monkeypatch):
        """`RESEND_API_KEY=" "` is what a half-edited .env line looks like. Read raw it is truthy,
        so the check passed and the failure it exists to pre-empt arrived at request time."""
        monkeypatch.setattr(email_mod, "resend_api_key", "   ")

        with pytest.raises(MailerNotConfiguredError):
            assert_mailer_configured()

    def test_whitespace_does_not_initialize_the_mailer(self):
        assert sendable_key("   ") == ""

    def test_a_real_key_does(self):
        """The floor under the two above: this check must still recognize an actual key."""
        assert sendable_key(A_REAL_KEY) == A_REAL_KEY
