import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github/workflows"
TEXT = (WORKFLOWS / "report.yml").read_text()
PUBLISH = (WORKFLOWS / "gheymat-latest.yml").read_text()


def job(name):
    match = re.search(rf"^  {name}:\n(.*?)(?=^  [a-z]+:\n|\Z)", TEXT, re.S | re.M)
    assert match
    return match.group(1)


def test_report_job_conditions():
    body = job("report")
    assert "needs:" not in body
    assert "if: github.ref == 'refs/heads/master'" in body
    assert "continue-on-error: true" in body
    assert "timeout-minutes: 4" in body
    assert "contents: read" in body and "actions: read" in body and "write" not in body.split("steps:")[0]


def test_report_job_is_state_free():
    body = job("report")
    assert "cache/save" not in body
    assert "actions/cache/restore@" in body
    assert "gh cache" not in body and "cache delete" not in body
    assert body.count("actions/cache/") == 1


def test_report_has_no_lead_secret():
    assert "LEAD" not in TEXT


def test_publish_workflow_has_no_idle_report_or_self_start():
    for name in ("idle", "report"):
        assert not re.search(rf"^  {name}:", PUBLISH, re.M)
    assert "idle.py" not in PUBLISH and "force_report" not in PUBLISH
    assert not (WORKFLOWS / "watchdog.yml").exists()
    assert "gate:" in PUBLISH and "publish:" in PUBLISH


def test_publish_step_gets_the_extra_sources_secret_and_deploy_steps_do_not():
    assert "GHEYMAT_AI_SOURCES_EXTRA: ${{ secrets.GHEYMAT_AI_SOURCES_EXTRA }}" in PUBLISH
    assert PUBLISH.count("GHEYMAT_AI_SOURCES_EXTRA:") == 1


def test_report_runs_on_a_schedule_through_the_closed_hours():
    head = TEXT.split("concurrency:")[0]
    crons = re.findall(r"- cron: '(\d+) (\d+) \* \* \*'", head)
    assert len(crons) >= 20
    hours = {int(h) for _, h in crons}
    assert hours <= set(range(14, 24)) | {0, 1, 2, 3}
    assert {14, 23, 0, 3} <= hours
    assert "workflow_dispatch:" in head


def test_report_secrets_only_in_build_step():
    body = job("report")
    before = body.split("- name: Build report")[0]
    step = body.split("- name: Build report")[1].split("- name: Upload report")[0]
    for name in ("GHEYMAT_PAYLOAD_KEY", "GHEYMAT_SIGNING_KEY", "GHEYMAT_OWNER_PUBKEY"):
        assert name in step
    for name in ("GHEYMAT_PAYLOAD_KEY", "GHEYMAT_SIGNING_KEY"):
        assert name not in before
    assert before.count("GHEYMAT_OWNER_PUBKEY") == 1
    assert "secrets.GHEYMAT_OWNER_PUBKEY != ''" in before


def test_report_upload_pinned_with_retention():
    body = job("report")
    assert re.search(r"actions/upload-artifact@[0-9a-f]{40} ", body)
    assert "retention-days: 14" in body
    assert "steps.check.outputs.name" in body


def test_force_input_declared():
    head = TEXT.split("concurrency:")[0]
    assert "force_report:" in head and "type: boolean" in head


def test_all_actions_pinned_to_full_sha():
    for line in re.findall(r"uses: (\S+)", TEXT + PUBLISH):
        if line.startswith("./"):
            continue
        assert re.search(r"@[0-9a-f]{40}$", line), line


def test_the_day_is_claimed_before_any_long_work():
    body = job("report")
    order = [body.index(f"- name: {n}") for n in ("Check today", "Mark the day", "Claim the day",
                                                    "Python and dependencies", "Restore feed state", "Build report")]
    assert order == sorted(order)
    claim = body.split("- name: Claim the day")[1].split("- name: Python and dependencies")[0]
    assert "steps.check.outputs.skip == 'false'" in claim and "steps.check.outputs.name" in claim
    final = body.split("- name: Upload report")[1]
    assert "steps.run.outputs.report == 'true'" in final and "overwrite: true" in final


def test_nothing_gets_a_token_it_does_not_need_and_the_build_step_is_capped():
    build = job("report").split("- name: Build report")[1].split("- name: Warn when nothing was produced")[0]
    assert "GH_TOKEN" not in build and "timeout-minutes: 3" in build
