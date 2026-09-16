"""One-off: truncate the duplicate tail of solver_sardine/cli_bridge.py."""
import io

P = "solver_sardine/cli_bridge.py"
lines = io.open(P, encoding="utf-8").read().splitlines(keepends=True)
keep = lines[:451]                      # through the first __all__ block
with io.open(P, "w", encoding="utf-8", newline="") as fh:
    fh.write("".join(keep))
print("kept", len(keep), "lines")
