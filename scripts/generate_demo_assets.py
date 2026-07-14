"""Generate small reproducible GIF documentation assets without third-party libraries."""

from __future__ import annotations

import gzip
import struct
import zlib
from pathlib import Path

WIDTH = 720
HEIGHT = 400
SCALE = 2
FONT_PATH = Path("/usr/share/consolefonts/Lat38-Terminus12x6.psf.gz")
PALETTE = bytes(
    [
        12,
        18,
        28,
        226,
        232,
        240,
        28,
        78,
        121,
        89,
        214,
        141,
    ]
)

SLIDES = [
    (
        "01 / PURPOSE",
        [
            "HIFI AGENT V1.0.0",
            "CONSTRAINED PACBIO HIFI ASSEMBLY AGENT",
            "",
            "RULES DECIDE. LLM EXPLAINS.",
        ],
    ),
    (
        "02 / QUICKSTART",
        [
            "$ HIFI-AGENT --VERSION",
            "HIFI-AGENT 1.0.0",
            "",
            "$ HIFI-AGENT DEMO /TMP/HIFI-AGENT-DEMO",
        ],
    ),
    (
        "03 / NORMAL",
        [
            "SCENARIO: NORMAL_HIFI_METRICS",
            "EXPECTED: BASELINE",
            "OBSERVED: BASELINE",
            "ACTION: ACCEPT_DEFAULT_PARAMETERS",
            "RESULT: PASS",
        ],
    ),
    (
        "04 / LOW COVERAGE",
        [
            "SCENARIO: LOW_COVERAGE_DOWNSAMPLE",
            "COVERAGE: 10X",
            "ACTION: STOP_LOW_COVERAGE_SEARCH",
            "NO BLIND PARAMETER SEARCH",
            "RESULT: PASS",
        ],
    ),
    (
        "05 / BOUNDED RETRY",
        [
            "SIZE RATIO: 1.40   BUSCO DUP: 15.0%",
            "ACTION: PROPOSE_STRONGER_PURGE",
            "CANDIDATE: PURGE_SIMILARITY = 0.5",
            "CANDIDATES: 1 OF MAX 2",
            "RESULT: PASS",
        ],
    ),
    (
        "06 / METRIC CONFLICT",
        [
            "ASSEMBLY SIZE LOSS + BUSCO DUPLICATION",
            "ACTION: REQUIRE_HUMAN_REVIEW",
            "DECISION: STOP",
            "CANDIDATES: 0",
            "RESULT: PASS",
        ],
    ),
    (
        "07 / TOOL FAILURE",
        [
            "POST-QC TOOL FAILURE INJECTED",
            "ACTION: STOP_EVALUATION_INCOMPLETE",
            "ENGINEERING != BIOLOGICAL FAILURE",
            "RESULT: PASS",
        ],
    ),
    (
        "08 / REAL CANDIDA",
        [
            "READ ACCESSION: SRR23724250",
            "REFERENCE: CP128823.1",
            "ASSEMBLY: 22,812,604 BP",
            "N50: 1,247,647 BP   BUSCO C: 98.2%",
        ],
    ),
    (
        "09 / WHY KEEP OR CHANGE",
        [
            "SIZE RATIO 1.573 BUT BUSCO DUP ONLY 0.8%",
            "EVIDENCE DOES NOT SUPPORT BLIND PURGING",
            "ACTION: REVIEW_GENOME_SIZE_ESTIMATE",
            "SAFE STOP IS A SUCCESS",
        ],
    ),
    (
        "10 / RAG SAFETY",
        [
            "RULES-ONLY DECISION: STOP / REVIEW",
            "RULES + RAG: STOP_AND_REVIEW",
            "DECISION CHANGED: FALSE",
            "CANDIDATE PARAMETERS CHANGED: FALSE",
        ],
    ),
    (
        "11 / ABLATION",
        [
            "N50-ONLY WOULD SELECT A BAD CANDIDATE",
            "FULL COMPARATOR DETECTS COMPLETENESS LOSS",
            "OUTCOME: STOP_METRIC_CONFLICT",
            "N50 NEVER OVERRIDES HARD QUALITY GATES",
        ],
    ),
    (
        "12 / ACCEPTANCE",
        [
            "10 / 10 SCENARIOS PASS",
            "NONEXISTENT PARAMETER RATE: 0%",
            "REPEAT CONSISTENCY: 100%",
            "SAFETY COVERAGE: 82.06%",
            "LOCAL RELEASE CANDIDATE: PASS",
        ],
    ),
]


def _font() -> tuple[int, int, list[bytes]]:
    data = gzip.open(FONT_PATH, "rb").read()
    magic, _version, header_size, _flags, length, char_size, height, width = struct.unpack(
        "<8I", data[:32]
    )
    if magic != 0x864AB572 or width > 8:
        raise ValueError("Expected a PSF2 font no wider than eight pixels")
    start = header_size
    glyphs = [
        data[start + index * char_size : start + (index + 1) * char_size] for index in range(length)
    ]
    return width, height, glyphs


