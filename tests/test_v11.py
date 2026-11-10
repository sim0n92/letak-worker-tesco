"""Proc-protocol v1.1 (spec / check / run) and the legacy-execute regression for letak-worker-tesco."""
from __future__ import annotations

import json
import sys

import pytest
from jsonschema import Draft202012Validator

from conftest import FIXTURES, ROOT, UNREACHABLE

sys.path.insert(0, str(ROOT / "src")) if (ROOT / "src").is_dir() else sys.path.insert(0, str(ROOT))
import v11  # noqa: E402

CURRENT = "HM"
MAGAZINE = "SM"


def _keys(result: dict) -> list[str]:
    return [item["key"] for item in result["items"]]


def test_should_return_valid_schemas_when_spec_is_requested(run_action):
    run = run_action("spec")

    assert run.returncode == 0
    assert run.result["protocol"] == "1.1"
    Draft202012Validator.check_schema(run.result["configSchema"])
    Draft202012Validator.check_schema(run.result["outputSchema"])
    assert run.result["configSchema"]["type"] == "object"


def test_should_report_keyed_items_and_state_when_run_on_fixture(run_action, fixture_config):
    run = run_action("run", **fixture_config)

    assert run.returncode == 0
    result = run.result
    assert sorted(_keys(result)) == sorted([
        f"{CURRENT}|2026-07-01|2026-07-07", f"{MAGAZINE}|2026-07-01|2026-07-07"])
    first = next(i for i in result["items"] if i["key"].startswith(CURRENT))
    assert first["url"].endswith(".pdf")
    assert first["meta"] == {"type": CURRENT, "validFrom": "2026-07-01", "validTo": "2026-07-07"}
    assert sorted(result["state"]["seen"]) == sorted(_keys(result))
    assert result["metrics"] == {"leaflets": 2, "newLeaflets": 2}
    assert result["checks"] == [{"name": "leaflets_found", "passed": True, "severity": "error"}]


def test_should_match_output_schema_when_run_on_fixture(run_action, fixture_config):
    spec = run_action("spec").result
    result = run_action("run", **fixture_config).result

    Draft202012Validator(spec["outputSchema"]).validate(result)
    element = spec["outputSchema"]["properties"]["items"]["items"]
    for item in result["items"]:
        Draft202012Validator(element).validate(item)


def test_should_return_no_items_when_run_again_with_returned_state(run_action, fixture_config):
    first = run_action("run", **fixture_config).result

    again = run_action("run", state=first["state"], **fixture_config).result

    assert again["items"] == []
    assert again["state"] == first["state"]
    assert again["metrics"] == {"leaflets": 2, "newLeaflets": 0}


def test_should_filter_by_type_but_record_every_key_when_types_given(run_action, fixture_config):
    result = run_action("run", types=[CURRENT.lower()], **fixture_config).result

    assert _keys(result) == [f"{CURRENT}|2026-07-01|2026-07-07"]
    assert len(result["state"]["seen"]) == 2
    assert result["metrics"] == {"leaflets": 2, "newLeaflets": 1}


def test_should_keep_newest_200_when_state_has_250_keys(run_action, fixture_config):
    old = [f"old|{n:03d}|x" for n in range(250)]

    result = run_action("run", state={"seen": old}, **fixture_config).result

    seen = result["state"]["seen"]
    assert len(seen) == 200
    assert set(_keys(result)) <= set(seen)
    assert "old|000|x" not in seen
    assert "old|249|x" in seen


def test_should_treat_known_leaflets_as_seen_when_legacy_param_given(run_action, fixture_config):
    result = run_action(
        "run", knownLeaflets=[f"{CURRENT}|2026-07-01|2026-07-07"], **fixture_config).result

    assert _keys(result) == [f"{MAGAZINE}|2026-07-01|2026-07-07"]


def test_should_report_ok_when_check_finds_leaflets(run_action, fixture_config):
    run = run_action("check", **fixture_config)

    assert run.returncode == 0
    assert run.result["ok"] is True


def test_should_report_system_error_when_check_page_has_no_leaflets(run_action, fixture_config, empty_page):
    run = run_action("check", **{**fixture_config, "pageUrl": empty_page})

    assert run.returncode == 4
    assert run.error["code"] == "system_error"
    assert "data" not in run.error


def test_should_report_transient_error_with_retry_when_fetch_fails(run_action, fixture_config):
    run = run_action("run", **{**fixture_config, "pageUrl": UNREACHABLE})

    assert run.error["code"] == "transient_error"
    assert run.error["data"] == {"retryAfterSec": 300}
    assert run.returncode == 4


def test_should_report_transient_error_when_check_fetch_fails(run_action, fixture_config):
    run = run_action("check", **{**fixture_config, "pageUrl": UNREACHABLE})

    assert run.error["code"] == "transient_error"
    assert run.error["data"] == {"retryAfterSec": 300}


def test_should_report_system_error_when_run_finds_no_leaflets(run_action, fixture_config, empty_page):
    run = run_action("run", **{**fixture_config, "pageUrl": empty_page})

    assert run.error["code"] == "system_error"
    assert "data" not in run.error


@pytest.mark.parametrize("legacy_code, data, expected", [
    ("FETCH_FAILED", None, "transient_error"), ("FETCH_FAILED", {}, "transient_error"),
    ("FETCH_FAILED", {"status": 503}, "transient_error"), ("TIMEOUT", None, "transient_error"),
    ("FETCH_FAILED", {"status": 403}, "system_error"), ("FETCH_FAILED", {"status": 401}, "system_error"),
    ("NO_LEAFLETS", None, "system_error"), ("PARSE_FAILED", None, "system_error"),
    ("INVALID_INPUT", None, "config_error"), (None, None, "system_error")])
