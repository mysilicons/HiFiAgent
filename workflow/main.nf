nextflow.enable.dsl = 2

def sampleId = params.sample_id as String
def assemblyRunId = params.assembly_run_id ? params.assembly_run_id as String : 'baseline'
def hifiasmPurgeLevel = params.hifiasm_purge_level == null ? 3 : params.hifiasm_purge_level as int
def hifiasmPurgeSimilarity = params.hifiasm_purge_similarity == null ? 0.55 : params.hifiasm_purge_similarity as double
def hifiasmHomCov = params.hifiasm_hom_cov ? params.hifiasm_hom_cov as String : ''
def hifiasmDisablePostJoin = params.hifiasm_disable_post_join == null ? false : params.hifiasm_disable_post_join.toString().toBoolean()
def validationReceipt = params.validation_receipt ? params.validation_receipt as String : ''
def binReuseManifest = params.bin_reuse_manifest ? params.bin_reuse_manifest as String : ''
def readsPattern = params.reads
def readsManifest = params.reads_manifest
def kmerReadsManifest = params.kmer_reads_manifest ?: readsManifest
def kmerSource = params.kmer_source ?: 'same_data_advisory'
def expectedGenomeSize = params.expected_genome_size ? params.expected_genome_size as String : ''
def kmerK = params.kmer_k ?: 21
def pythonPath = "${projectDir}/../src"
def runAssembly = params.run_assembly == null ? true : params.run_assembly.toString().toBoolean()
def runPostQc = params.run_post_qc == null ? true : params.run_post_qc.toString().toBoolean()
def referenceGenome = params.reference_genome ? params.reference_genome as String : ''
def buscoLineage = params.busco_lineage ? params.busco_lineage as String : ''
def buscoDownloadPath = params.busco_download_path as String
def buscoTimeoutMinutes = params.busco_timeout_minutes ?: 240
def coverageWindowSize = params.coverage_window_size ?: 10000
def mappingMinReadLength = params.mapping_min_read_length ?: 1000
def mappingMinMeanQscore = params.mapping_min_mean_qscore ?: 20.0
def kmerLowCoveragePeakThreshold = params.kmer_low_coverage_peak_threshold ?: 10.0

if (!sampleId) {
    error "Missing required parameter: --sample_id"
}

if (!validationReceipt || !new File(validationReceipt).isFile()) {
    error "Missing validated input receipt: --validation_receipt"
}

if (!(sampleId ==~ /^[A-Za-z0-9_-]+$/)) {
    error "Invalid --sample_id '${sampleId}'. Use only letters, numbers, underscores, and hyphens."
}

