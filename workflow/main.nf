nextflow.enable.dsl = 2

process FASTQ_PROBE {
    tag "${sample_id}"
    label 'small'

    publishDir "${params.outdir}/01_pre_qc/fastq_probe",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(reads)

    output:
    path 'fastq_probe.tsv', emit: metrics
    path 'fastq_probe.log', emit: log

    script:
    """
    set -euo pipefail

    printf 'sample_id\tfile\trecords\tbases\tstatus\\n' > fastq_probe.tsv
    : > fastq_probe.log

    for read in ${reads}; do
        case "\$read" in
            *.gz) reader="gzip -cd --" ;;
            *) reader="cat --" ;;
        esac

        \$reader "\$read" | awk -v sample_id="${sample_id}" -v file="\$read" '
            NR % 4 == 1 {
                if (substr(\$0, 1, 1) != "@") {
                    printf("invalid FASTQ header at line %d in %s\\n", NR, file) > "/dev/stderr"
                    exit 2
                }
                records++
                next
            }
            NR % 4 == 2 {
                bases += length(\$0)
                next
            }
            NR % 4 == 3 {
                if (substr(\$0, 1, 1) != "+") {
                    printf("invalid FASTQ separator at line %d in %s\\n", NR, file) > "/dev/stderr"
                    exit 2
                }
                next
            }
            END {
                if (NR == 0 || NR % 4 != 0 || records == 0) {
                    printf("incomplete or empty FASTQ in %s\\n", file) > "/dev/stderr"
                    exit 2
                }
                printf("%s\\t%s\\t%d\\t%d\\tPASS\\n", sample_id, file, records, bases)
            }
        ' >> fastq_probe.tsv 2>> fastq_probe.log
    done

    printf 'FASTQ probe completed for sample %s.\\n' "${sample_id}" >> fastq_probe.log
    """
}

process SEQKIT_STATS {
    tag "${sample_id}"
    label 'small'

    publishDir "${params.outdir}/01_pre_qc/seqkit",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(reads)

    output:
    tuple val(sample_id), path('seqkit_stats.tsv'), emit: stats

    script:
    """
    set -euo pipefail

    if ! command -v seqkit >/dev/null 2>&1; then
        printf 'seqkit executable not found\\n' >&2
        exit 127
    fi
    seqkit stats -a -T -j "${task.cpus}" ${reads} > seqkit_stats.tsv
    """
}

process NANOPLOT {
    tag "${sample_id}"
    label 'small'

    publishDir "${params.outdir}/01_pre_qc/nanoplot",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(reads)

    output:
    tuple val(sample_id), path('NanoStats.txt'), emit: nanostats
    path '*.html', optional: true, emit: plots
    path 'NanoPlot-data.tsv.gz', optional: true, emit: data

    script:
    """
    set -euo pipefail

    NanoPlot \\
        --fastq ${reads} \\
        --outdir . \\
        --threads "${task.cpus}" \\
        --tsv_stats \\
        --raw \\
        --no_static \\
        --N50
    """
}

process KMER_COUNT {
    tag "${sample_id}"
    label 'medium'

    publishDir "${params.outdir}/01_pre_qc/kmer",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(reads)

    output:
    tuple val(sample_id), path('read.meryl'), path('kmer_histogram.tsv'), emit: histogram

    script:
    """
    set -euo pipefail

    if ! command -v meryl >/dev/null 2>&1; then
        printf 'meryl executable not found\\n' >&2
        exit 127
    fi
    MERYL_BIN="\$(command -v meryl)"

    "\$MERYL_BIN" count \\
        k="${params.kmer_k ?: 21}" \\
        threads="${task.cpus}" \\
        memory="${task.memory.toGiga() as int}" \\
        output read.meryl \\
        ${reads}
    "\$MERYL_BIN" histogram read.meryl > kmer_histogram.tsv
    """
}

