# Hifiasm

[Hifiasm](https://github.com/chhylp123/hifiasm) is a fast haplotype-resolved de novo assembler for PacBio HiFi reads. It can assemble a human genome in several hours and assemble a ~30Gb California redwood genome in a few days. Hifiasm emits partially phased assemblies of quality competitive with the best assemblers. Given parental short reads or Hi-C data, it produces arguably the best haplotype-resolved assemblies so far.

## Publications

**Hifiasm**
Haoyu Cheng, Gregory T. Concepcion, Xiaowen Feng, Haowen Zhang & Heng Li.
[Haplotype-resolved de novo assembly using phased assembly graphs with hifiasm](https://doi.org/10.1038/s41592-020-01056-5). Nature Methods. (2021).

## Install

The easiest way to get started is to download a [release](https://github.com/chhylp123/hifiasm/releases). Please report any issues on [github issues](https://github.com/chhylp123/hifiasm/issues) page.

In addition, the latest unreleased version can be found from github:

```bash
git clone https://github.com/chhylp123/hifiasm
cd hifiasm && make
```

Another way is to install hifiasm via [bioconda](https://anaconda.org/bioconda/hifiasm):

```bash
conda install -c bioconda hifiasm
```

## Assembly Concepts

There are different types of assemblies which are commonly used in practice (see [details](https://lh3.github.io/2021/04/17/concepts-in-phased-assemblies)).
Hifiasm produces primary/alternate assemblies or partially phased assemblies only with HiFi reads. Given Hi-C data or trio-binning data, hifiasm produces contiguous fully-phased assemblies, i.e. haplotype-resolved assemblies.

## Why Hifiasm?

- Hifiasm delivers high-quality assemblies. It tends to generate longer contigs and resolve more segmental duplications than other assemblers.

- Given Hi-C reads or short reads from the parents, hifiasm can produce overall the best haplotype-resolved assembly so far. It is the assembler of choice by the [Human Pangenome Project](https://humanpangenome.org/) for the first batch of samples.

- Hifiasm can purge duplications between haplotigs without relying on third-party tools such as purge_dups. Hifiasm does not need polishing tools like pilon or racon, either. This simplifies the assembly pipeline and saves running time.

- Hifiasm is fast. It can assemble a human genome in half a day and assemble a ~30Gb redwood genome in three days. No genome is too large for hifiasm.

- Hifiasm is trivial to install and easy to use. It does not required Python, R or C++11 compilers, and can be compiled into a single executable. The default setting works well with a variety of genomes.

## Learn

- [HiFi-only Assembly](pa-assembly.md) - Assembling HiFi reads without additional data types
- [Trio-binning Assembly](trio-assembly.md) - Producing fully phased assemblies with HiFi and trio-binning data
- [Hi-C Integrated Assembly](hic-assembly.md) - Producing fully phased assemblies with HiFi and Hi-C data
- [Hifiasm Output](interpreting-output.md) - Interpreting results
- [Hifiasm FAQ](faq.md) - Frequently asked questions
- [Hifiasm Parameters](parameter-reference.md) - Parameter reference of hifiasm
