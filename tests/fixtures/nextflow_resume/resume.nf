nextflow.enable.dsl = 2

process FIRST_STEP {
    publishDir "${params.outdir}/published", mode: 'copy', overwrite: true

    output:
    path 'first.txt', emit: completed

    script:
    """
    printf 'stable completed output\n' > first.txt
    """
}

process SECOND_STEP {
    publishDir "${params.outdir}/published", mode: 'copy', overwrite: true

    input:
    path first_output

    output:
    path 'second.txt'

    script:
    """
    touch "${params.control_dir}/second_started"
    while [ ! -f "${params.control_dir}/allow_finish" ]; do
        sleep 1
    done
    cp "${first_output}" second.txt
    """
}

workflow {
    if (!params.outdir || !params.control_dir) {
        error 'Required parameters: --outdir and --control_dir'
    }

    FIRST_STEP()
    SECOND_STEP(FIRST_STEP.out.completed)
}