if (!readsPattern && !readsManifest) {
    error "Missing required parameter: --reads or --reads_manifest"
}

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

    if command -v seqkit >/dev/null 2>&1; then
        seqkit stats -a -T -j "${task.cpus}" ${reads} > seqkit_stats.tsv
    elif [ -x /home/gw/software/seqkit ]; then
        /home/gw/software/seqkit stats -a -T -j "${task.cpus}" ${reads} > seqkit_stats.tsv
    else
        printf 'seqkit executable not found\\n' >&2
        exit 127
    fi
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

    if command -v meryl >/dev/null 2>&1; then
        MERYL_BIN="meryl"
    elif [ -x /home/gw/software/canu/build/bin/meryl ]; then
        MERYL_BIN="/home/gw/software/canu/build/bin/meryl"
    else
        printf 'meryl executable not found\\n' >&2
        exit 127
    fi

    "\$MERYL_BIN" count \\
        k="${kmerK}" \\
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

    PYTHONPATH="${pythonPath}" python -m hifi_agent.workflow_tools run-genomescope \\
        --histogram "${histogram}" \\
        --k "${kmerK}" \\
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

    PYTHONPATH="${pythonPath}" python -m hifi_agent.workflow_tools kmer-metrics \\
        --sample-id "${sample_id}" \\
        --histogram "${histogram}" \\
        --genomescope-summary "${genomescope_summary}" \\
        --expected-genome-size "${expectedGenomeSize}" \\
        --kmer-source "${kmerSource}" \\
        --low-coverage-peak-threshold "${kmerLowCoveragePeakThreshold}" \\
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

    PYTHONPATH="${pythonPath}" python -m hifi_agent.workflow_tools raw-metrics \\
        --sample-id "${sample_id}" \\
        --seqkit-stats "${seqkit_stats}" \\
        --nanostats "${nanostats}" \\
        --kmer-metrics "${kmer_metrics}" \\
        --expected-genome-size "${expectedGenomeSize}" \\
        --output raw_metrics.json
    """
}

process HIFIASM_BASELINE {
    tag "${sample_id}:${assemblyRunId}"
    label 'assembly'

    publishDir "${params.outdir}/02_assembly/${assemblyRunId}",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(reads), path(raw_metrics), path(bin_reuse_manifest)

    output:
    tuple val(sample_id), path('metadata/assembly_manifest.json'), path("fasta/${assemblyRunId}.primary.fa"), emit: baseline
    path 'logs', emit: logs
    path 'gfa', emit: gfa
    path 'fasta', emit: fasta
    path 'bins', optional: true, emit: bins
    path 'metadata', emit: metadata

    script:
    """
    set -euo pipefail

    PREFIX="${sample_id}.${assemblyRunId}"
    mkdir -p logs gfa fasta bins metadata

    if command -v hifiasm >/dev/null 2>&1; then
        HIFIASM_BIN="hifiasm"
    elif [ -x /home/gw/software/hifiasm/hifiasm ]; then
        HIFIASM_BIN="/home/gw/software/hifiasm/hifiasm"
    else
        printf 'hifiasm executable not found\\n' >&2
        exit 127
    fi

    if command -v gfatools >/dev/null 2>&1; then
        GFATOOLS_BIN="gfatools"
    elif [ -x /home/gw/software/gfatools/gfatools ]; then
        GFATOOLS_BIN="/home/gw/software/gfatools/gfatools"
    else
        printf 'gfatools executable not found\\n' >&2
        exit 127
    fi

    "\$HIFIASM_BIN" --version > metadata/hifiasm.version.txt
    "\$GFATOOLS_BIN" version > metadata/gfatools.version.txt 2>&1 || true

    printf 'source_path\\tdestination\\tstatus\\n' > metadata/reused_bins.tsv
    while IFS=\$'\\t' read -r bin expected_sha expected_bytes; do
        [ "\$bin" != "path" ] || continue
        [ -f "\$bin" ] || { printf 'Missing reuse candidate: %s\\n' "\$bin" >&2; exit 2; }
        observed_sha=\$(sha256sum "\$bin" | awk '{print \$1}')
        [ "\$observed_sha" = "\$expected_sha" ] || {
            printf 'Checksum mismatch for reuse candidate: %s\\n' "\$bin" >&2
            exit 2
        }
        source_name=\$(basename "\$bin")
        destination_name="\${source_name/${sample_id}.baseline/\$PREFIX}"
        cp "\$bin" "\$destination_name"
        printf '%s\\t%s\\treused\\n' "\$bin" "\$destination_name" >> metadata/reused_bins.tsv
    done < "${bin_reuse_manifest}"

    PARAMETER_ARGS=()
    if [ "${assemblyRunId}" != "baseline" ]; then
        PARAMETER_ARGS=(-l "${hifiasmPurgeLevel}" -s "${hifiasmPurgeSimilarity}")
        if [ -n "${hifiasmHomCov}" ]; then
            PARAMETER_ARGS+=(--hom-cov "${hifiasmHomCov}")
        fi
        if [ "${hifiasmDisablePostJoin}" = "true" ]; then
            PARAMETER_ARGS+=(-u0)
        fi
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

    convert_gfa "gfa/\${PREFIX}.bp.p_ctg.gfa" "fasta/${assemblyRunId}.primary.fa" "primary contig"
    convert_gfa "gfa/\${PREFIX}.bp.hap1.p_ctg.gfa" "fasta/${assemblyRunId}.hap1.fa" "haplotype 1"
    convert_gfa "gfa/\${PREFIX}.bp.hap2.p_ctg.gfa" "fasta/${assemblyRunId}.hap2.fa" "haplotype 2"

    PYTHONPATH="${pythonPath}" python -m hifi_agent.workflow_tools hifiasm-manifest \\
        --sample-id "${sample_id}" \\
        --run-id "${assemblyRunId}" \\
        --prefix "\$PREFIX" \\
        --command-file metadata/hifiasm_command.txt \\
        --stdout logs/hifiasm.stdout \\
        --stderr logs/hifiasm.stderr \\
        --time-report logs/hifiasm.time.txt \\
        --reused-bins-record metadata/reused_bins.tsv \\
        --output metadata/assembly_manifest.json
    """
}

process QUAST {
    tag "${sample_id}:${assemblyRunId}"
    label 'post_qc'

    publishDir "${params.outdir}/03_post_qc/${assemblyRunId}/quast",
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

    if command -v quast.py >/dev/null 2>&1; then
        QUAST_BIN="quast.py"
    elif [ -x /home/gw/software/quast/quast.py ]; then
        QUAST_BIN="/home/gw/software/quast/quast.py"
    else
        QUAST_BIN=""
    fi

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

    PYTHONPATH="${pythonPath}" python -m hifi_agent.workflow_tools quast-metrics \
        --report quast/report.tsv \
        --status "\$STATUS" \
        --mode "\$MODE" \
        --version-file quast.version.txt \
        --output quast_metrics.json
    """
}

