from pathlib import Path

from hifi_agent.executors.nextflow import _write_hifiasm_bin_reuse_manifest


def test_hifiasm_reuse_manifest_declares_only_matching_prefix_bins(tmp_path: Path) -> None:
    bins = tmp_path / "published"
    bins.mkdir()
    expected = [
        bins / "sample.baseline.ec.bin",
        bins / "sample.baseline.ovlp.source.bin",
        bins / "sample.baseline.ovlp.reverse.bin",
    ]
    for index, path in enumerate(expected):
        path.write_bytes(f"bin-{index}".encode())
    (bins / "other.baseline.ec.bin").write_bytes(b"other")
    output = tmp_path / "reuse.tsv"

    _write_hifiasm_bin_reuse_manifest(output, bins, "sample.baseline")

    rows = output.read_text().splitlines()
    assert rows[0] == "path\tsha256\tbytes"
    assert len(rows) == 4
    assert {Path(row.split("\t")[0]).name for row in rows[1:]} == {path.name for path in expected}
    assert all(len(row.split("\t")[1]) == 64 for row in rows[1:])
