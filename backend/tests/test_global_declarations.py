"""Guard against a silent UnboundLocalError from a missing `global` declaration.

`_run_generation` in routes/chat.py kept its reaper counter in a module-level
variable and did `_active_bg_generations += 1`.  Having *any* assignment in the
function makes Python treat the name as local for the whole body, so the first
read raised UnboundLocalError.  It went unnoticed because the raise happened
inside a `finally`, which meant every line after the try block was skipped —
including the fallback that persists a generation whose client disconnected.
The user-visible symptom was "connection lost, finishing in the background"
followed by an empty chat, with the real cause visible only in a Modal log.

This is a static check, not an execution test: the failure mode is a scoping
rule, so reading the AST is the reliable way to catch every instance at once.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _module_level_names(tree: ast.Module) -> set[str]:
    """Names bound at module scope by a plain assignment."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _functions(tree: ast.Module):
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _source_files() -> list[Path]:
    return [
        p
        for p in sorted(BACKEND.rglob("*.py"))
        if "tests" not in p.parts and "__pycache__" not in p.parts
    ]


def test_no_module_global_is_augmented_without_a_global_declaration():
    """`x += 1` on a module global inside a function requires `global x`.

    Augmented assignment is checked specifically rather than any assignment:
    it always reads before writing, so it raises UnboundLocalError outright on
    the first call.  (A plain `x = ...` may be a deliberately local shadow.)
    """
    offenders: list[str] = []

    for path in _source_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        module_names = _module_level_names(tree)
        if not module_names:
            continue

        for fn in _functions(tree):
            # ast.walk descends into nested defs, so a `global` declared by an
            # inner function legitimately covers the outer one's nested scope.
            declared = {n for s in ast.walk(fn) if isinstance(s, ast.Global) for n in s.names}
            augmented = {
                s.target.id
                for s in ast.walk(fn)
                if isinstance(s, ast.AugAssign) and isinstance(s.target, ast.Name)
            }
            for name in sorted((augmented & module_names) - declared):
                rel = path.relative_to(BACKEND)
                offenders.append(f"{rel}:{fn.lineno} {fn.name}() does `{name} += ...` without `global {name}`")

    assert not offenders, (
        "module-level variables are augmented inside a function without a "
        "`global` declaration — this raises UnboundLocalError on the first "
        "call:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("path", _source_files(), ids=lambda p: str(p.relative_to(BACKEND)))
def test_every_backend_module_parses(path: Path):
    """A file that cannot be parsed cannot be checked by the test above."""
    ast.parse(path.read_text(), filename=str(path))
