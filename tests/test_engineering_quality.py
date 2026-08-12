import ast
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src" / "hifi_agent"
CODE_ROOTS = (
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "scripts",
    PROJECT_ROOT / "configs",
    PROJECT_ROOT / ".github",
)
CODE_SUFFIXES = {".config", ".j2", ".json", ".nf", ".py", ".sh", ".toml", ".yaml", ".yml"}
GENERATION_MARKER = re.compile(r"(?i)(?<![A-Za-z0-9])v[123](?![A-Za-z0-9])")
VERSIONED_CONTRACT_KEYS = tuple(
    f"{prefix}_{'version'}" for prefix in ("schema", "policy", "catalog", "parser")
)
MARKDOWN_FILES = (
    *sorted(PROJECT_ROOT.glob("*.md")),
    *sorted((PROJECT_ROOT / "docs").rglob("*.md")),
)


def _public_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not node.name.startswith(
            "_"
        ):
            functions.append(node)
    return functions


def test_public_functions_have_annotations_and_docstrings() -> None:
    failures: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for function in _public_functions(tree):
            missing_annotations = [
                argument.arg
                for argument in [*function.args.posonlyargs, *function.args.args]
                if argument.arg not in {"self", "cls"} and argument.annotation is None
            ]
            if function.args.vararg is not None and function.args.vararg.annotation is None:
                missing_annotations.append(f"*{function.args.vararg.arg}")
            if function.args.kwarg is not None and function.args.kwarg.annotation is None:
                missing_annotations.append(f"**{function.args.kwarg.arg}")
            if function.returns is None:
                missing_annotations.append("return")
            if ast.get_docstring(function) is None:
                location = f"{path.relative_to(PROJECT_ROOT)}:{function.lineno}"
                failures.append(f"{location}: missing docstring")
            if missing_annotations:
                failures.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{function.lineno}: "
                    f"missing annotations {', '.join(missing_annotations)}"
                )
    assert failures == []


def test_source_has_no_builtin_print_debug_calls() -> None:
    failures: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                failures.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert failures == []


def test_code_surface_has_no_generation_markers() -> None:
    """Keep the production implementation free of generation-specific names and contracts."""
    failures: list[str] = []
    paths = [
        path
        for root in CODE_ROOTS
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in CODE_SUFFIXES
        and not path.is_relative_to(SOURCE_ROOT / "data/knowledge")
    ]
    paths.extend((PROJECT_ROOT / "pyproject.toml", PROJECT_ROOT / "environment.yml"))
    for path in sorted(set(paths)):
        relative = path.relative_to(PROJECT_ROOT)
        content = path.read_text(errors="replace")
        if GENERATION_MARKER.search(str(relative)):
            failures.append(f"generation marker in path: {relative}")
        if GENERATION_MARKER.search(content):
            failures.append(f"generation marker in content: {relative}")
        for key in VERSIONED_CONTRACT_KEYS:
            if key in content:
                failures.append(f"versioned contract key `{key}` in {relative}")
    assert failures == []


def test_knowledge_contract_uses_neutral_identifiers() -> None:
    """Check generated knowledge metadata without scanning quoted third-party publications."""
    for relative in (
        "src/hifi_agent/data/knowledge/index.json",
        "src/hifi_agent/data/knowledge/index_manifest.json",
    ):
        payload = json.loads((PROJECT_ROOT / relative).read_text())
        assert payload["schema_id"] == "hifi-agent"
        assert payload["catalog_id"] == "production-knowledge"
        assert not set(VERSIONED_CONTRACT_KEYS).intersection(payload)


def test_public_policy_copy_matches_packaged_runtime_policy() -> None:
    public_policy = PROJECT_ROOT / "configs/comparison_policy.yaml"
    packaged_policy = PROJECT_ROOT / "src/hifi_agent/data/comparison_policy.yaml"
    assert public_policy.read_bytes() == packaged_policy.read_bytes()


