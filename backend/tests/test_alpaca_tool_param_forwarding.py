"""A declared tool parameter that the dispatcher never forwards is unreachable.

`alpaca_market_data` declared `option_type` in its schema, and
`execute_alpaca_market_data` accepted and used it — but the chat dispatcher never
passed it through. So a model asking for puts got an unfiltered chain, and since
Alpaca returns calls before puts, a page sized for a focused slice contained
calls only. The model concluded puts could not be fetched, and nothing in the
tool result said otherwise.

`page_token`, `start` and `end` were dropped the same way in the same call site;
the research dispatcher forwarded all four, which is why the defect survived —
one code path worked and masked the other.

This is a static check because the failure is structural: the schema and the call
site are independent declarations of the same interface, and only a diff of the
two reveals a gap. Driving the real dispatcher would need an LLM.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# schema constant, the executor whose call sites must honour it, and any
# property whose name deliberately differs from the parameter name.
TOOLS = [
    {
        "schema": "ALPACA_MARKET_DATA_TOOL",
        "func": "execute_alpaca_market_data",
        "aliases": {"type": "data_type"},
    },
]

DISPATCHERS = ["routes/chat.py", "core/research.py"]


def _dict_value(node: ast.AST, key: str) -> ast.AST | None:
    """Value for a string key in a dict literal."""
    if not isinstance(node, ast.Dict):
        return None
    for k, v in zip(node.keys, node.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _declared_properties(schema_name: str) -> set[str]:
    tree = ast.parse((BACKEND / "core" / "llm.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if schema_name not in [t.id for t in node.targets if isinstance(t, ast.Name)]:
                continue
            props = _dict_value(
                _dict_value(_dict_value(node.value, "function"), "parameters"), "properties"
            )
            assert isinstance(props, ast.Dict), f"{schema_name}: unreadable parameters.properties"
            return {k.value for k in props.keys if isinstance(k, ast.Constant)}
    raise AssertionError(f"{schema_name} not found in core/llm.py")


def _parameter_names(func_name: str) -> list[str]:
    """Parameter names of the executor, in declaration order (positional first)."""
    tree = ast.parse((BACKEND / "core" / "llm.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return [a.arg for a in node.args.args + node.args.kwonlyargs]
    raise AssertionError(f"{func_name} not found in core/llm.py")


def _call_sites(path: Path, func_name: str):
    """Yield (lineno, positional_count, keyword_names) for each call."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func_name:
            yield node.lineno, len(node.args), {kw.arg for kw in node.keywords if kw.arg}


def test_declared_tool_params_are_forwarded_by_every_dispatcher():
    failures: list[str] = []

    for tool in TOOLS:
        schema_name, func_name, aliases = tool["schema"], tool["func"], tool["aliases"]
        params = _parameter_names(func_name)
        # Schema property names translated to the parameter names they reach.
        expected = {aliases.get(p, p) for p in _declared_properties(schema_name)}
        found_any = False

        for rel in DISPATCHERS:
            for lineno, positional, keywords in _call_sites(BACKEND / rel, func_name):
                found_any = True
                # Positional arguments bind to the leading parameters by order.
                covered = set(params[:positional]) | keywords
                # `symbol` and the aliased `data_type` are passed positionally, so
                # drop them from the comparison; everything else must be explicit.
                missing = sorted(expected - covered)
                if missing:
                    failures.append(
                        f"{rel}:{lineno} calls {func_name}() without forwarding {missing}"
                    )

        assert found_any, f"no call to {func_name}() found in any dispatcher"

    assert not failures, (
        "a tool parameter is declared in the schema but never reaches the "
        "implementation, so the model can request it and silently not get it:\n  "
        + "\n  ".join(failures)
    )