process GENOMESCOPE_SUMMARY {
    tag "${sample_id}"
    label 'small'

    publishDir "${params.outdir}/01_pre_qc/kmer",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(meryl_db), path(histogram)

    output:
    tuple val(sample_id), path(histogram), path('genomescope_summary.tsv'), emit: summary
    path 'genomescope', optional: true, emit: genomescope_output

    script:
    """
    set -euo pipefail

    python -m hifi_agent.workflow_tools run-genomescope \\
        --histogram "${histogram}" \\
        --k "${params.kmer_k ?: 21}" \\
        --output-dir genomescope \\
        --summary genomescope_summary.tsv
    """
}

process KMER_METRICS {
    tag "${sample_id}"
    label 'small'

    publishDir "${params.outdir}/01_pre_qc/kmer",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(histogram), path(genomescope_summary)

    output:
    tuple val(sample_id), path('kmer_metrics.json'), emit: metrics

    script:
    """
    set -euo pipefail

    python -m hifi_agent.workflow_tools kmer-metrics \\
        --sample-id "${sample_id}" \\
        --histogram "${histogram}" \\
        --genomescope-summary "${genomescope_summary}" \\
        --expected-genome-size "${params.expected_genome_size ?: ''}" \\
        --kmer-source "${params.kmer_source ?: 'same_data_advisory'}" \\
        --low-coverage-peak-threshold "${params.kmer_low_coverage_peak_threshold ?: 10.0}" \\
        --output kmer_metrics.json
    """
}

process RAW_METRICS {
    tag "${sample_id}"
    label 'small'

    publishDir "${params.outdir}/01_pre_qc",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(seqkit_stats), path(nanostats), path(kmer_metrics)

    output:
    tuple val(sample_id), path('raw_metrics.json'), emit: raw

    script:
    """
    set -euo pipefail

    python -m hifi_agent.workflow_tools raw-metrics \\
        --sample-id "${sample_id}" \\
        --seqkit-stats "${seqkit_stats}" \\
        --nanostats "${nanostats}" \\
        --kmer-metrics "${kmer_metrics}" \\
        --expected-genome-size "${params.expected_genome_size ?: ''}" \\
        --output raw_metrics.json
    """
}

