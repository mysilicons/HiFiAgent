import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src" / "hifi_agent"


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
