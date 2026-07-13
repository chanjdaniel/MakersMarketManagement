import os
import sys
import types

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.captcha import (
    RECAPTCHA_SECRET_KEY_VAR,
    CaptchaNotConfiguredError,
    assert_captcha_configured,
    verify_recaptcha,
)
from utils.deployment import INSECURE_LOCAL_DEV_VAR


@pytest.fixture
def local_dev(monkeypatch):
    """A process that has said, explicitly, that it is a local development one."""
    monkeypatch.setenv(INSECURE_LOCAL_DEV_VAR, "true")


@pytest.fixture
def deployed(monkeypatch):
    """Anything that has not said so -- which is every deployment, and the default."""
    monkeypatch.delenv(INSECURE_LOCAL_DEV_VAR, raising=False)


class TestCaptchaBypass:
    def test_bypass_when_disable_captcha_enabled(self, monkeypatch, local_dev):
        monkeypatch.setenv("DISABLE_CAPTCHA", "true")
        monkeypatch.delenv("RECAPTCHA_SECRET_KEY", raising=False)

        success, score = verify_recaptcha("dummy-token")

        assert success is True
        assert score == 1.0

    def test_bypass_when_disable_captcha_is_1(self, monkeypatch, local_dev):
        monkeypatch.setenv("DISABLE_CAPTCHA", "1")
        monkeypatch.delenv("RECAPTCHA_SECRET_KEY", raising=False)

        success, score = verify_recaptcha("dummy-token")

        assert success is True
        assert score == 1.0

    def test_disable_captcha_is_ignored_by_anything_that_is_not_local_dev(
        self, monkeypatch, deployed,
    ):
        """A deployment that inherited DISABLE_CAPTCHA from a copied .env must not have a live
        bypass on it. The escape hatch is the only thing that can open one, and it is opt-in."""
        monkeypatch.setenv("DISABLE_CAPTCHA", "true")

        class FakeResponse:
            def json(self):
                return {"success": False, "score": 0.1}

        def fake_post(url, data, timeout):
            return FakeResponse()

        monkeypatch.setattr("utils.captcha.requests.post", fake_post)

        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "prod-secret-key")

        success, score = verify_recaptcha("dummy-token")

        assert success is False
        assert score == 0.1

    def test_dev_bypass_when_no_secret_key(self, monkeypatch, local_dev):
        monkeypatch.delenv("DISABLE_CAPTCHA", raising=False)
        monkeypatch.delenv("RECAPTCHA_SECRET_KEY", raising=False)

        success, score = verify_recaptcha("dummy-token")

        assert success is True
        assert score == 1.0

    def test_enforced_when_secret_key_set_and_no_bypass(self, monkeypatch, local_dev):
        monkeypatch.delenv("DISABLE_CAPTCHA", raising=False)

        class FakeResponse:
            def json(self):
                return {"success": False, "score": 0.1}

        def fake_post(url, data, timeout):
            return FakeResponse()

        monkeypatch.setattr("utils.captcha.requests.post", fake_post)

        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "test-secret-key")

        success, score = verify_recaptcha("bad-token")

        assert success is False
        assert score == 0.1

    def test_enforced_rejects_empty_token_with_secret_key(self, monkeypatch, local_dev):
        monkeypatch.delenv("DISABLE_CAPTCHA", raising=False)

        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "test-secret-key")

        success, score = verify_recaptcha("", ip_address=None)

        assert success is False
        assert score == 0.0


class TestAnUnconfiguredCaptchaFailsClosed:
    """A captcha that disappears when it is not configured is not a control.

    The endpoints it gates are public and unauthenticated, and they write to the database and send
    mail from the product's domain. An unset secret used to mean "pass everybody, and say so only to
    stdout", so a deployment could ship with the gate silently off.

    The check used to be gated on ``FLASK_ENV == "production"``, which is how it came to be dead
    code: the repo's own Dockerfile sets ``FLASK_ENV=development``, so every deployment built from
    that image was exempt from the very check that existed for it. Nothing here reads ``FLASK_ENV``
    any more. The refusal is the default, and the exemption is what has to be asked for.
    """

    def test_boot_refuses_when_the_secret_is_missing(self, monkeypatch, deployed):
        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", None)

        with pytest.raises(CaptchaNotConfiguredError) as exc:
            assert_captcha_configured()

        assert RECAPTCHA_SECRET_KEY_VAR in str(exc.value)
        assert INSECURE_LOCAL_DEV_VAR in str(exc.value)

    @pytest.mark.parametrize("flask_env", ["development", "production", ""])
    def test_the_refusal_does_not_depend_on_flask_env(self, monkeypatch, deployed, flask_env):
        """The bug this replaces in one line: the image ships FLASK_ENV=development, so a gate keyed
        on it protected only the deployments that did not need protecting."""
        monkeypatch.setenv("FLASK_ENV", flask_env)
        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", None)

        with pytest.raises(CaptchaNotConfiguredError):
            assert_captcha_configured()

    def test_boot_is_allowed_once_the_secret_is_set(self, monkeypatch, deployed):
        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "prod-secret-key")

        assert_captcha_configured()

    def test_an_opted_in_local_dev_machine_still_boots_without_a_secret(self, monkeypatch, local_dev):
        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", None)

        assert_captcha_configured()

    def test_an_unverifiable_token_is_not_a_verified_one(self, monkeypatch, deployed):
        """Belt and braces for an entrypoint that skipped the boot check: with no secret there is
        nothing to verify a token against, and that refuses rather than waves through.
        """
        monkeypatch.setenv("DISABLE_CAPTCHA", "true")
        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", None)

        success, score = verify_recaptcha("any-token")

        assert success is False
        assert score == 0.0
