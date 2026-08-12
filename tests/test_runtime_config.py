import gzip
import json
import re
from pathlib import Path

import pytest
import yaml

from hifi_agent.config import validate_config_file
from hifi_agent.exceptions import InputValidationError
from hifi_agent.orchestration.runtime_config import resolve_runtime_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fastq(path: Path) -> Path:
    path.write_text("@read\nACGT\n+\nIIII\n")
    return path


def _native_config(tmp_path: Path) -> Path:
    path = tmp_path / "sample.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_id": "hifi-agent",
                "sample_id": "sample",
                "read_technology": "pacbio_hifi",
                "hifi_reads": [str(_fastq(tmp_path / "reads.fastq"))],
                "outdir": str(tmp_path / "run"),
                "optimization": {
                    "enabled": True,
                    "max_rounds": 2,
                    "max_candidates_per_round": 1,
                    "max_parameter_changes_per_candidate": 1,
                    "decision_mode": "rules_only",
                },
                "execution_budget": {
                    "max_total_assemblies": 3,
                    "max_tool_retries": 1,
                    "max_cpu_hours": 20,
                    "max_walltime_hours": 10,
                    "min_free_disk_gib": 0,
                    "max_llm_calls_per_round": 1,
                    "max_total_llm_calls": 2,
                },
            },
            sort_keys=False,
        )
    )
    return path


def test_native_config_requires_explicit_read_technology(tmp_path: Path) -> None:
    path = _native_config(tmp_path)
    data = yaml.safe_load(path.read_text())
    data.pop("read_technology")
    path.write_text(yaml.safe_dump(data))

    with pytest.raises(InputValidationError, match="read_technology"):
        resolve_runtime_config(path)


def test_runtime_config_records_config_default_and_cli_sources(tmp_path: Path) -> None:
    result = resolve_runtime_config(
        _native_config(tmp_path),
        decision_mode_override="llm_disabled",
    )

    assert result.effective.sample.schema_id == "hifi-agent"
    assert result.effective.read_technology == "pacbio_hifi"
    assert result.effective.optimization.decision_mode == "llm_disabled"
    assert result.source_map["optimization.decision_mode"] == "cli"
    assert result.source_map["optimization.max_rounds"] == "config"
    assert result.source_map["optimization.plateau_rounds"] == "default"
    assert result.source_map["execution_budget.max_cpu_hours"] == "config"
    assert result.plan().maximum_planned_assemblies == 3


