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
    assert "timeout-minutes: 8" in body
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
