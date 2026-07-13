from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = PROJECT_ROOT / "workflow"


def test_phase3_workflow_files_exist() -> None:
    expected_files = [
        WORKFLOW_DIR / "main.nf",
        WORKFLOW_DIR / "nextflow.config",
        WORKFLOW_DIR / "conf" / "base.config",
        WORKFLOW_DIR / "conf" / "local.config",
    ]

    for path in expected_files:
        assert path.is_file(), path


def test_phase3_main_declares_minimal_processes() -> None:
    main_nf = (WORKFLOW_DIR / "main.nf").read_text()

    assert "nextflow.enable.dsl = 2" in main_nf
    assert "process FASTQ_PROBE" in main_nf
    assert "process WRITE_RUN_MANIFEST" in main_nf
    assert "process SEQKIT_STATS" in main_nf
    assert "process NANOPLOT" in main_nf
    assert "process KMER_COUNT" in main_nf
    assert "process RAW_METRICS" in main_nf
    assert "process HIFIASM_BASELINE" in main_nf
    assert "process QUAST" in main_nf
    assert "process BUSCO_POST_QC" in main_nf
    assert "process MERQURY_POST_QC" in main_nf
    assert "process MAPPING_POST_QC" in main_nf
    assert "process ASSEMBLY_METRICS" in main_nf
    assert "workflow POST_QC_ONLY" in main_nf
    assert "Channel" in main_nf
    assert "checkIfExists: true" in main_nf
    assert "reads_manifest" in main_nf
    assert "NanoPlot" in main_nf
    assert "meryl" in main_nf
    assert "hifiasm" in main_nf
    assert "gfatools" in main_nf
    assert "*.bin" in main_nf
    assert "--auto-lineage-euk" in main_nf
    assert "map-hifi" in main_nf
    assert "coverage_windows.tsv" in main_nf
    assert "timeout --signal=TERM" in main_nf


def test_local_profile_enables_execution_artifacts() -> None:
    local_config = (WORKFLOW_DIR / "conf" / "local.config").read_text()

    for artifact in ["timeline.html", "report.html", "trace.txt", "dag.html"]:
        assert artifact in local_config

    assert "workDir" in local_config
    assert "name = 'local'" in local_config


def test_large_local_host_resource_policy() -> None:
    base_config = (WORKFLOW_DIR / "conf" / "base.config").read_text()

    assert "max_threads = 480" in base_config
    assert "max_memory_gb = 960" in base_config
    assert "Math.min(256, params.max_threads as int)" in base_config
    assert "withName: NANOPLOT" in base_config
    assert "withName: MERQURY_POST_QC" in base_config
    assert "withName: MAPPING_POST_QC" in base_config
