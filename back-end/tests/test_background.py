"""Deferred work runs, and a failure in it takes nothing else down with it."""

from utils.background import run_later


class TestRunLater:
    def test_the_work_actually_runs(self):
        done = []

        future = run_later(lambda value: done.append(value), "sent")
        future.result(timeout=5)

        assert done == ["sent"]

    def test_arguments_are_passed_through(self):
        seen = []

        future = run_later(lambda addr, otp: seen.append((addr, otp)), "v@example.com", otp="123456")
        future.result(timeout=5)

        assert seen == [("v@example.com", "123456")]

    def test_a_failure_is_swallowed_rather_than_raised_into_nowhere(self, caplog):
        """There is no request left to fail by the time this runs, and a mail that could not be sent
        is not a reason to take a worker thread down. It is logged."""

        def boom():
            raise RuntimeError("resend is down")

        future = run_later(boom)

        assert future.result(timeout=5) is None
        assert future.exception() is None
