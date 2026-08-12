import ast
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src" / "hifi_agent"
CODE_ROOTS = (
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "scripts",
    PROJECT_ROOT / "workflow",
    PROJECT_ROOT / "configs",
    PROJECT_ROOT / "examples",
    PROJECT_ROOT / ".github",
)
CODE_SUFFIXES = {".config", ".j2", ".json", ".nf", ".py", ".sh", ".toml", ".yaml", ".yml"}
GENERATION_MARKER = re.compile(r"(?i)(?<![A-Za-z0-9])v[123](?![A-Za-z0-9])")
VERSIONED_CONTRACT_KEYS = tuple(
    f"{prefix}_{'version'}" for prefix in ("schema", "policy", "catalog", "parser")
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
