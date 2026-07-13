"""The client address a rate limit may be keyed on, and what happens when nobody has said.

A limit keyed on the wrong identity is worse than no limit: behind a proxy, ``remote_addr`` is the
proxy for every caller in the world, so a per-IP budget becomes a product-wide one that the first
burst spends on everyone's behalf. Trusting ``X-Forwarded-For`` whole is the opposite failure -- the
caller writes that header, so a limit keyed on it is a limit an attacker resets per request.
"""

import pytest

from conftest import skip_without_real_dependencies

skip_without_real_dependencies()

from flask import Flask, request

from utils.proxy import (
    TRUSTED_PROXY_HOPS_VAR,
    TrustedProxyConfigError,
    apply_trusted_proxy_fix,
    trusted_proxy_hops,
)


class _FakeApp:
    def __init__(self):
        self.wsgi_app = object()


def _app_reporting_the_caller():
    app = Flask(__name__)

    @app.route("/whoami")
    def whoami():
        return {"ip": request.remote_addr}

    return app


class TestTrustedProxyHops:
    def test_development_defaults_to_trusting_nothing(self, monkeypatch):
        monkeypatch.delenv(TRUSTED_PROXY_HOPS_VAR, raising=False)
        monkeypatch.setenv("FLASK_ENV", "development")

        assert trusted_proxy_hops() == 0

    def test_production_refuses_to_guess(self, monkeypatch):
        """Unset is not zero, it is unknown, and both readings of an unknown value break: guess
        zero behind a proxy and every applicant shares one budget; guess one with nothing in front
        and the budget is keyed on a header the caller writes."""
        monkeypatch.delenv(TRUSTED_PROXY_HOPS_VAR, raising=False)
        monkeypatch.setenv("FLASK_ENV", "production")

        with pytest.raises(TrustedProxyConfigError) as exc:
            trusted_proxy_hops()

        assert TRUSTED_PROXY_HOPS_VAR in str(exc.value)

    def test_production_takes_an_explicit_zero(self, monkeypatch):
        """An operator who means "Flask is exposed directly" can say so; they just have to say it."""
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv(TRUSTED_PROXY_HOPS_VAR, "0")

        assert trusted_proxy_hops() == 0

    def test_a_count_is_read(self, monkeypatch):
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv(TRUSTED_PROXY_HOPS_VAR, "2")

        assert trusted_proxy_hops() == 2

    @pytest.mark.parametrize("value", ["yes", "1.5", "-1"])
    def test_a_value_that_is_not_a_hop_count_is_refused(self, monkeypatch, value):
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv(TRUSTED_PROXY_HOPS_VAR, value)

        with pytest.raises(TrustedProxyConfigError):
            trusted_proxy_hops()


class TestApplyTrustedProxyFix:
    def test_no_hops_reads_no_forwarded_header(self, monkeypatch):
        """With nothing in front of Flask, the peer *is* the caller, and a forwarded header is a
        thing the caller made up. Leaving ProxyFix off the path is what keeps it unread."""
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.delenv(TRUSTED_PROXY_HOPS_VAR, raising=False)
        app = _FakeApp()
        original = app.wsgi_app

        hops = apply_trusted_proxy_fix(app)

        assert hops == 0
        assert app.wsgi_app is original

    def test_the_declared_hops_are_the_ones_trusted(self, monkeypatch):
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv(TRUSTED_PROXY_HOPS_VAR, "1")
        app = _FakeApp()
        original = app.wsgi_app

        hops = apply_trusted_proxy_fix(app)

        assert hops == 1
        assert app.wsgi_app is not original
        assert app.wsgi_app.x_for == 1

    def test_a_misconfigured_deployment_does_not_boot(self, monkeypatch):
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.delenv(TRUSTED_PROXY_HOPS_VAR, raising=False)

        with pytest.raises(TrustedProxyConfigError):
            apply_trusted_proxy_fix(_FakeApp())


class TestTheAddressARequestIsCreditedTo:
    """What the rate limits actually key on, driven through the WSGI stack that decides it."""

    def _remote_addr(self, hops, monkeypatch, **headers):
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv(TRUSTED_PROXY_HOPS_VAR, str(hops))
        app = _app_reporting_the_caller()
        apply_trusted_proxy_fix(app)
        with app.test_client() as client:
            return client.get(
                "/whoami", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.1"},
            ).get_json()["ip"]

    def test_with_no_proxy_a_forged_header_is_ignored(self, monkeypatch):
        """Any caller can send X-Forwarded-For. Believed with nothing in front of Flask, it is a
        per-request identity an attacker mints at will, and the budget bounds nothing."""
        addr = self._remote_addr(0, monkeypatch, **{"X-Forwarded-For": "198.51.100.7"})

        assert addr == "10.0.0.1"

    def test_behind_one_proxy_the_caller_is_the_hop_the_proxy_appended(self, monkeypatch):
        addr = self._remote_addr(1, monkeypatch, **{"X-Forwarded-For": "203.0.113.5"})

        assert addr == "203.0.113.5"

    def test_a_caller_cannot_forge_its_way_out_of_its_own_budget(self, monkeypatch):
        """The entries to the *left* are whatever the caller chose to send; the trusted proxy
        appends the address it actually saw on the right. One trusted hop reads exactly that one,
        so a caller that pads the header with a thousand fake addresses is still counted as itself.
        """
        addr = self._remote_addr(
            1, monkeypatch,
            **{"X-Forwarded-For": "1.2.3.4, 5.6.7.8, 203.0.113.5"},
        )

        assert addr == "203.0.113.5"

    def test_two_trusted_hops_read_past_the_second_one(self, monkeypatch):
        addr = self._remote_addr(
            2, monkeypatch,
            **{"X-Forwarded-For": "203.0.113.5, 172.16.0.9"},
        )

        assert addr == "203.0.113.5"
