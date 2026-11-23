"""Read the shipped files with KSP's ConfigNode and resolve their real game/contract types."""

import argparse
import os
import platform
import subprocess
import tempfile
from pathlib import Path

from build_plugin import compile_csharp, managed_directory
from parts import ROOT


def run(game, payload, dotnet):
    game = game.resolve()
    managed = managed_directory(game)
    with tempfile.TemporaryDirectory() as output:
        work = Path(output)
        program = work / "StockSmoke.exe"
        managers = list((game / "GameData").glob("ModuleManager*.dll"))
        if len(managers) != 1:
            raise ValueError("The test installation needs exactly one ModuleManager DLL in GameData")
        plugin = payload / "GameData/FAMSeasons/Plugins/FAMSeasons.dll"
        compile_csharp(
            game,
            dotnet,
            "tools/StockSmoke.cs",
            program,
            "exe",
            [*managers, plugin],
            extra_sources=["tools/ScenarioSmoke.cs"],
        )
        if platform.system() == "Darwin":
            runtime = game / "KSP.app/Contents/Frameworks/libmonobdwgc-2.0.dylib"
            host = work / "stock-mono"
            # KSP 1.12.5 for macOS ships an Intel Mono runtime.
            subprocess.run(
                ["clang", "-arch", "x86_64", ROOT / "tools/mono_host.c", "-o", host],
                check=True,
            )
            command = [host, runtime]
        elif os.name == "nt":
            command = []
        else:
            command = ["mono"]
        subprocess.run(
            [*command, program, managed, game / "GameData", payload.resolve()],
            check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ksp-root", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT, help="Release or source tree to check")
    parser.add_argument("--dotnet", default="dotnet")
    args = parser.parse_args()
    run(args.ksp_root, args.root, args.dotnet)