process HIFIASM_ASSEMBLY {
    tag "${sample_id}:${params.assembly_run_id ?: 'baseline'}"
    label 'assembly'

    publishDir (params.assembly_publish_dir ?: "${params.outdir}/02_assembly/${params.assembly_run_id ?: 'baseline'}"),
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(reads), path(raw_metrics)

    output:
    tuple val(sample_id), path('metadata/assembly_manifest.json'), path("fasta/${params.assembly_run_id ?: 'baseline'}.primary.fa"), emit: baseline
    path 'logs', emit: logs
    path 'gfa', emit: gfa
    path 'fasta', emit: fasta
    path 'bins', optional: true, emit: bins
    path 'metadata', emit: metadata

    script:
    """
    set -euo pipefail

    PREFIX="${sample_id}.${params.assembly_run_id ?: 'baseline'}"
    mkdir -p logs gfa fasta bins metadata

    if ! command -v hifiasm >/dev/null 2>&1; then
        printf 'hifiasm executable not found\\n' >&2
        exit 127
    fi
    HIFIASM_BIN="\$(command -v hifiasm)"

    if ! command -v gfatools >/dev/null 2>&1; then
        printf 'gfatools executable not found\\n' >&2
        exit 127
    fi
    GFATOOLS_BIN="\$(command -v gfatools)"

    "\$HIFIASM_BIN" --version > metadata/hifiasm.version.txt
    "\$GFATOOLS_BIN" version > metadata/gfatools.version.txt 2>&1 || true

    PARAMETER_ARGS=()
    PARAMETER_ARGS=(-l "${params.hifiasm_purge_level == null ? 3 : params.hifiasm_purge_level}" -s "${params.hifiasm_purge_similarity == null ? 0.55 : params.hifiasm_purge_similarity}")
    if [ -n "${params.hifiasm_hom_cov ?: ''}" ]; then
        PARAMETER_ARGS+=(--hom-cov "${params.hifiasm_hom_cov ?: ''}")
    fi
    if [ "${params.hifiasm_disable_post_join == null ? false : params.hifiasm_disable_post_join}" = "true" ]; then
        PARAMETER_ARGS+=(-u0)
    fi

    printf '%q ' "\$HIFIASM_BIN" -o "\$PREFIX" -t "${task.cpus}" "\${PARAMETER_ARGS[@]}" ${reads} > metadata/hifiasm_command.txt
    printf '\\n' >> metadata/hifiasm_command.txt

    if [ -x /usr/bin/time ]; then
        /usr/bin/time -v -o logs/hifiasm.time.txt \\
            "\$HIFIASM_BIN" -o "\$PREFIX" -t "${task.cpus}" "\${PARAMETER_ARGS[@]}" ${reads} \\
            > logs/hifiasm.stdout 2> logs/hifiasm.stderr
    else
        "\$HIFIASM_BIN" -o "\$PREFIX" -t "${task.cpus}" "\${PARAMETER_ARGS[@]}" ${reads} \\
            > logs/hifiasm.stdout 2> logs/hifiasm.stderr
        printf 'time_report_unavailable\\n' > logs/hifiasm.time.txt
    fi

    find . -maxdepth 1 -type f -name "\${PREFIX}*.gfa" -exec mv {} gfa/ \\;
    find . -maxdepth 1 -type f -name "\${PREFIX}*.bin" -exec mv {} bins/ \\;

    convert_gfa() {
        gfa_path="\$1"
        fasta_path="\$2"
        label="\$3"
        if [ ! -s "\$gfa_path" ]; then
            printf 'Required %s GFA is missing or empty: %s\\n' "\$label" "\$gfa_path" >&2
            exit 2
        fi
        "\$GFATOOLS_BIN" gfa2fa "\$gfa_path" > "\$fasta_path"
        if [ ! -s "\$fasta_path" ] || ! grep -q '^>' "\$fasta_path"; then
            printf 'Extracted %s FASTA is empty or invalid: %s\\n' "\$label" "\$fasta_path" >&2
            exit 2
        fi
    }

    convert_gfa "gfa/\${PREFIX}.bp.p_ctg.gfa" "fasta/${params.assembly_run_id ?: 'baseline'}.primary.fa" "primary contig"
    convert_gfa "gfa/\${PREFIX}.bp.hap1.p_ctg.gfa" "fasta/${params.assembly_run_id ?: 'baseline'}.hap1.fa" "haplotype 1"
    convert_gfa "gfa/\${PREFIX}.bp.hap2.p_ctg.gfa" "fasta/${params.assembly_run_id ?: 'baseline'}.hap2.fa" "haplotype 2"

    python -m hifi_agent.workflow_tools hifiasm-manifest \\
        --sample-id "${sample_id}" \\
        --run-id "${params.assembly_run_id ?: 'baseline'}" \\
        --prefix "\$PREFIX" \\
        --command-file metadata/hifiasm_command.txt \\
        --stdout logs/hifiasm.stdout \\
        --stderr logs/hifiasm.stderr \\
        --time-report logs/hifiasm.time.txt \\
        --output metadata/assembly_manifest.json
    """
}

