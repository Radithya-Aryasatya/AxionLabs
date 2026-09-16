"""Diagnostic: list top-level defs/classes and __all__ of Python files."""
import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

out = []
for rel in sys.argv[1:]:
    path = os.path.join(HERE, rel.replace("/", os.sep))
    try:
        tree = ast.parse(io.open(path, encoding="utf-8").read())
    except Exception as e:  # noqa: BLE001
        out.append("%s: PARSE FAIL %r" % (rel, e))
        continue
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            args = ""
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = "(" + ", ".join(a.arg for a in node.args.args) + ")"
            names.append("%s%s" % (node.name, args))
    exported = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "__all__":
            exported = [e.value for e in node.value.elts]
    out.append("=== %s ===" % rel)
    out.append("  defs: " + ", ".join(names))
    out.append("  __all__: " + ", ".join(exported))
    out.append("")

payload = "\n".join(out)
io.open(os.path.join(HERE, "_api_dump.txt"), "w", encoding="utf-8").write(payload)
sys.stdout.write(payload + "\n")