def test_should_map_legacy_codes_to_protocol_codes_when_classified(legacy_code, data, expected):
    assert v11.classify_error(legacy_code, data) == expected


@pytest.mark.parametrize("status", [403, 401])
def test_should_report_system_error_naming_the_block_when_site_blocks(run_action, status_server, status):
    run = run_action("run", pageUrl=status_server(status))

    assert run.error["code"] == "system_error"
    assert "blocked by the site" in run.error["message"]
    assert str(status) in run.error["message"]
    assert "data" not in run.error


def test_should_report_transient_error_when_site_answers_503(run_action, status_server):
    run = run_action("run", pageUrl=status_server(503))

    assert run.error["code"] == "transient_error"
    assert run.error["data"] == {"retryAfterSec": 300}


def test_should_report_system_error_when_page_markup_changed(run_action, broken_page):
    run = run_action("check", pageUrl=broken_page)

    assert run.error["code"] == "system_error"


def test_should_read_the_api_first_when_api_url_given(run_action):
    api = (FIXTURES / "tesco_api.json").as_uri()

    result = run_action("run", apiUrl=api).result

    assert len(result["items"]) == 4
    assert result["metrics"] == {"leaflets": 4, "newLeaflets": 4}


def test_should_report_config_error_when_state_is_malformed(run_action, fixture_config):
    run = run_action("run", state="not-an-object", **fixture_config)

    assert run.error["code"] == "config_error"
    assert run.returncode == 2


def test_should_report_config_error_when_types_is_not_a_list(run_action, fixture_config):
    run = run_action("run", types="Aktualny", **fixture_config)

    assert run.error["code"] == "config_error"


def test_should_emit_only_protocol_lines_when_any_action_runs(run_action, fixture_config, empty_page):
    allowed = {"progress", "result", "error"}
    runs = [
        run_action("spec"),
        run_action("check", **fixture_config),
        run_action("run", **fixture_config),
        run_action("run", state="bad", **fixture_config),
        run_action("check", **{**fixture_config, "pageUrl": empty_page}),
    ]

    for run in runs:
        assert run.lines
        assert {m["type"] for m in run.lines} <= allowed


def test_should_not_write_any_result_file_when_run_executes(run_action, fixture_config, tmp_path):
    before = set(tmp_path.rglob("*.json"))

    run_action("run", **fixture_config)

    assert set(tmp_path.rglob("*.json")) == before


def test_should_keep_legacy_execute_output_when_unchanged(run_action, fixture_config, tmp_path):
    """Regression: `execute` is byte-compatible with the pre-v1.1 behaviour (snapshot from 0.2.0)."""
    snapshot = json.loads((FIXTURES / "execute_snapshot.json").read_text(encoding="utf-8"))
    out = tmp_path / "out" / "result.json"

    run = run_action(
        "execute", outputPath=str(out), knownLeaflets=[f"{CURRENT}|2026-07-01|2026-07-07"], types=[],
        **fixture_config)

    assert run.returncode == 0
    result = run.result
    assert set(result) == {"outputPath", "count", "hasNew", "leaflets", "fileSize"}
    assert {k: v for k, v in result.items() if k not in ("outputPath", "fileSize")} == snapshot["result"]
    assert result["fileSize"] == out.stat().st_size
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written.pop("source") == fixture_config["pageUrl"]
    assert written == snapshot["fileDoc"]


def test_should_keep_legacy_error_codes_when_execute_fails(run_action, fixture_config, empty_page, tmp_path):
    out = str(tmp_path / "r.json")

    empty = run_action("execute", outputPath=out, **{**fixture_config, "pageUrl": empty_page})
    unreachable = run_action("execute", outputPath=out, **{**fixture_config, "pageUrl": UNREACHABLE})
    missing = run_action("execute")

    assert (empty.returncode, empty.error["code"]) == (4, "NO_LEAFLETS")
    assert (unreachable.returncode, unreachable.error["code"]) == (4, "FETCH_FAILED")
    assert (missing.returncode, missing.error["code"]) == (2, "INVALID_INPUT")


def test_should_keep_legacy_error_line_unchanged_when_execute_is_blocked(run_action, status_server, tmp_path):
    run = run_action("execute", outputPath=str(tmp_path / "r.json"), pageUrl=status_server(403))

    assert run.returncode == 4
    assert run.error["code"] == "FETCH_FAILED"
    assert run.error["message"].startswith("Failed to fetch leaflet page:")
    assert set(run.error) == {"type", "message", "code"}


def test_should_declare_all_actions_with_schemas_when_manifest_is_read():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["specVersion"] == "1.1"
    assert set(manifest["actions"]) == {"spec", "check", "run", "execute", "terminate"}
    for name in ("spec", "check", "run"):
        action = manifest["actions"][name]
        assert action["input"]["type"] == "object", name
        assert action["output"]["type"] == "object", name
    assert manifest["actions"]["run"]["input"]["properties"]["state"]


def test_should_return_only_configured_types_when_several_types_given(run_action, fixture_config):
    both = run_action("run", types=[CURRENT, MAGAZINE, "Other"], **fixture_config).result
    one = run_action("run", types=[MAGAZINE], **fixture_config).result

    assert sorted(_keys(both)) == sorted([f"{CURRENT}|2026-07-01|2026-07-07", f"{MAGAZINE}|2026-07-01|2026-07-07"])
    assert _keys(one) == [f"{MAGAZINE}|2026-07-01|2026-07-07"]
    assert len(one["state"]["seen"]) == 2