@pytest.mark.parametrize(
    ("decision_mode", "require_llm", "strategy"),
    [
        ("rules_only", False, "RULES_ONLY"),
        ("llm_disabled", False, "DETERMINISTIC_NO_LLM"),
        ("hybrid", False, "OPTIONAL_LLM_WITH_DETERMINISTIC_FALLBACK"),
        ("hybrid", True, "REQUIRED_LLM"),
    ],
)
def test_all_optimization_fields_compile_to_production_policy(
    tmp_path: Path,
    decision_mode: str,
    require_llm: bool,
    strategy: str,
) -> None:
    path = _native_config(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["optimization"].update(
        {
            "enabled": True,
            "max_rounds": 2,
            "max_candidates_per_round": 2,
            "max_parameter_changes_per_candidate": 1,
            "plateau_rounds": 1,
            "decision_mode": decision_mode,
            "require_llm": require_llm,
            "confirm_risk_level": "high",
            "retain_all_attempts": True,
        }
    )
    path.write_text(yaml.safe_dump(data))

    policy = resolve_runtime_config(path).effective.optimization_policy()

    assert policy.enabled is True
    assert policy.round_indices == (1, 2)
    assert policy.candidate_indices == (1, 2)
    assert policy.minimum_candidate_runs == 0
    assert policy.permits_parameter_change_count(1)
    assert not policy.permits_parameter_change_count(2)
    assert policy.plateau_reached(1)
    assert policy.decision_strategy == strategy
    assert policy.confirmation_risk_levels == ("high",)
    assert policy.retain_all_attempts is True


def test_unknown_runtime_fields_are_rejected(tmp_path: Path) -> None:
    path = _native_config(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["unknown_runtime"] = {"max_candidates_per_round": 2}
    path.write_text(yaml.safe_dump(data))

    with pytest.raises(InputValidationError, match="unknown_runtime"):
        resolve_runtime_config(path)


def test_require_llm_is_rejected_outside_hybrid_mode(tmp_path: Path) -> None:
    path = _native_config(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["optimization"].update({"decision_mode": "rules_only", "require_llm": True})
    path.write_text(yaml.safe_dump(data))

    with pytest.raises(InputValidationError, match="requires decision_mode=hybrid"):
        resolve_runtime_config(path)


def test_minimum_candidate_run_requires_an_enabled_round(tmp_path: Path) -> None:
    path = _native_config(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["optimization"].update({"minimum_candidate_runs": 1, "enabled": False, "max_rounds": 0})
    path.write_text(yaml.safe_dump(data))

    with pytest.raises(InputValidationError, match="minimum_candidate_runs"):
        resolve_runtime_config(path)


@pytest.mark.parametrize(
    ("enabled", "rounds", "candidates", "budget", "expected"),
    [
        (False, 0, 1, 7, 1),
        (True, 1, 1, 7, 2),
        (True, 3, 2, 7, 7),
        (True, 3, 2, 4, 4),
    ],
)
def test_maximum_assembly_plan_honors_round_candidate_and_global_bounds(
    tmp_path: Path,
    enabled: bool,
    rounds: int,
    candidates: int,
    budget: int,
    expected: int,
) -> None:
    path = _native_config(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["optimization"].update(
        {
            "enabled": enabled,
            "max_rounds": rounds,
            "max_candidates_per_round": candidates,
        }
    )
    data["execution_budget"]["max_total_assemblies"] = budget
    path.write_text(yaml.safe_dump(data))

    assert resolve_runtime_config(path).effective.maximum_planned_assemblies() == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_total_assemblies", 8),
        ("min_free_disk_gib", -1),
        ("max_llm_calls_per_round", 2),
        ("max_total_llm_calls", 4),
    ],
)
def test_budget_boundaries_are_enforced(
    tmp_path: Path,
    field: str,
    value: int,
) -> None:
    path = _native_config(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["execution_budget"][field] = value
    path.write_text(yaml.safe_dump(data))

    with pytest.raises(InputValidationError, match=field):
        resolve_runtime_config(path)


def test_runtime_audit_outputs_are_only_written_when_requested(tmp_path: Path) -> None:
    path = _native_config(tmp_path)
    preview = resolve_runtime_config(path, write_outputs=False)
    assert not preview.effective_config_path.exists()
    assert not preview.config_sources_path.exists()

    materialized = resolve_runtime_config(path, write_outputs=True)

    assert materialized.effective_config_path.is_file()
    assert materialized.config_sources_path.is_file()
    effective = json.loads(materialized.effective_config_path.read_text())
    sources = json.loads(materialized.config_sources_path.read_text())
    assert effective["schema_id"] == "hifi-agent"
    assert sources["sources"]["read_technology"] == "config"


def test_validation_receipt_marks_technology_as_declared_not_inferred(tmp_path: Path) -> None:
    result = validate_config_file(_native_config(tmp_path))
    receipt = json.loads(result.validation_receipt.read_text())

    assert receipt["read_technology"] == "pacbio_hifi"
    assert receipt["read_technology_source"] == "USER_DECLARED_NOT_INFERRED"


def test_repository_generic_sample_is_a_valid_native_config(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "Data"
    sample_root = data_root / "sample"
    sample_root.mkdir(parents=True)
    reads = sample_root / "reads.fastq.gz"
    with gzip.open(reads, "wt") as handle:
        handle.write("@read\nACGT\n+\nIIII\n")
    runtime_data = yaml.safe_load((PROJECT_ROOT / "configs/runtime.yaml").read_text())
    runtime_data["paths"] = {
        "data_root": str(data_root),
        "output_root": str(tmp_path / "results"),
        "cache_root": str(tmp_path / "cache"),
    }
    runtime_data["execution_budget"]["min_free_disk_gib"] = 0
    runtime = tmp_path / "runtime.yaml"
    runtime.write_text(yaml.safe_dump(runtime_data))
    sample_data = yaml.safe_load((PROJECT_ROOT / "configs/sample.yaml").read_text())
    sample_data["runtime_config"] = str(runtime)
    sample = tmp_path / "sample.yaml"
    sample.write_text(yaml.safe_dump(sample_data))

    result = resolve_runtime_config(sample, write_outputs=False)

    assert result.effective.sample.schema_id == "hifi-agent"
    assert result.effective.sample.hifi_reads[0].name == "reads.fastq.gz"
    assert result.effective.maximum_planned_assemblies() == 2
    assert result.source_map["species_name"] == "sample"
    assert result.source_map["resources.max_threads"] == "runtime"


def test_readme_yaml_example_is_schema_valid(tmp_path: Path) -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()
    match = re.search(
        r"## 两层配置.*?```yaml\n(?P<runtime>.*?)\n```.*?```yaml\n(?P<sample>.*?)\n```",
        readme,
        re.DOTALL,
    )
    assert match is not None
    data_root = tmp_path / "Data"
    data_root.mkdir()
    _fastq(data_root / "readme.fastq")
    runtime_data = yaml.safe_load(match.group("runtime"))
    runtime_data["paths"] = {
        "data_root": str(data_root),
        "output_root": str(tmp_path / "results"),
        "cache_root": str(tmp_path / "cache"),
    }
    runtime_data["execution_budget"]["min_free_disk_gib"] = 0
    runtime = tmp_path / "runtime.yaml"
    runtime.write_text(yaml.safe_dump(runtime_data))
    sample_data = yaml.safe_load(match.group("sample"))
    sample_data["runtime_config"] = str(runtime)
    sample_data["hifi_reads"] = ["readme.fastq"]
    sample = tmp_path / "sample.yaml"
    sample.write_text(yaml.safe_dump(sample_data))

    result = resolve_runtime_config(sample)

    assert result.effective.sample.schema_id == "hifi-agent"
