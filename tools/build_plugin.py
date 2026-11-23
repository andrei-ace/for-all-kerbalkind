"""Compile the flight compatibility module and Career parameter against KSP and CC."""

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from parts import PACK, ROOT


def managed_directory(game):
    candidates = [
        game / "KSP.app/Contents/Resources/Data/Managed",
        game / "KSP_x64_Data/Managed",
        game / "KSP_Data/Managed",
    ]
    managed = next((p for p in candidates if (p / "Assembly-CSharp.dll").is_file()), None)
    if managed is None:
        raise FileNotFoundError(f"No KSP 1 managed assemblies under {game}")
    return managed


def compile_csharp(game, dotnet, source, binary, target, extra_references=(), extra_sources=()):
    managed = managed_directory(game)
    sdk_paths = subprocess.check_output([str(dotnet), "--list-sdks"], text=True).splitlines()
    if not sdk_paths:
        raise RuntimeError("A .NET SDK with its Roslyn C# compiler is required")
    version, folder = sdk_paths[-1].split(" [", 1)
    compiler = Path(folder.removesuffix("]")) / version / "Roslyn/bincore/csc.dll"
    refs = [
        managed / p
        for p in (
            "mscorlib.dll",
            "System.dll",
            "System.Core.dll",
            "Assembly-CSharp.dll",
            "UnityEngine.dll",
            "UnityEngine.CoreModule.dll",
        )
    ]
    refs.append(game / "GameData/ContractConfigurator/ContractConfigurator.dll")
    refs.extend(extra_references)
    for ref in refs:
        if not ref.is_file():
            raise FileNotFoundError(ref)
    subprocess.run(
        [
            str(dotnet),
            str(compiler),
            "-nologo",
            "-noconfig",
            "-nostdlib+",
            "-langversion:7.3",
            "-target:" + target,
            "-platform:anycpu",
            "-optimize+",
            "-deterministic+",
            *["-reference:" + str(ref) for ref in refs],
            "-out:" + str(binary),
            str(source),
            *map(str, extra_sources),
        ],
        check=True,
        cwd=ROOT,
    )


def compile_plugin(game, dotnet):
    destination = PACK / "Plugins/FAMSeasons.dll"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        binary = Path(temp) / destination.name
        compile_csharp(
            game,
            dotnet,
            "src/HabitatCondition.cs",
            binary,
            "library",
            extra_references=[
                managed_directory(game) / name
                for name in ("UnityEngine.IMGUIModule.dll", "UnityEngine.TextRenderingModule.dll")
            ],
            extra_sources=[
                "src/StagingPolicy.cs",
                "src/ScenarioPlan.cs",
                "src/ScenarioObjectives.cs",
                "src/CrewAppearance.cs",
                "src/DockControls.cs",
                "src/BaseLift.cs",
            ],
        )
        os.replace(binary, destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ksp-root", type=Path, required=True)
    parser.add_argument("--dotnet", default="dotnet")
    args = parser.parse_args()
    compile_plugin(args.ksp_root, args.dotnet)
