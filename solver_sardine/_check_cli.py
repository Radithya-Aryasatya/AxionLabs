"""One-off syntax + import checker for cli_bridge."""
import sys, io, os
sys.path.insert(0, r"E:\Arkan\OpenAI_Competition\AxionLabs")
os.chdir(r"E:\Arkan\OpenAI_Competition\AxionLabs")
src = io.open(r"E:\Arkan\OpenAI_Competition\AxionLabs\solver_sardine\cli_bridge.py", encoding="utf-8").read()
import ast
ast.parse(src)
print("SYNTAX OK")
import importlib
m = importlib.import_module("solver_sardine.cli_bridge")
print("IMPORT OK", m.__file__)
