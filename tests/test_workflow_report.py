import re
from pathlib import Path

TEXT = (Path(__file__).resolve().parent.parent / ".github/workflows/gheymat-latest.yml").read_text()


def job(name):
    match = re.search(rf"^  {name}:\n(.*?)(?=^  [a-z]+:\n|\Z)", TEXT, re.S | re.M)
    assert match
    return match.group(1)


def test_report_job_conditions():
    body = job("report")
    assert "needs: gate" in body
    assert "needs.gate.outputs.open == 'false' && github.ref == 'refs/heads/master'" in body
    assert "continue-on-error: true" in body
    assert "timeout-minutes: 4" in body
    assert "contents: read" in body and "actions: read" in body and "write" not in body.split("steps:")[0]


def test_report_job_is_state_free():
    body = job("report")
    assert "cache/save" not in body
    assert "actions/cache/restore@" in body
    assert "gh cache" not in body and "cache delete" not in body
    assert body.count("actions/cache/") == 1


def test_report_job_no_lead_secret_and_idle_has_no_secrets():
    assert "LEAD" not in TEXT
    assert "secrets." not in job("idle").replace("secrets.GITHUB_TOKEN", "")


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
    for line in re.findall(r"uses: (\S+)", TEXT):
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
