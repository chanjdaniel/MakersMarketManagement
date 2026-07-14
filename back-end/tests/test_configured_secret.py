"""What counts as a configured secret - the one question all three boot checks now ask.

Each of them used to ask its own, and each asked the weakest one available: is the variable truthy?
Two values answer yes without being a secret, and both are what a half-copied template looks like: a
blank, and a placeholder this repository has printed. The second is the dangerous one, because it is
truthy - so the check passes, and the deployment fails later and elsewhere, naming none of it.
"""

import pytest

from utils.configured_secret import (
    PUBLISHED_VALUES,
    configured_secret,
    is_published,
)

A_GENERATED_KEY = "SGDdxXn4YCG4M5pDeUjXTt8g0MSTXNKAtePMxo96b3s"

VAR = "A_SECRET_FOR_THIS_TEST"


class TestAValueThisRepositoryHasPrinted:
    @pytest.mark.parametrize("published", sorted(PUBLISHED_VALUES))
    def test_is_not_a_secret(self, published):
        assert is_published(published)

    def test_the_case_it_is_typed_in_does_not_launder_it(self):
        assert is_published("TEMP_KEY_CHANGE_IN_PRODUCTION")

    def test_neither_does_the_whitespace_around_it(self):
        assert is_published("  your-resend-api-key\n")

    @pytest.mark.parametrize("placeholder", [
        "re_xxxxxxxxxxxx",
        "sk_XXXXXXXXXXXX",
        "your-api-key",
        "your_secret_here",
        "<generate: python -c 'import secrets; print(secrets.token_urlsafe(48))'>",
    ])
    def test_one_nobody_has_listed_yet_is_caught_by_its_shape(self, placeholder):
        """The literal list cannot be complete: the placeholder somebody writes into a template
        tomorrow is not in it yet. A run of x's and a `your-` prefix are what every one of them in
        this repository's history has looked like."""
        assert is_published(placeholder)


class TestARealSecret:
    def test_is_not_mistaken_for_a_placeholder(self):
        assert not is_published(A_GENERATED_KEY)
        assert not is_published("re_QYt3bK9wLm2ZpR7vX4nHs6Ja")

    def test_survives_the_read(self, monkeypatch):
        monkeypatch.setenv(VAR, A_GENERATED_KEY)

        assert configured_secret(VAR) == A_GENERATED_KEY

    def test_the_whitespace_a_env_file_carries_is_stripped(self, monkeypatch):
        monkeypatch.setenv(VAR, f"  {A_GENERATED_KEY}  ")

        assert configured_secret(VAR) == A_GENERATED_KEY


class TestAVariableThatHoldsNoSecret:
    def test_an_unset_one_holds_none(self, monkeypatch):
        monkeypatch.delenv(VAR, raising=False)

        assert configured_secret(VAR) == ""

    def test_a_blank_one_holds_none(self, monkeypatch):
        """The shape a forgotten variable takes in a .env file, and truthy to anything reading the
        raw value."""
        monkeypatch.setenv(VAR, "   ")

        assert configured_secret(VAR) == ""
        assert not is_published("   "), "blank is unset, not published - the refusals differ"

    def test_a_published_one_holds_none(self, monkeypatch):
        """A secret only the deployment holds is the whole of what a secret is. This one is in the
        repo, so every reader has it - which makes it exactly as useful as an empty string."""
        monkeypatch.setenv(VAR, "re_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx")

        assert configured_secret(VAR) == ""