def _markdown_anchors(content: str) -> set[str]:
    """Return GitHub-style heading anchors needed by local documentation links."""
    anchors: set[str] = set()
    counts: defaultdict[str, int] = defaultdict(int)
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*$", content, flags=re.MULTILINE):
        plain = re.sub(r"<[^>]+>", "", heading.replace("`", "")).strip().lower()
        slug = "".join(
            character for character in plain if character.isalnum() or character in " _-"
        )
        slug = re.sub(r"[\s]+", "-", slug)
        count = counts[slug]
        counts[slug] += 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def test_local_markdown_links_and_anchors_resolve() -> None:
    """Keep every repository-local documentation target navigable."""
    failures: list[str] = []
    link_pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^()\s]+)\)")
    for source in MARKDOWN_FILES:
        content = source.read_text()
        for raw_target in link_pattern.findall(content):
            if re.match(r"^[a-z][a-z0-9+.-]*:", raw_target, flags=re.IGNORECASE):
                continue
            target_value = unquote(raw_target.strip("<>"))
            path_value, separator, anchor = target_value.partition("#")
            target = source if not path_value else (source.parent / path_value).resolve()
            if not target.exists():
                failures.append(f"{source.relative_to(PROJECT_ROOT)} -> missing {target_value}")
                continue
            missing_anchor = (
                separator
                and target.is_file()
                and anchor not in _markdown_anchors(target.read_text())
            )
            if missing_anchor:
                failures.append(
                    f"{source.relative_to(PROJECT_ROOT)} -> missing anchor #{anchor} in "
                    f"{target.relative_to(PROJECT_ROOT)}"
                )
    assert failures == []


def test_public_documentation_has_english_and_chinese_pairs() -> None:
    """Keep English as the default while preserving a Chinese counterpart for every guide."""
    expected_pairs = [
        (PROJECT_ROOT / "README.md", PROJECT_ROOT / "README.zh-CN.md"),
        (PROJECT_ROOT / "CONTRIBUTING.md", PROJECT_ROOT / "CONTRIBUTING.zh-CN.md"),
        (PROJECT_ROOT / "CHANGELOG.md", PROJECT_ROOT / "CHANGELOG.zh-CN.md"),
        *[
            (english, PROJECT_ROOT / "docs" / "zh-CN" / english.name)
            for english in sorted((PROJECT_ROOT / "docs").glob("*.md"))
        ],
    ]
    failures: list[str] = []
    for english, chinese in expected_pairs:
        if not chinese.is_file():
            failures.append(f"missing Chinese counterpart for {english.relative_to(PROJECT_ROOT)}")
            continue
        if str(chinese.relative_to(english.parent)) not in english.read_text():
            failures.append(f"missing Chinese language link in {english.relative_to(PROJECT_ROOT)}")
        expected_english_link = (
            english.name if chinese.parent == PROJECT_ROOT else f"../{english.name}"
        )
        if expected_english_link not in chinese.read_text():
            failures.append(f"missing English language link in {chinese.relative_to(PROJECT_ROOT)}")
    assert failures == []


def test_documentation_yaml_fences_are_parseable() -> None:
    """Reject malformed YAML in public documentation examples."""
    failures: list[str] = []
    for source in MARKDOWN_FILES:
        for index, block in enumerate(
            re.findall(r"```yaml\n(.*?)\n```", source.read_text(), flags=re.DOTALL),
            start=1,
        ):
            try:
                yaml.safe_load(block)
            except yaml.YAMLError as exc:
                failures.append(f"{source.relative_to(PROJECT_ROOT)} block {index}: {exc}")
    assert failures == []


def test_public_tree_has_no_project_specific_organisms_or_personal_paths() -> None:
    """Prevent local acceptance subjects and developer paths from returning."""
    excluded_roots = {".git", "Data", "cache", "dist", "logs", "results"}
    text_suffixes = CODE_SUFFIXES | {".md", ".txt", ".tsv", ".cff"}
    files = [
        path
        for path in PROJECT_ROOT.rglob("*")
        if path.is_file()
        and path.suffix in text_suffixes
        and not excluded_roots.intersection(path.relative_to(PROJECT_ROOT).parts)
    ]
    organism_terms = tuple(
        "".join(parts)
        for parts in (
            ("Droso", "phila"),
            ("mela", "nogaster"),
            ("Ma", "lus"),
            ("domes", "tica"),
            ("Can", "dida"),
            ("albi", "cans"),
            ("Zizi", "phus"),
            ("ju", "juba"),
        )
    )
    failures: list[str] = []
    for path in files:
        content = path.read_text(errors="replace")
        for term in organism_terms:
            if re.search(rf"\b{re.escape(term)}\b", content, flags=re.IGNORECASE):
                failures.append(f"project-specific organism in {path.relative_to(PROJECT_ROOT)}")
        if re.search(r"/(?:home|data)/gw(?:/|\b)", content):
            failures.append(f"personal absolute path in {path.relative_to(PROJECT_ROOT)}")
    assert failures == []