process QUAST {
    tag "${sample_id}:${params.assembly_run_id ?: 'baseline'}"
    label 'post_qc'

    publishDir "${params.post_qc_publish_dir ?: "${params.outdir}/03_post_qc/${params.assembly_run_id ?: 'baseline'}"}/quast",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(assembly_manifest), path(primary_fasta), val(reference_genome), val(expected_genome_size_value)

    output:
    tuple val(sample_id), path('quast_metrics.json'), emit: metrics
    path 'quast', emit: raw
    path 'quast.stdout'
    path 'quast.stderr'
    path 'quast.version.txt'

    script:
    """
    set -euo pipefail
    mkdir -p quast

    QUAST_BIN="\$(command -v quast.py || true)"

    MODE="reference_free"
    REFERENCE_ARGS=()
    LARGE_ARGS=()
    if [ -n "${reference_genome}" ] && [ -f "${reference_genome}" ]; then
        MODE="reference_based"
        REFERENCE_ARGS=(-r "${reference_genome}")
    fi
    if [ -n "${expected_genome_size_value}" ] && [ "${expected_genome_size_value}" -ge 100000000 ]; then
        LARGE_ARGS=(--large)
    fi

    STATUS=127
    if [ -n "\$QUAST_BIN" ]; then
        "\$QUAST_BIN" --version > quast.version.txt 2>&1 || true
        set +e
        "\$QUAST_BIN" "${primary_fasta}" \
            -o quast \
            -t "${task.cpus}" \
            --min-contig 0 \
            "\${LARGE_ARGS[@]}" \
            "\${REFERENCE_ARGS[@]}" \
            > quast.stdout 2> quast.stderr
        STATUS=\$?
        set -e
    else
        printf 'quast.py executable not found\n' > quast.version.txt
        : > quast.stdout
        printf 'quast.py executable not found\n' > quast.stderr
    fi

    python -m hifi_agent.workflow_tools quast-metrics \
        --report quast/report.tsv \
        --status "\$STATUS" \
        --mode "\$MODE" \
        --version-file quast.version.txt \
        --output quast_metrics.json
    """
}

process BUSCO_POST_QC {
    tag "${sample_id}:${params.assembly_run_id ?: 'baseline'}"
    label 'post_qc'

    publishDir "${params.post_qc_publish_dir ?: "${params.outdir}/03_post_qc/${params.assembly_run_id ?: 'baseline'}"}/busco",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(assembly_manifest), path(primary_fasta), val(busco_lineage_value), val(busco_download_path_value), val(busco_timeout_minutes_value)

    output:
    tuple val(sample_id), path('busco_metrics.json'), emit: metrics
    path 'busco', emit: raw
    path 'busco.stdout'
    path 'busco.stderr'
    path 'busco.version.txt'

    script:
    """
    set -euo pipefail
    mkdir -p busco

    BUSCO_BIN="\$(command -v busco || true)"

    LINEAGE_ARGS=()
    OFFLINE_ARGS=()
    DOWNLOAD_ARGS=()
    REPORT_DOWNLOAD_ARGS=()
    if [ -n "${busco_download_path_value}" ]; then
        DOWNLOAD_ARGS=(--download_path "${busco_download_path_value}")
        REPORT_DOWNLOAD_ARGS=(--download-path "${busco_download_path_value}")
    fi
    if [ -n "${busco_lineage_value}" ]; then
        LINEAGE_ARGS=(-l "${busco_lineage_value}")
        if [ -n "${busco_download_path_value}" ] && \
           { [ -d "${busco_download_path_value}/${busco_lineage_value}" ] || \
             [ -d "${busco_download_path_value}/lineages/${busco_lineage_value}" ]; }; then
            OFFLINE_ARGS=(--offline)
        fi
    else
        LINEAGE_ARGS=(--auto-lineage-euk)
    fi

    STATUS=127
    if [ -n "\$BUSCO_BIN" ]; then
        export PATH="\$(dirname "\$BUSCO_BIN"):\$PATH"
        "\$BUSCO_BIN" --version > busco.version.txt 2>&1 || true
        set +e
        timeout --signal=TERM "${busco_timeout_minutes_value}m" "\$BUSCO_BIN" \
            -i "${primary_fasta}" \
            -o baseline \
            -m genome \
            -c "${task.cpus}" \
            --out_path "\$PWD/busco" \
            --opt-out-run-stats \
            "\${DOWNLOAD_ARGS[@]}" \
            "\${OFFLINE_ARGS[@]}" \
            "\${LINEAGE_ARGS[@]}" \
            > busco.stdout 2> busco.stderr
        STATUS=\$?
        set -e
    else
        printf 'BUSCO executable not found\n' > busco.version.txt
        : > busco.stdout
        printf 'BUSCO executable not found\n' > busco.stderr
    fi

    python -m hifi_agent.workflow_tools busco-metrics \
        --root busco \
        --status "\$STATUS" \
        --lineage "${busco_lineage_value}" \
        "\${REPORT_DOWNLOAD_ARGS[@]}" \
        --version-file busco.version.txt \
        --output busco_metrics.json
    """
}

