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


class TestCaptchaBypass:
    def test_bypass_when_disable_captcha_enabled(self, monkeypatch):
        monkeypatch.setenv("DISABLE_CAPTCHA", "true")
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.delenv("RECAPTCHA_SECRET_KEY", raising=False)

        success, score = verify_recaptcha("dummy-token")

        assert success is True
        assert score == 1.0

    def test_bypass_when_disable_captcha_is_1(self, monkeypatch):
        monkeypatch.setenv("DISABLE_CAPTCHA", "1")
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.delenv("RECAPTCHA_SECRET_KEY", raising=False)

        success, score = verify_recaptcha("dummy-token")

        assert success is True
        assert score == 1.0

    def test_disable_captcha_ignored_in_production(self, monkeypatch):
        monkeypatch.setenv("DISABLE_CAPTCHA", "true")
        monkeypatch.setenv("FLASK_ENV", "production")

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

    def test_dev_bypass_when_no_secret_key(self, monkeypatch):
        monkeypatch.delenv("DISABLE_CAPTCHA", raising=False)
        monkeypatch.delenv("RECAPTCHA_SECRET_KEY", raising=False)
        monkeypatch.setenv("FLASK_ENV", "development")

        success, score = verify_recaptcha("dummy-token")

        assert success is True
        assert score == 1.0

    def test_enforced_when_secret_key_set_and_no_bypass(self, monkeypatch):
        monkeypatch.delenv("DISABLE_CAPTCHA", raising=False)
        monkeypatch.setenv("FLASK_ENV", "development")

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

    def test_enforced_rejects_empty_token_with_secret_key(self, monkeypatch):
        monkeypatch.delenv("DISABLE_CAPTCHA", raising=False)
        monkeypatch.setenv("FLASK_ENV", "development")

        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "test-secret-key")

        success, score = verify_recaptcha("", ip_address=None)

        assert success is False
        assert score == 0.0


class TestProductionFailsClosed:
    """A captcha that disappears when it is not configured is not a control.

    The endpoints it gates are public and unauthenticated, and they write to the database and send
    mail from the product's domain. An unset secret used to mean "pass everybody, and say so only to
    stdout", so a deployment could ship with the gate silently off. Unknown state is never safe
    state: production refuses, loudly, naming the variable.
    """

    def test_boot_refuses_when_the_secret_is_missing_in_production(self, monkeypatch):
        monkeypatch.setenv("FLASK_ENV", "production")
        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", None)

        with pytest.raises(CaptchaNotConfiguredError) as exc:
            assert_captcha_configured()

        assert RECAPTCHA_SECRET_KEY_VAR in str(exc.value)

    def test_boot_is_allowed_once_the_secret_is_set(self, monkeypatch):
        monkeypatch.setenv("FLASK_ENV", "production")
        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", "prod-secret-key")

        assert_captcha_configured()

    def test_development_still_boots_without_a_secret(self, monkeypatch):
        monkeypatch.setenv("FLASK_ENV", "development")
        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", None)

        assert_captcha_configured()

    def test_an_unverifiable_token_is_not_a_verified_one(self, monkeypatch):
        """Belt and braces for an entrypoint that skipped the boot check: with no secret there is
        nothing to verify a token against, and in production that refuses rather than waves through.
        """
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DISABLE_CAPTCHA", "true")
        import utils.captcha as captcha_mod
        monkeypatch.setattr(captcha_mod, "RECAPTCHA_SECRET_KEY", None)

        success, score = verify_recaptcha("any-token")

        assert success is False
        assert score == 0.0
