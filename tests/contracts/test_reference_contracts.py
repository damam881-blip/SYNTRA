"""Verification tests for the byte-preserved TASK-04 and TASK-05 reference contracts.

These tests exercise the approved reference schemas, fixtures, wire vocabulary, and
documented model corrections. They do not alter the imported reference artifacts.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
TASK04 = ROOT / "contracts" / "reference" / "task04"
TASK05 = ROOT / "contracts" / "reference" / "task05"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_entries(root: Path, manifest_name: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in (root / manifest_name).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and len(parts[0]) == 64:
            relative = parts[1]
            if relative.startswith("./"):
                relative = relative[2:]
            entries.append((parts[0], relative))
    return entries


def _load_check_model():
    module_path = TASK04 / "tools" / "check_model.py"
    spec = importlib.util.spec_from_file_location("task04_check_model", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_manifests_are_intact() -> None:
    manifests = (
        (TASK04, "MANIFEST.sha256"),
        (TASK05, "manifest.sha256"),
    )
    for root, manifest_name in manifests:
        entries = _manifest_entries(root, manifest_name)
        assert entries
        for expected_digest, relative_path in entries:
            actual_digest = hashlib.sha256((root / relative_path).read_bytes()).hexdigest()
            assert actual_digest == expected_digest, relative_path


def test_task04_schema_is_valid_and_fixtures_validate() -> None:
    schema = _load_json(TASK04 / "schemas" / "topology-model-v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)

    fixtures = sorted((TASK04 / "fixtures").glob("rt-*.json"))
    assert len(fixtures) == 5
    for fixture_path in fixtures:
        document = _load_json(fixture_path)
        errors = list(validator.iter_errors(document))
        assert not errors, f"{fixture_path.name}: {errors[:3]}"


def test_task04_rejects_unsupported_schema_version() -> None:
    schema = _load_json(TASK04 / "schemas" / "topology-model-v1.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    document = _load_json(TASK04 / "fixtures" / "rt-01.json")
    document["schema_version"] = "2.0.0"

    assert list(validator.iter_errors(document))


def test_task04_rejects_unknown_top_level_field() -> None:
    schema = _load_json(TASK04 / "schemas" / "topology-model-v1.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    document = _load_json(TASK04 / "fixtures" / "rt-01.json")
    document["invented_field"] = "not part of the model"

    assert list(validator.iter_errors(document))


def test_task04_unicode_normalization_matches_approved_rule() -> None:
    module = _load_check_model()

    assert module.norm("  PC1  ") == "pc1"
    assert module.norm("\u3000PC1\u00a0") == "pc1"
    assert module.norm("straße") == "strasse"
    assert module.norm("\x1cPC1") == "\x1cpc1"
    assert module.norm("\uff30\uff23\uff11") != "pc1"


def test_task04_accepts_admin_disabled_cabled_interface() -> None:
    module = _load_check_model()
    document = _load_json(TASK04 / "fixtures" / "rt-04.json")

    connected_ids = {
        interface_id
        for connection in document["connections"]
        for interface_id in (
            connection["interface_a_id"],
            connection["interface_b_id"],
        )
    }
    interface = next(
        item for item in document["interfaces"] if item["interface_id"] in connected_ids
    )
    interface["admin_state"] = "DISABLED"

    module.failures.clear()
    module.checks = 0
    module.validate_document(document, "rt-04 admin-disabled")
    assert module.failures == [], module.failures


def test_task04_accepts_route_sequence_gap_after_deletion() -> None:
    module = _load_check_model()
    document = _load_json(TASK04 / "fixtures" / "rt-04.json")

    module.route_sequence_gap(document)
    assert document["static_routes"][0]["route_sequence"] == 5

    module.failures.clear()
    module.checks = 0
    module.validate_document(document, "rt-04 route-sequence-gap")
    assert module.failures == [], module.failures


def test_task04_router_interfaces_are_in_separate_l2_domains() -> None:
    module = _load_check_model()
    document = _load_json(TASK04 / "fixtures" / "rt-04.json")

    domain_of: dict[str, int] = {}
    for index, domain in enumerate(module.l2_domains(document)):
        for interface_id in domain:
            domain_of[interface_id] = index

    routers = [device for device in document["devices"] if device["kind"] == "ROUTER"]
    assert routers
    for router in routers:
        router_interfaces = [
            interface["interface_id"]
            for interface in document["interfaces"]
            if interface["device_id"] == router["device_id"]
        ]
        assert len({domain_of[interface_id] for interface_id in router_interfaces}) == len(
            router_interfaces
        )


def test_task04_configuration_digest_verifier_passes() -> None:
    result = subprocess.run(
        [str(PYTHON), str(TASK04 / "tools" / "configuration_digest.py"), "--verify"],
        cwd=TASK04,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "reference digest: ba18d012468c378746d93872281c15b4b5c132970a45e01f53657e3bbbd4642f" in result.stdout


def test_task04_model_verifier_passes() -> None:
    result = subprocess.run(
        [str(PYTHON), str(TASK04 / "tools" / "check_model.py")],
        cwd=TASK04,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "checks run: 666" in result.stdout


def test_task04_boundary_verifier_passes() -> None:
    result = subprocess.run(
        [str(PYTHON), str(TASK04 / "tools" / "test_limits.py")],
        cwd=TASK04,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "checks: 52   failed: 0" in result.stdout


def test_task05_schema_is_valid_and_examples_validate() -> None:
    schema = _load_json(TASK05 / "schemas" / "task05-contract-v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)

    examples = sorted((TASK05 / "examples").glob("*.json"))
    assert len(examples) == 10
    for example_path in examples:
        document = _load_json(example_path)
        errors = list(validator.iter_errors(document))
        assert not errors, f"{example_path.name}: {errors[:3]}"


def test_task05_rejects_unsupported_contract_version() -> None:
    schema = _load_json(TASK05 / "schemas" / "task05-contract-v1.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    document = _load_json(TASK05 / "examples" / "ping_command.json")
    document["contract_version"] = "2.0.0"

    assert list(validator.iter_errors(document))


def test_task05_rejects_unknown_top_level_field() -> None:
    schema = _load_json(TASK05 / "schemas" / "task05-contract-v1.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    document = _load_json(TASK05 / "examples" / "ping_command.json")
    document["invented_field"] = "not part of the contract"

    assert list(validator.iter_errors(document))


def test_task05_wire_vocabulary_is_frozen_and_matches_engine_diagnostics() -> None:
    from app.engine.diagnostics.codes import DiagnosticCode

    vocabulary = _load_json(TASK05 / "schemas" / "wire-vocabulary-v1.json")
    assert vocabulary["contract_version"] == "1.0.0"
    assert set(vocabulary["diagnostic_codes"]) == {
        diagnostic_code.value for diagnostic_code in DiagnosticCode
    }


def test_task05_rejects_unknown_diagnostic_code() -> None:
    schema = _load_json(TASK05 / "schemas" / "task05-contract-v1.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    document = _load_json(TASK05 / "examples" / "ping_failure_no_arp.json")
    document["diagnostics"][0]["code"] = "INVENTED_FAILURE"

    assert list(validator.iter_errors(document))


def test_task05_rejects_unknown_event_kind() -> None:
    schema = _load_json(TASK05 / "schemas" / "task05-contract-v1.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    document = _load_json(TASK05 / "examples" / "ping_success.json")
    document["events"][0]["kind"] = "INVENTED_PACKET_TELEPORT"

    assert list(validator.iter_errors(document))


def test_task05_contract_verifier_passes_without_modifying_reference(
    tmp_path: Path,
) -> None:
    disposable_copy = tmp_path / "task05"
    shutil.copytree(TASK05, disposable_copy)

    result = subprocess.run(
        [str(PYTHON), str(disposable_copy / "tools" / "verify_contract.py")],
        cwd=disposable_copy,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TOTAL: 58 PASS / 0 FAIL" in result.stdout
