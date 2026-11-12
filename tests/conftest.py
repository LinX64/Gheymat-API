import pytest

_skipped = []


def pytest_runtest_logreport(report):
    if report.skipped:
        _skipped.append(report.nodeid)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    if _skipped and session.exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        print("\nSkipped tests are not allowed: " + ", ".join(_skipped))