def _draw_text(
    pixels: bytearray,
    text: str,
    x: int,
    y: int,
    color: int,
    font_width: int,
    font_height: int,
    glyphs: list[bytes],
) -> None:
    for character in text:
        glyph = glyphs[ord(character)] if ord(character) < len(glyphs) else glyphs[ord("?")]
        for row in range(font_height):
            bits = glyph[row]
            for column in range(font_width):
                if bits & (0x80 >> column):
                    for dy in range(SCALE):
                        for dx in range(SCALE):
                            px = x + column * SCALE + dx
                            py = y + row * SCALE + dy
                            if 0 <= px < WIDTH and 0 <= py < HEIGHT:
                                pixels[py * WIDTH + px] = color
        x += (font_width + 1) * SCALE


def _frame(title: str, lines: list[str]) -> bytes:
    font_width, font_height, glyphs = _font()
    pixels = bytearray(WIDTH * HEIGHT)
    for y in range(72):
        pixels[y * WIDTH : (y + 1) * WIDTH] = bytes([2]) * WIDTH
    _draw_text(pixels, title, 30, 24, 1, font_width, font_height, glyphs)
    for index, line in enumerate(lines):
        color = 3 if "PASS" in line or "FALSE" in line else 1
        _draw_text(
            pixels,
            line,
            30,
            105 + index * 48,
            color,
            font_width,
            font_height,
            glyphs,
        )
    _draw_text(
        pixels,
        "GENERATED FROM VERSIONED TEST AND REPORT ARTIFACTS",
        30,
        365,
        1,
        font_width,
        font_height,
        glyphs,
    )
    return bytes(pixels)


def _lzw(indices: bytes) -> bytes:
    minimum_size = 2
    clear = 1 << minimum_size
    end = clear + 1
    dictionary: dict[tuple[int, ...], int] = {(index,): index for index in range(clear)}
    next_code = end + 1
    code_size = minimum_size + 1
    emitted: list[tuple[int, int]] = [(clear, code_size)]
    prefix = (indices[0],)
    for value in indices[1:]:
        combined = (*prefix, value)
        if combined in dictionary:
            prefix = combined
            continue
        emitted.append((dictionary[prefix], code_size))
        if next_code < 4096:
            dictionary[combined] = next_code
            next_code += 1
            if next_code == 1 << code_size and code_size < 12:
                code_size += 1
        else:
            emitted.append((clear, code_size))
            dictionary = {(index,): index for index in range(clear)}
            next_code = end + 1
            code_size = minimum_size + 1
        prefix = (value,)
    emitted.extend(((dictionary[prefix], code_size), (end, code_size)))
    packed = bytearray()
    buffer = 0
    bits = 0
    for code, size in emitted:
        buffer |= code << bits
        bits += size
        while bits >= 8:
            packed.append(buffer & 0xFF)
            buffer >>= 8
            bits -= 8
    if bits:
        packed.append(buffer & 0xFF)
    blocks = bytearray([minimum_size])
    for offset in range(0, len(packed), 255):
        block = packed[offset : offset + 255]
        blocks.append(len(block))
        blocks.extend(block)
    blocks.append(0)
    return bytes(blocks)


def _gif(frames: list[bytes], delays: list[int]) -> bytes:
    output = bytearray(b"GIF89a")
    output.extend(struct.pack("<HHBBB", WIDTH, HEIGHT, 0x81, 0, 0))
    output.extend(PALETTE)
    for pixels, delay in zip(frames, delays, strict=True):
        output.extend(b"\x21\xf9\x04\x04")
        output.extend(struct.pack("<H", delay))
        output.extend(b"\x00\x00")
        output.extend(b"\x2c\x00\x00\x00\x00")
        output.extend(struct.pack("<HHB", WIDTH, HEIGHT, 0))
        output.extend(_lzw(pixels))
    output.append(0x3B)
    return bytes(output)


def _png(pixels: bytes) -> bytes:
    """Encode one indexed frame as a standard RGB PNG for report previews."""
    rows = bytearray()
    colors = [PALETTE[index : index + 3] for index in range(0, len(PALETTE), 3)]
    for y in range(HEIGHT):
        rows.append(0)
        for value in pixels[y * WIDTH : (y + 1) * WIDTH]:
            rows.extend(colors[value])

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    output = Path("docs/assets")
    output.mkdir(parents=True, exist_ok=True)
    frames = [_frame(title, lines) for title, lines in SLIDES]
    (output / "hifi_agent_demo.gif").write_bytes(_gif(frames, [1800] * len(frames)))
    (output / "hifi_agent_demo_preview.png").write_bytes(_png(frames[0]))
    real = _frame(
        "REAL REPORT SNAPSHOT / CANDIDA ALBICANS",
        [
            "READS: SRR23724250   REFERENCE: CP128823.1",
            "ASSEMBLY SIZE: 22,812,604 BP",
            "CONTIG N50: 1,247,647 BP",
            "BUSCO COMPLETE: 98.2%   DUPLICATED: 0.8%",
            "ACTION: REVIEW_GENOME_SIZE_ESTIMATE",
        ],
    )
    (output / "candida_report_snapshot.gif").write_bytes(_gif([real], [0]))
    (output / "candida_report_snapshot.png").write_bytes(_png(real))


if __name__ == "__main__":
    main()