process MERQURY_POST_QC {
    tag "${sample_id}:${params.assembly_run_id ?: 'baseline'}"
    label 'post_qc'

    publishDir "${params.post_qc_publish_dir ?: "${params.outdir}/03_post_qc/${params.assembly_run_id ?: 'baseline'}"}/merqury",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(assembly_manifest), path(primary_fasta), path(meryl_db), path(histogram), val(kmer_source_value)

    output:
    tuple val(sample_id), path('merqury_metrics.json'), emit: metrics
    path 'merqury', emit: raw

    script:
    """
    set -euo pipefail
    mkdir -p merqury/toolbin

    MERQURY_BIN="\$(command -v merqury.sh || true)"
    REAL_MERYL="\$(command -v meryl || true)"

    printf 'Merqury 1.3 (existing installation)\n' > merqury/merqury.version.txt
    STATUS=127
    if [ -n "\$MERQURY_BIN" ] && [ -n "\$REAL_MERYL" ]; then
        MERQURY_SCRIPT="\$(readlink -f "\$MERQURY_BIN")"
        MERQURY_ROOT="\$(dirname "\$MERQURY_SCRIPT")"
        printf '#!/usr/bin/env bash\nexec "%s" threads="%s" memory="%s" "\$@"\n' \
            "\$REAL_MERYL" "${task.cpus}" "${task.memory.toGiga() as int}" \
            > merqury/toolbin/meryl
        chmod +x merqury/toolbin/meryl
        set +e
        (
            cd merqury
            export PATH="\$PWD/toolbin:\$PATH"
            export MERQURY="\$MERQURY_ROOT"
            "\$MERQURY_SCRIPT" "../${meryl_db}" "../${primary_fasta}" baseline
        ) > merqury/merqury.stdout 2> merqury/merqury.stderr
        STATUS=\$?
        set -e
    else
        : > merqury/merqury.stdout
        printf 'Merqury or meryl executable not found\n' > merqury/merqury.stderr
    fi

    python -m hifi_agent.workflow_tools merqury-metrics \
        --qv merqury/baseline.qv \
        --completeness merqury/baseline.completeness.stats \
        --status "\$STATUS" \
        --kmer-source "${kmer_source_value}" \
        --version-file merqury/merqury.version.txt \
        --output merqury/merqury_metrics.json
    cp merqury/merqury_metrics.json merqury_metrics.json
    """
}