process BUSCO_POST_QC {
    tag "${sample_id}:${assemblyRunId}"
    label 'post_qc'

    publishDir "${params.outdir}/03_post_qc/${assemblyRunId}/busco",
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

    if command -v busco >/dev/null 2>&1; then
        BUSCO_BIN="busco"
    elif [ -x /home/gw/miniconda3/envs/evaluation/bin/busco ]; then
        BUSCO_BIN="/home/gw/miniconda3/envs/evaluation/bin/busco"
    else
        BUSCO_BIN=""
    fi

    LINEAGE_ARGS=()
    OFFLINE_ARGS=()
    if [ -n "${busco_lineage_value}" ]; then
        LINEAGE_ARGS=(-l "${busco_lineage_value}")
        if [ -d "${busco_download_path_value}/${busco_lineage_value}" ] || \
           [ -d "${busco_download_path_value}/lineages/${busco_lineage_value}" ]; then
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
            --download_path "${busco_download_path_value}" \
            --opt-out-run-stats \
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

    PYTHONPATH="${pythonPath}" python -m hifi_agent.workflow_tools busco-metrics \
        --root busco \
        --status "\$STATUS" \
        --lineage "${busco_lineage_value}" \
        --download-path "${busco_download_path_value}" \
        --version-file busco.version.txt \
        --output busco_metrics.json
    """
}

process MERQURY_POST_QC {
    tag "${sample_id}:${assemblyRunId}"
    label 'post_qc'

    publishDir "${params.outdir}/03_post_qc/${assemblyRunId}/merqury",
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

    if command -v merqury.sh >/dev/null 2>&1; then
        MERQURY_BIN="\$(command -v merqury.sh)"
    elif [ -x /home/gw/software/merqury/merqury.sh ]; then
        MERQURY_BIN="/home/gw/software/merqury/merqury.sh"
    else
        MERQURY_BIN=""
    fi
    if command -v meryl >/dev/null 2>&1; then
        REAL_MERYL="\$(command -v meryl)"
    elif [ -x /home/gw/software/canu/build/bin/meryl ]; then
        REAL_MERYL="/home/gw/software/canu/build/bin/meryl"
    else
        REAL_MERYL=""
    fi

    printf 'Merqury 1.3 (existing installation)\n' > merqury/merqury.version.txt
    STATUS=127
    if [ -n "\$MERQURY_BIN" ] && [ -n "\$REAL_MERYL" ]; then
        printf '#!/usr/bin/env bash\nexec "%s" threads="%s" memory="%s" "\$@"\n' \
            "\$REAL_MERYL" "${task.cpus}" "${task.memory.toGiga() as int}" \
            > merqury/toolbin/meryl
        chmod +x merqury/toolbin/meryl
        set +e
        (
            cd merqury
            export PATH="\$PWD/toolbin:\$PATH"
            export MERQURY="\$(dirname "\$MERQURY_BIN")"
            "\$MERQURY_BIN" "../${meryl_db}" "../${primary_fasta}" baseline
        ) > merqury/merqury.stdout 2> merqury/merqury.stderr
        STATUS=\$?
        set -e
    else
        : > merqury/merqury.stdout
        printf 'Merqury or meryl executable not found\n' > merqury/merqury.stderr
    fi

    PYTHONPATH="${pythonPath}" python -m hifi_agent.workflow_tools merqury-metrics \
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
    tag "${sample_id}:${assemblyRunId}"
    label 'post_qc'

    publishDir "${params.outdir}/03_post_qc/${assemblyRunId}/mapping",
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

    if command -v minimap2 >/dev/null 2>&1; then
        MINIMAP2_BIN="\$(command -v minimap2)"
    elif [ -x /home/gw/software/minimap2/minimap2 ]; then
        MINIMAP2_BIN="/home/gw/software/minimap2/minimap2"
    else
        MINIMAP2_BIN=""
    fi
    if command -v samtools >/dev/null 2>&1; then
        SAMTOOLS_BIN="\$(command -v samtools)"
    elif [ -x /home/gw/software/samtools/bin/samtools ]; then
        SAMTOOLS_BIN="/home/gw/software/samtools/bin/samtools"
    else
        SAMTOOLS_BIN=""
    fi
    if command -v mosdepth >/dev/null 2>&1; then
        COVERAGE_BIN="\$(command -v mosdepth)"
        COVERAGE_MODE="mosdepth"
    elif command -v bedtools >/dev/null 2>&1; then
        COVERAGE_BIN="\$(command -v bedtools)"
        COVERAGE_MODE="bedtools_samtools_bedcov"
    elif [ -x /home/gw/software/bedtools2/bin/bedtools ]; then
        COVERAGE_BIN="/home/gw/software/bedtools2/bin/bedtools"
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
    PYTHONPATH="${pythonPath}" python -m hifi_agent.workflow_tools filter-hifi-reads \
        --input ${reads} \
        --output mapping/filtered_reads.fastq.gz \
        --summary mapping/filter_summary.json \
        --min-read-length "${mappingMinReadLength}" \
        --min-mean-qscore "${mappingMinMeanQscore}" \
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

    PYTHONPATH="${pythonPath}" python -m hifi_agent.workflow_tools mapping-metrics \
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
    tag "${sample_id}:${assemblyRunId}"
    label 'small'

    publishDir "${params.outdir}/03_post_qc/${assemblyRunId}",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(quast_metrics), path(busco_metrics), path(merqury_metrics), path(mapping_metrics), val(expected_genome_size_value)

    output:
    tuple val(sample_id), path('assembly_metrics.json'), emit: metrics

    script:
    """
    set -euo pipefail
    PYTHONPATH="${pythonPath}" python -m hifi_agent.workflow_tools assembly-metrics \
        --run-id "${assemblyRunId}" \
        --quast "${quast_metrics}" \
        --busco "${busco_metrics}" \
        --merqury "${merqury_metrics}" \
        --mapping "${mapping_metrics}" \
        --expected-genome-size "${expected_genome_size_value}" \
        --output assembly_metrics.json
    """
}

process WRITE_RUN_MANIFEST {
    tag "${sample_id}"
    label 'small'

    publishDir "${params.outdir}/00_metadata",
        mode: params.publish_mode,
        overwrite: params.publish_overwrite

    input:
    tuple val(sample_id), path(metrics), path(raw_metrics)

    output:
    path 'run_manifest.json', emit: manifest

    script:
    """
    set -euo pipefail

    total_records=\$(awk 'NR > 1 { sum += \$3 } END { print sum + 0 }' "${metrics}")
    total_bases=\$(awk 'NR > 1 { sum += \$4 } END { print sum + 0 }' "${metrics}")
    file_count=\$(awk 'NR > 1 { count++ } END { print count + 0 }' "${metrics}")

    printf '{\\n' > run_manifest.json
    printf '  "sample_id": "%s",\\n' "${sample_id}" >> run_manifest.json
    printf '  "workflow_stage": "phase3_minimal_nextflow",\\n' >> run_manifest.json
    printf '  "workflow_entry": "workflow/main.nf",\\n' >> run_manifest.json
    printf '  "file_count": %s,\\n' "\$file_count" >> run_manifest.json
    printf '  "read_count": %s,\\n' "\$total_records" >> run_manifest.json
    printf '  "total_bases": %s,\\n' "\$total_bases" >> run_manifest.json
    printf '  "fastq_probe": "01_pre_qc/fastq_probe/fastq_probe.tsv",\\n' >> run_manifest.json
    printf '  "raw_metrics": "01_pre_qc/raw_metrics.json"\\n' >> run_manifest.json
    printf '}\\n' >> run_manifest.json
    """
}

workflow POST_QC_ONLY {
    if (!params.assembly_fasta || !params.assembly_manifest || !params.meryl_db) {
        error "POST_QC_ONLY requires --assembly_fasta, --assembly_manifest, and --meryl_db"
    }

    baseline_ch = Channel.of(
        tuple(sampleId, file(params.assembly_manifest), file(params.assembly_fasta))
    )
    quast_ch = baseline_ch.map { sample_id, assembly_manifest, primary_fasta ->
        tuple(sample_id, assembly_manifest, primary_fasta, referenceGenome, expectedGenomeSize)
    }
    busco_ch = baseline_ch.map { sample_id, assembly_manifest, primary_fasta ->
        tuple(
            sample_id,
            assembly_manifest,
            primary_fasta,
            buscoLineage,
            buscoDownloadPath,
            buscoTimeoutMinutes
        )
    }
    QUAST(quast_ch)
    BUSCO_POST_QC(busco_ch)

    merqury_ch = Channel.of(
        tuple(
            sampleId,
            file(params.assembly_manifest),
            file(params.assembly_fasta),
            file(params.meryl_db),
            file(params.kmer_histogram ?: params.meryl_db),
            kmerSource
        )
    )
    MERQURY_POST_QC(merqury_ch)

    mapping_reads_ch = Channel
        .fromPath(readsManifest, checkIfExists: true)
        .splitText()
        .map { read -> read.trim() }
        .filter { read -> read }
        .map { read -> file(read) }
        .collect()
        .map { reads -> tuple(sampleId, reads) }
    mapping_ch = baseline_ch
        .join(mapping_reads_ch)
        .map { sample_id, assembly_manifest, primary_fasta, reads ->
            tuple(sample_id, assembly_manifest, primary_fasta, reads, coverageWindowSize)
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
                expectedGenomeSize
            )
        }
    ASSEMBLY_METRICS(combined_ch)
}

workflow HIFIASM_REUSE_ONLY {
    if (!readsManifest || !params.raw_metrics || !binReuseManifest) {
        error "HIFIASM_REUSE_ONLY requires --reads_manifest, --raw_metrics, and --bin_reuse_manifest"
    }

    assembly_reads_ch = Channel
        .fromPath(readsManifest, checkIfExists: true)
        .splitText()
        .map { read -> read.trim() }
        .filter { read -> read }
        .map { read -> file(read) }
        .collect()
        .map { reads -> tuple(sampleId, reads) }
    raw_metrics_ch = Channel.of(tuple(sampleId, file(params.raw_metrics)))
    bin_reuse_ch = Channel.of(tuple(sampleId, file(binReuseManifest)))
    assembly_input_ch = assembly_reads_ch
        .join(raw_metrics_ch)
        .join(bin_reuse_ch)
        .map { sample_id, reads, raw_metrics, bin_reuse_manifest ->
            tuple(sample_id, reads, raw_metrics, bin_reuse_manifest)
        }
    HIFIASM_BASELINE(assembly_input_ch)
}

workflow CANDIDATE_ONLY {
    if (!readsManifest || !params.raw_metrics || !binReuseManifest || !params.meryl_db) {
        error "CANDIDATE_ONLY requires --reads_manifest, --raw_metrics, --bin_reuse_manifest, and --meryl_db"
    }
    if (assemblyRunId == 'baseline') {
        error "CANDIDATE_ONLY requires a non-baseline --assembly_run_id"
    }

    assembly_reads_ch = Channel
        .fromPath(readsManifest, checkIfExists: true)
        .splitText()
        .map { read -> read.trim() }
        .filter { read -> read }
        .map { read -> file(read) }
        .collect()
        .map { reads -> tuple(sampleId, reads) }
    raw_metrics_ch = Channel.of(tuple(sampleId, file(params.raw_metrics)))
    bin_reuse_ch = Channel.of(tuple(sampleId, file(binReuseManifest)))
    assembly_input_ch = assembly_reads_ch
        .join(raw_metrics_ch)
        .join(bin_reuse_ch)
        .map { sample_id, reads, raw_metrics, bin_reuse_manifest ->
            tuple(sample_id, reads, raw_metrics, bin_reuse_manifest)
        }
    HIFIASM_BASELINE(assembly_input_ch)

    quast_ch = HIFIASM_BASELINE.out.baseline.map {
        sample_id, assembly_manifest, primary_fasta ->
            tuple(
                sample_id,
                assembly_manifest,
                primary_fasta,
                referenceGenome,
                expectedGenomeSize
            )
    }
    busco_ch = HIFIASM_BASELINE.out.baseline.map {
        sample_id, assembly_manifest, primary_fasta ->
            tuple(
                sample_id,
                assembly_manifest,
                primary_fasta,
                buscoLineage,
                buscoDownloadPath,
                buscoTimeoutMinutes
            )
    }
    QUAST(quast_ch)
    BUSCO_POST_QC(busco_ch)

    merqury_ch = HIFIASM_BASELINE.out.baseline.map {
        sample_id, assembly_manifest, primary_fasta ->
            tuple(
                sample_id,
                assembly_manifest,
                primary_fasta,
                file(params.meryl_db),
                file(params.kmer_histogram ?: params.meryl_db),
                kmerSource
            )
    }
    MERQURY_POST_QC(merqury_ch)

    mapping_ch = HIFIASM_BASELINE.out.baseline
        .join(assembly_reads_ch)
        .map { sample_id, assembly_manifest, primary_fasta, reads ->
            tuple(sample_id, assembly_manifest, primary_fasta, reads, coverageWindowSize)
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
                expectedGenomeSize
            )
        }
    ASSEMBLY_METRICS(combined_ch)
}

workflow {
    if (readsManifest) {
        reads_ch = Channel
            .fromPath(readsManifest, checkIfExists: true)
            .splitText()
            .map { read -> read.trim() }
            .filter { read -> read }
            .map { read -> file(read) }
            .collect()
            .map { reads -> tuple(sampleId, reads) }
    } else {
        reads_ch = Channel
            .fromPath(readsPattern, checkIfExists: true)
            .collect()
            .map { reads -> tuple(sampleId, reads) }
    }

    if (kmerReadsManifest) {
        kmer_reads_ch = Channel
            .fromPath(kmerReadsManifest, checkIfExists: true)
            .splitText()
            .map { read -> read.trim() }
            .filter { read -> read }
            .map { read -> file(read) }
            .collect()
            .map { reads -> tuple(sampleId, reads) }
    } else {
        kmer_reads_ch = Channel
            .fromPath(readsPattern, checkIfExists: true)
            .collect()
            .map { reads -> tuple(sampleId, reads) }
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

    if (runAssembly) {
        if (!binReuseManifest || !new File(binReuseManifest).isFile()) {
            error "Assembly requires --bin_reuse_manifest from the validated CLI"
        }
        if (readsManifest) {
            assembly_reads_ch = Channel
                .fromPath(readsManifest, checkIfExists: true)
                .splitText()
                .map { read -> read.trim() }
                .filter { read -> read }
                .map { read -> file(read) }
                .collect()
                .map { reads -> tuple(sampleId, reads) }
        } else {
            assembly_reads_ch = Channel
                .fromPath(readsPattern, checkIfExists: true)
                .collect()
                .map { reads -> tuple(sampleId, reads) }
        }

        bin_reuse_ch = Channel.of(tuple(sampleId, file(binReuseManifest)))
        assembly_input_ch = assembly_reads_ch
            .join(RAW_METRICS.out.raw)
            .join(bin_reuse_ch)
            .map { sample_id, reads, raw_metrics, bin_reuse_manifest ->
                tuple(sample_id, reads, raw_metrics, bin_reuse_manifest)
        }
        HIFIASM_BASELINE(assembly_input_ch)

        if (runPostQc) {
            quast_input_ch = HIFIASM_BASELINE.out.baseline
                .map { sample_id, assembly_manifest, primary_fasta ->
                    tuple(
                        sample_id,
                        assembly_manifest,
                        primary_fasta,
                        referenceGenome,
                        expectedGenomeSize
                    )
                }
            busco_input_ch = HIFIASM_BASELINE.out.baseline
                .map { sample_id, assembly_manifest, primary_fasta ->
                    tuple(
                        sample_id,
                        assembly_manifest,
                        primary_fasta,
                        buscoLineage,
                        buscoDownloadPath,
                        buscoTimeoutMinutes
                    )
                }
            QUAST(quast_input_ch)
            BUSCO_POST_QC(busco_input_ch)

            merqury_input_ch = HIFIASM_BASELINE.out.baseline
                .join(KMER_COUNT.out.histogram)
                .map { sample_id, assembly_manifest, primary_fasta, meryl_db, histogram ->
                    tuple(
                        sample_id,
                        assembly_manifest,
                        primary_fasta,
                        meryl_db,
                        histogram,
                        kmerSource
                    )
                }
            MERQURY_POST_QC(merqury_input_ch)

            if (readsManifest) {
                mapping_reads_ch = Channel
                    .fromPath(readsManifest, checkIfExists: true)
                    .splitText()
                    .map { read -> read.trim() }
                    .filter { read -> read }
                    .map { read -> file(read) }
                    .collect()
                    .map { reads -> tuple(sampleId, reads) }
            } else {
                mapping_reads_ch = Channel
                    .fromPath(readsPattern, checkIfExists: true)
                    .collect()
                    .map { reads -> tuple(sampleId, reads) }
            }
            mapping_input_ch = HIFIASM_BASELINE.out.baseline
                .join(mapping_reads_ch)
                .map { sample_id, assembly_manifest, primary_fasta, reads ->
                    tuple(sample_id, assembly_manifest, primary_fasta, reads, coverageWindowSize)
                }
            MAPPING_POST_QC(mapping_input_ch)

            assembly_metrics_input_ch = QUAST.out.metrics
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
                        expectedGenomeSize
                    )
                }
            ASSEMBLY_METRICS(assembly_metrics_input_ch)
        }
    }

    manifest_input_ch = FASTQ_PROBE.out.metrics
        .map { metrics -> tuple(sampleId, metrics) }
        .join(RAW_METRICS.out.raw)
    WRITE_RUN_MANIFEST(manifest_input_ch)
}
