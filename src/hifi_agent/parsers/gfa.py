"""Minimal, deterministic GFA segment-to-FASTA conversion for validation fixtures."""

from __future__ import annotations

from pathlib import Path


def gfa_segments_to_fasta(gfa: Path, fasta: Path) -> int:
    """Write GFA `S` records with literal sequence and return the segment count.

    Production assembly conversion remains delegated to versioned gfatools. This deliberately
    small parser exists for portable integration tests and rejects missing (`*`) sequences.
    """
    count = 0
    with gfa.open() as source, fasta.open("w") as output:
        for line_number, line in enumerate(source, start=1):
            if not line.startswith("S\t"):
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 3 or not fields[1] or fields[2] == "*":
                raise ValueError(f"Invalid literal GFA segment at line {line_number}")
            output.write(f">{fields[1]}\n{fields[2]}\n")
            count += 1
    if count == 0:
        raise ValueError("GFA contains no literal segment records")
    return count
