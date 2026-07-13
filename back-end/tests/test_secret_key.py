"""The key everything in this product is signed with, and what happens when nobody configured one.

The fallback that used to stand in for it was a literal in this repository, which is to say a
published key: the Flask session cookie and the application-scoped applicant token were both signed
with a string anyone could read off the source, so anyone could write either one. A secret with a
default is not a secret, and these tests hold the line that there is no default.
"""

import pytest

from conftest import skip_without_real_dependencies

skip_without_real_dependencies()

import utils.secret_key as secret_key_module
from utils.deployment import INSECURE_LOCAL_DEV_VAR
from utils.secret_key import (
    SECRET_KEY_VAR,
    SecretKeyNotConfiguredError,
    assert_signing_secret_configured,
    signing_secret,
)

PUBLISHED_FALLBACK = "TEMP_KEY_CHANGE_IN_PRODUCTION"


@pytest.fixture(autouse=True)
def no_secret_carried_between_tests(monkeypatch):
    """The dev secret is cached for the process, so a test must not inherit the last one's."""
    monkeypatch.setattr(secret_key_module, "_ephemeral_secret", None)


@pytest.fixture
def local_dev(monkeypatch):
    monkeypatch.setenv(INSECURE_LOCAL_DEV_VAR, "true")


@pytest.fixture
def deployed(monkeypatch):
    """Anything that has not opted in -- which is every deployment, and the default."""
    monkeypatch.delenv(INSECURE_LOCAL_DEV_VAR, raising=False)


class TestADeploymentWithoutASecret:
    def test_refuses_to_start(self, monkeypatch, deployed):
        monkeypatch.delenv(SECRET_KEY_VAR, raising=False)

        with pytest.raises(SecretKeyNotConfiguredError) as exc:
            assert_signing_secret_configured()

        assert SECRET_KEY_VAR in str(exc.value), "the refusal has to name the variable"
        assert INSECURE_LOCAL_DEV_VAR in str(exc.value)

    def test_an_empty_secret_is_no_secret(self, monkeypatch, deployed):
        """A variable that is present and blank is the shape a forgotten one takes in a .env file."""
        monkeypatch.setenv(SECRET_KEY_VAR, "   ")

        with pytest.raises(SecretKeyNotConfiguredError):
            signing_secret()

    @pytest.mark.parametrize("flask_env", ["development", "production", ""])
    def test_the_refusal_does_not_depend_on_flask_env(self, monkeypatch, deployed, flask_env):
        """The image ships FLASK_ENV=development and nothing overrides it, so a check keyed on it
        would exempt every deployment built from that image -- which is all of them."""
        monkeypatch.setenv("FLASK_ENV", flask_env)
        monkeypatch.delenv(SECRET_KEY_VAR, raising=False)

        with pytest.raises(SecretKeyNotConfiguredError):
            signing_secret()

    def test_a_configured_secret_is_the_one_used(self, monkeypatch, deployed):
        monkeypatch.setenv(SECRET_KEY_VAR, "a-real-secret")

        assert signing_secret() == "a-real-secret"


class TestAnOptedInLocalDevMachine:
    """It boots without a secret. It does not boot with a *published* one."""

    def test_gets_a_secret_that_is_not_in_this_repository(self, monkeypatch, local_dev):
        monkeypatch.delenv(SECRET_KEY_VAR, raising=False)

        secret = signing_secret()

        assert secret
        assert secret != PUBLISHED_FALLBACK, "a committed fallback is a key anyone can read"

    def test_the_secret_is_unpredictable(self, monkeypatch, local_dev):
        """Random per process is what keeps the escape hatch from being a fallback again: a value
        nobody can guess cannot be forged against, and one that changes every boot cannot quietly
        become the key a deployment ships with."""
        monkeypatch.delenv(SECRET_KEY_VAR, raising=False)
        first = signing_secret()

        monkeypatch.setattr(secret_key_module, "_ephemeral_secret", None)
        second = signing_secret()

        assert first != second
        assert len(first) >= 32

    def test_the_secret_is_stable_within_the_process(self, monkeypatch, local_dev):
        """Re-rolled per call, it would refuse the token it signed a moment earlier."""
        monkeypatch.delenv(SECRET_KEY_VAR, raising=False)

        assert signing_secret() == signing_secret()

    def test_it_says_so_every_time(self, monkeypatch, local_dev, caplog):
        monkeypatch.delenv(SECRET_KEY_VAR, raising=False)

        with caplog.at_level("WARNING"):
            signing_secret()

        assert INSECURE_LOCAL_DEV_VAR in caplog.text
        assert SECRET_KEY_VAR in caplog.text