process MAPPING_POST_QC {
    tag "${sample_id}:${params.assembly_run_id ?: 'baseline'}"
    label 'post_qc'

    publishDir "${params.post_qc_publish_dir ?: "${params.outdir}/03_post_qc/${params.assembly_run_id ?: 'baseline'}"}/mapping",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(assembly_manifest), path(primary_fasta), path(reads), val(coverage_window_size_value)

    output:
    tuple val(sample_id), path('mapping_metrics.json'), emit: metrics
    path 'mapping', emit: raw

    script:
    """
    set -euo pipefail
    mkdir -p mapping
    cp "${primary_fasta}" mapping/assembly.fa

    MINIMAP2_BIN="\$(command -v minimap2 || true)"
    SAMTOOLS_BIN="\$(command -v samtools || true)"
    if command -v mosdepth >/dev/null 2>&1; then
        COVERAGE_BIN="\$(command -v mosdepth)"
        COVERAGE_MODE="mosdepth"
    elif command -v bedtools >/dev/null 2>&1; then
        COVERAGE_BIN="\$(command -v bedtools)"
        COVERAGE_MODE="bedtools_samtools_bedcov"
    else
        COVERAGE_BIN=""
        COVERAGE_MODE="unavailable"
    fi

    [ -n "\$MINIMAP2_BIN" ] && "\$MINIMAP2_BIN" --version > mapping/minimap2.version.txt 2>&1 || true
    [ -n "\$SAMTOOLS_BIN" ] && "\$SAMTOOLS_BIN" --version > mapping/samtools.version.txt 2>&1 || true
    if [ "\$COVERAGE_MODE" = "mosdepth" ]; then
        "\$COVERAGE_BIN" --version > mapping/coverage.version.txt 2>&1 || true
    elif [ -n "\$COVERAGE_BIN" ]; then
        "\$COVERAGE_BIN" --version > mapping/coverage.version.txt 2>&1 || true
    fi
    touch mapping/minimap2.version.txt mapping/samtools.version.txt mapping/coverage.version.txt

    set +e
    python -m hifi_agent.workflow_tools filter-hifi-reads \
        --input ${reads} \
        --output mapping/filtered_reads.fastq.gz \
        --summary mapping/filter_summary.json \
        --min-read-length "${params.mapping_min_read_length ?: 1000}" \
        --min-mean-qscore "${params.mapping_min_mean_qscore ?: 20.0}" \
        > mapping/filter.stdout 2> mapping/filter.stderr
    FILTER_STATUS=\$?
    set -e
    [ -f mapping/filter_summary.json ] || printf '{}\n' > mapping/filter_summary.json

    STATUS=\$FILTER_STATUS
    set +e
    if [ "\$STATUS" -eq 0 ] && [ -n "\$MINIMAP2_BIN" ] && [ -n "\$SAMTOOLS_BIN" ] && [ -n "\$COVERAGE_BIN" ]; then
        set -o pipefail
        MAPPING_THREADS="${task.cpus}"
        MINIMAP_THREADS=\$((MAPPING_THREADS * 3 / 4))
        SAMTOOLS_THREADS=\$((MAPPING_THREADS - MINIMAP_THREADS))
        [ "\$MINIMAP_THREADS" -ge 1 ] || MINIMAP_THREADS=1
        [ "\$SAMTOOLS_THREADS" -ge 1 ] || SAMTOOLS_THREADS=1
        "\$MINIMAP2_BIN" -ax map-hifi -t "\$MINIMAP_THREADS" mapping/assembly.fa mapping/filtered_reads.fastq.gz \
            2> mapping/minimap2.stderr \
            | "\$SAMTOOLS_BIN" sort -@ "\$SAMTOOLS_THREADS" -o mapping/alignment.bam - \
            2> mapping/samtools_sort.stderr
        STATUS=\$?
        if [ "\$STATUS" -eq 0 ]; then
            "\$SAMTOOLS_BIN" index mapping/alignment.bam || STATUS=\$?
            "\$SAMTOOLS_BIN" flagstat mapping/alignment.bam > mapping/flagstat.txt || STATUS=\$?
            "\$SAMTOOLS_BIN" faidx mapping/assembly.fa || STATUS=\$?
        fi
        if [ "\$STATUS" -eq 0 ] && [ "\$COVERAGE_MODE" = "mosdepth" ]; then
            "\$COVERAGE_BIN" --threads "${task.cpus}" --by "${coverage_window_size_value}" \
                mapping/coverage mapping/alignment.bam || STATUS=\$?
            if [ -f mapping/coverage.regions.bed.gz ]; then
                gzip -cd mapping/coverage.regions.bed.gz \
                    | awk 'BEGIN{OFS="\\t"} {print \$1,\$2,\$3,\$4*(\$3-\$2)}' \
                    > mapping/coverage_windows.tsv
            fi
        elif [ "\$STATUS" -eq 0 ]; then
            "\$COVERAGE_BIN" makewindows -g mapping/assembly.fa.fai -w "${coverage_window_size_value}" \
                > mapping/windows.bed || STATUS=\$?
            "\$SAMTOOLS_BIN" bedcov mapping/windows.bed mapping/alignment.bam \
                > mapping/coverage_windows.tsv || STATUS=\$?
        fi
    elif [ "\$STATUS" -eq 0 ]; then
        STATUS=127
        printf 'Required mapping or coverage executable not found\n' > mapping/mapping.stderr
    fi
    set -e
    touch mapping/flagstat.txt mapping/coverage_windows.tsv

    python -m hifi_agent.workflow_tools mapping-metrics \
        --flagstat mapping/flagstat.txt \
        --windows mapping/coverage_windows.tsv \
        --status "\$STATUS" \
        --preset map-hifi \
        --minimap2-version mapping/minimap2.version.txt \
        --samtools-version mapping/samtools.version.txt \
        --coverage-tool-version mapping/coverage.version.txt \
        --filter-summary mapping/filter_summary.json \
        --output mapping/mapping_metrics.json
    cp mapping/mapping_metrics.json mapping_metrics.json
    """
}

