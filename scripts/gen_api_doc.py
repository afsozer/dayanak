"""Generate API reference from module docstrings (stdlib introspection only).

Usage:
    python scripts/gen_api_doc.py

Writes docs/API.md with function signatures and docstrings extracted via ast.
"""
import ast
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "emsal_mcp"
OUT_DIR = Path(__file__).resolve().parent.parent / "docs"
EXCLUDE_FILES = {"__init__.py", "__pycache__"}
EXCLUDE_DIRS = {"sources", "__pycache__"}


def extract_public_functions(filepath: Path) -> list[dict]:
    """Extract public functions with signatures and docstrings from a Python file."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))
    
    functions = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                # Get signature
                args = []
                for arg in node.args.args:
                    if arg.arg != "self" and arg.arg != "cls":
                        annotation = ""
                        if arg.annotation:
                            annotation = ast.unparse(arg.annotation)
                        args.append(f"{arg.arg}: {annotation}" if annotation else arg.arg)
                
                # Get return annotation
                ret = ""
                if node.returns:
                    ret = f" -> {ast.unparse(node.returns)}"
                
                sig = ", ".join(args)
                is_async = isinstance(node, ast.AsyncFunctionDef)
                prefix = "async " if is_async else ""
                
                # Get docstring
                docstring = ""
                if node.body:
                    first = node.body[0]
                    if isinstance(first, ast.Expr) and isinstance(first.value, (ast.Constant, ast.Str)):
                        val = first.value.value if isinstance(first.value, ast.Constant) else first.value.s
                        if isinstance(val, str):
                            docstring = val.strip()
                
                functions.append({
                    "name": node.name,
                    "signature": f"{prefix}def {node.name}({sig}){ret}",
                    "docstring": docstring,
                    "line": node.lineno,
                })
    
    return functions


def generate_api_doc() -> str:
    """Generate API reference markdown from all public functions."""
    lines = [
        "# Emsal-mcp API Reference",
        "",
        "Auto-generated from module docstrings.",
        "",
        "---",
        "",
    ]
    
    total_functions = 0
    total_with_docstring = 0
    
    for py_file in sorted(SRC_DIR.glob("*.py")):
        if py_file.name in EXCLUDE_FILES:
            continue
        
        module_name = py_file.stem
        functions = extract_public_functions(py_file)
        
        if not functions:
            continue
        
        total_functions += len(functions)
        total_with_docstring += sum(1 for f in functions if f["docstring"])
        
        lines.append(f"## `{module_name}`")
        lines.append("")
        
        for func in functions:
            lines.append(f"### `{func['signature']}`")
            lines.append("")
            
            if func["docstring"]:
                # Use first line as summary
                summary = func["docstring"].split("\n")[0].strip()
                lines.append(f"{summary}")
                lines.append("")
                
                # Add remaining docstring lines if they exist
                remaining = "\n".join(func["docstring"].split("\n")[1:]).strip()
                if remaining:
                    for dl in remaining.split("\n"):
                        lines.append(f"    {dl}")
                    lines.append("")
            else:
                lines.append("*No docstring.*")
                lines.append("")
            
            lines.append("---")
            lines.append("")
    
    # Add coverage summary
    coverage = (total_with_docstring / total_functions * 100) if total_functions > 0 else 0
    lines.append("## Coverage Summary")
    lines.append("")
    lines.append(f"- **Total public functions:** {total_functions}")
    lines.append(f"- **With docstrings:** {total_with_docstring}")
    lines.append(f"- **Coverage:** {coverage:.1f}%")
    lines.append("")
    
    return "\n".join(lines)


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    content = generate_api_doc()
    out_path = OUT_DIR / "API.md"
    out_path.write_text(content, encoding="utf-8")
    print(f"API reference generated: {out_path}")
    print(f"Content length: {len(content)} bytes")
