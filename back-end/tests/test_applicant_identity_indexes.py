"""The two unique indexes the public applicant endpoints rest on, and how they refuse.

One applicant is one application at a market, and one address is one live login challenge with one
attempt budget. Neither is a promise application code can keep: both documents are written by an
upsert on a public, unauthenticated endpoint, so both are read-then-write races that only the
database can settle. The index *is* the guarantee, not a decoration on one - so a process that
cannot build it does not have the guarantee, and must not pretend it does. It refuses, at boot,
naming what is wrong, exactly as a missing market-key migration and a missing captcha secret do.
"""
import pytest
from pymongo.errors import PyMongoError

from datatypes import Application, ApplicationStatus, ApplicationType

import api.applicants as ApplicantsApi
import api.applications as ApplicationsApi


@pytest.fixture(autouse=True)
def unbuilt(monkeypatch):
    """A process that has not built its indexes yet - which every process is, once, at boot."""
    monkeypatch.setattr(ApplicationsApi, "_indexes_ready", False)
    monkeypatch.setattr(ApplicantsApi, "_login_code_indexes_ready", False)


def _unbuildable(collection, monkeypatch):
    """A collection whose index will not build - which, in production, means it already holds the
    duplicates the index exists to forbid."""
    def boom(*_args, **_kwargs):
        raise PyMongoError("E11000 duplicate key error: index build failed")

    monkeypatch.setattr(collection, "create_index", boom)


class TestTheApplicationIdentityIndex:
    def test_an_index_that_will_not_build_refuses(self, applications, monkeypatch):
        _unbuildable(applications, monkeypatch)

        with pytest.raises(ApplicationsApi.ApplicationIndexError):
            ApplicationsApi.ensure_application_indexes()

    def test_the_refusal_names_the_duplicates_that_are_blocking_it(self, applications, monkeypatch):
        """The operator has to be able to act on it, and the likeliest cause is the one thing the
        index forbids being already in the collection."""
        _unbuildable(applications, monkeypatch)

        with pytest.raises(ApplicationsApi.ApplicationIndexError) as exc:
            ApplicationsApi.ensure_application_indexes()

        message = str(exc.value)
        assert ApplicationsApi.APPLICANT_IDENTITY_INDEX in message
        assert "duplicates" in message

    def test_no_application_is_stored_while_the_index_is_absent(self, applications, monkeypatch):
        """The write that creates an application is a race the index is the only referee of, so a
        process that cannot build it does not get to run the race."""
        _unbuildable(applications, monkeypatch)

        with pytest.raises(ApplicationsApi.ApplicationIndexError):
            ApplicationsApi.find_or_create_application(Application(
                market_id="market-123",
                applicant_email="vendor@example.com",
                application_type=ApplicationType.MAIN,
                form_data={},
                status=ApplicationStatus.OPEN,
            ))

        assert applications.documents == []

    def test_an_index_that_builds_lets_the_application_be_stored(self, applications):
        stored = ApplicationsApi.find_or_create_application(Application(
            market_id="market-123",
            applicant_email="vendor@example.com",
            application_type=ApplicationType.MAIN,
            form_data={},
            status=ApplicationStatus.OPEN,
        ))

        assert stored.applicant_email == "vendor@example.com"
        assert len(applications.documents) == 1


class TestTheLoginChallengeIndex:
    def test_an_index_that_will_not_build_refuses(self, login_codes, monkeypatch):
        _unbuildable(login_codes, monkeypatch)

        with pytest.raises(ApplicantsApi.LoginChallengeIndexError):
            ApplicantsApi.ensure_login_code_indexes()

    def test_the_refusal_names_what_is_lost_with_it(self, login_codes, monkeypatch):
        _unbuildable(login_codes, monkeypatch)

        with pytest.raises(ApplicantsApi.LoginChallengeIndexError) as exc:
            ApplicantsApi.ensure_login_code_indexes()

        assert "attempt budget" in str(exc.value)

    def test_no_challenge_is_issued_while_the_index_is_absent(self, login_codes, monkeypatch):
        """Without the unique index an address can hold several live codes, each with its own
        attempt budget - which is a guess budget the caller sets, against a five-minute code."""
        _unbuildable(login_codes, monkeypatch)

        with pytest.raises(ApplicantsApi.LoginChallengeIndexError):
            ApplicantsApi._issue_challenge("market-123", "vendor@example.com", "123456")

        assert login_codes.documents == []