process ASSEMBLY_METRICS {
    tag "${sample_id}:${params.assembly_run_id ?: 'baseline'}"
    label 'small'

    publishDir (params.post_qc_publish_dir ?: "${params.outdir}/03_post_qc/${params.assembly_run_id ?: 'baseline'}"),
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(quast_metrics), path(busco_metrics), path(merqury_metrics), path(mapping_metrics), val(expected_genome_size_value)

    output:
    tuple val(sample_id), path('assembly_metrics.json'), emit: metrics

    script:
    """
    set -euo pipefail
    python -m hifi_agent.workflow_tools assembly-metrics \
        --run-id "${params.assembly_run_id ?: 'baseline'}" \
        --quast "${quast_metrics}" \
        --busco "${busco_metrics}" \
        --merqury "${merqury_metrics}" \
        --mapping "${mapping_metrics}" \
        --expected-genome-size "${expected_genome_size_value}" \
        --output assembly_metrics.json
    """
}

workflow ASSEMBLY_ATTEMPT {
    def sample_id_value = params.sample_id as String
    def validation_receipt_value = params.validation_receipt ? params.validation_receipt as String : ''
    def reads_manifest_value = params.reads_manifest
    def reference_genome_value = params.reference_genome ? params.reference_genome as String : ''
    def expected_genome_size_value = params.expected_genome_size ? params.expected_genome_size as String : ''
    def busco_lineage_value = params.busco_lineage ? params.busco_lineage as String : ''
    def busco_download_path_value = params.busco_download_path ? params.busco_download_path as String : ''
    def busco_timeout_minutes_value = params.busco_timeout_minutes ?: 240
    def kmer_source_value = params.kmer_source ?: 'same_data_advisory'
    def coverage_window_size_value = params.coverage_window_size ?: 10000

    if (!sample_id_value) {
        error "Missing required parameter: --sample_id"
    }
    if (!(sample_id_value ==~ /^[A-Za-z0-9_-]+$/)) {
        error "Invalid --sample_id '${sample_id_value}'. Use only letters, numbers, underscores, and hyphens."
    }
    if (!validation_receipt_value || !new File(validation_receipt_value).isFile()) {
        error "Missing validated input receipt: --validation_receipt"
    }
    if (!reads_manifest_value || !params.raw_metrics || !params.meryl_db) {
        error "ASSEMBLY_ATTEMPT requires --reads_manifest, --raw_metrics, and --meryl_db"
    }

    assembly_reads_ch = Channel
        .fromPath(reads_manifest_value, checkIfExists: true)
        .splitText()
        .map { read -> read.trim() }
        .filter { read -> read }
        .map { read -> file(read) }
        .collect()
        .map { reads -> tuple(sample_id_value, reads) }
    raw_metrics_ch = Channel.of(tuple(sample_id_value, file(params.raw_metrics)))
    assembly_input_ch = assembly_reads_ch
        .join(raw_metrics_ch)
        .map { sample_id, reads, raw_metrics ->
            tuple(sample_id, reads, raw_metrics)
        }
    HIFIASM_ASSEMBLY(assembly_input_ch)

    quast_ch = HIFIASM_ASSEMBLY.out.baseline.map {
        sample_id, assembly_manifest, primary_fasta ->
            tuple(
                sample_id,
                assembly_manifest,
                primary_fasta,
                reference_genome_value,
                expected_genome_size_value
            )
    }
    busco_ch = HIFIASM_ASSEMBLY.out.baseline.map {
        sample_id, assembly_manifest, primary_fasta ->
            tuple(
                sample_id,
                assembly_manifest,
                primary_fasta,
                busco_lineage_value,
                busco_download_path_value,
                busco_timeout_minutes_value
            )
    }
    QUAST(quast_ch)
    BUSCO_POST_QC(busco_ch)

    merqury_ch = HIFIASM_ASSEMBLY.out.baseline.map {
        sample_id, assembly_manifest, primary_fasta ->
            tuple(
                sample_id,
                assembly_manifest,
                primary_fasta,
                file(params.meryl_db),
                file(params.kmer_histogram ?: params.meryl_db),
                kmer_source_value
            )
    }
    MERQURY_POST_QC(merqury_ch)

    mapping_ch = HIFIASM_ASSEMBLY.out.baseline
        .join(assembly_reads_ch)
        .map { sample_id, assembly_manifest, primary_fasta, reads ->
            tuple(sample_id, assembly_manifest, primary_fasta, reads, coverage_window_size_value)
        }
    MAPPING_POST_QC(mapping_ch)

    combined_ch = QUAST.out.metrics
        .join(BUSCO_POST_QC.out.metrics)
        .join(MERQURY_POST_QC.out.metrics)
        .join(MAPPING_POST_QC.out.metrics)
        .map { sample_id, quast_metrics, busco_metrics, merqury_metrics, mapping_metrics ->
            tuple(
                sample_id,
                quast_metrics,
                busco_metrics,
                merqury_metrics,
                mapping_metrics,
                expected_genome_size_value
            )
        }
    ASSEMBLY_METRICS(combined_ch)
}

