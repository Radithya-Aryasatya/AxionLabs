"""One-off helper: dump key SC.Core C# source files into a text file for reading."""
from __future__ import annotations
import io, os

base = r"E:\Arkan\OpenAI_Competition\AI_modelsIntegration\sardine-can\SC.Core\ObjectModel"
files = [
    "Configuration/Configuration.cs",
    "Configuration/Solvers.cs",
    "Configuration/OptimizationGoal.cs",
    "IO/JsonIO.cs",
    "IO/Behavior/CapslockNamingPolicy.cs",
    "Rules/FlagRule.cs",
    "Rules/FlagRuleType.cs",
    "Rules/RuleSet.cs",
    "MethodType.cs",
    "Additionals/MeritType.cs",
    "Additionals/Objective.cs",
    "Additionals/ObjectiveType.cs",
    "Additionals/PieceOrder.cs",
    "Additionals/PieceReorder.cs",
]

out = io.open(r"E:\Arkan\OpenAI_Competition\AxionLabs\_sc_dump.txt", "w", encoding="utf-8")
for f in files:
    p = os.path.join(base, f.replace("/", os.sep))
    out.write("\n===== " + f + " =====\n")
    try:
        out.write(io.open(p, encoding="utf-8-sig").read())
    except Exception as e:  # noqa
        out.write("ERR " + str(e))
out.close()

# second batch
base2 = r"E:\Arkan\OpenAI_Competition\AI_modelsIntegration\sardine-can\SC.Core\ObjectModel"
files2 = [
    "InstanceIO.cs",
    "COSolution.cs",
    "Additionals/Constants.cs",
    "Elements/MeshCube.cs",
    "../Toolbox/Helper.cs",
]
out = io.open(r"E:\Arkan\OpenAI_Competition\AxionLabs\_sc_dump2.txt", "w", encoding="utf-8")
for f in files2:
    p = os.path.normpath(os.path.join(base2, f))
    out.write("\n===== " + f + " =====\n")
    try:
        out.write(io.open(p, encoding="utf-8-sig").read())
    except Exception as e:  # noqa
        out.write("ERR " + str(e))
out.close()
print("done")