workflow {
    def sample_id_value = params.sample_id as String
    def validation_receipt_value = params.validation_receipt ? params.validation_receipt as String : ''
    def reads_pattern_value = params.reads
    def reads_manifest_value = params.reads_manifest
    def kmer_reads_manifest_value = params.kmer_reads_manifest ?: reads_manifest_value

    if (!sample_id_value) {
        error "Missing required parameter: --sample_id"
    }
    if (!(sample_id_value ==~ /^[A-Za-z0-9_-]+$/)) {
        error "Invalid --sample_id '${sample_id_value}'. Use only letters, numbers, underscores, and hyphens."
    }
    if (!validation_receipt_value || !new File(validation_receipt_value).isFile()) {
        error "Missing validated input receipt: --validation_receipt"
    }
    if (!reads_pattern_value && !reads_manifest_value) {
        error "Missing required parameter: --reads or --reads_manifest"
    }

    if (reads_manifest_value) {
        reads_ch = Channel
            .fromPath(reads_manifest_value, checkIfExists: true)
            .splitText()
            .map { read -> read.trim() }
            .filter { read -> read }
            .map { read -> file(read) }
            .collect()
            .map { reads -> tuple(sample_id_value, reads) }
    } else {
        reads_ch = Channel
            .fromPath(reads_pattern_value, checkIfExists: true)
            .collect()
            .map { reads -> tuple(sample_id_value, reads) }
    }

    if (kmer_reads_manifest_value) {
        kmer_reads_ch = Channel
            .fromPath(kmer_reads_manifest_value, checkIfExists: true)
            .splitText()
            .map { read -> read.trim() }
            .filter { read -> read }
            .map { read -> file(read) }
            .collect()
            .map { reads -> tuple(sample_id_value, reads) }
    } else {
        kmer_reads_ch = Channel
            .fromPath(reads_pattern_value, checkIfExists: true)
            .collect()
            .map { reads -> tuple(sample_id_value, reads) }
    }

    FASTQ_PROBE(reads_ch)
    SEQKIT_STATS(reads_ch)
    NANOPLOT(reads_ch)
    KMER_COUNT(kmer_reads_ch)
    GENOMESCOPE_SUMMARY(KMER_COUNT.out.histogram)
    KMER_METRICS(GENOMESCOPE_SUMMARY.out.summary)

    pre_qc_ch = SEQKIT_STATS.out.stats
        .join(NANOPLOT.out.nanostats)
        .join(KMER_METRICS.out.metrics)
        .map { sample_id, seqkit_stats, nanostats, kmer_metrics ->
            tuple(sample_id, seqkit_stats, nanostats, kmer_metrics)
        }
    RAW_METRICS(pre_qc_ch)

}
