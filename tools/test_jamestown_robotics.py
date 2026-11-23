"""Exercise the installed Jamestown review craft in a disposable copy of KSP."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from build_plugin import compile_csharp, managed_directory
from build_review import PREFIX, verify_review
from config import read_node
from parts import ROOT
from render_scenarios import clone_game

SAVE = "FAM Robotics Test"


def prepare(game, sandbox_save, output, dotnet):
    if read_node(sandbox_save).children("GAME")[0].values("Mode") != ["SANDBOX"]:
        raise ValueError("Choose a Sandbox .sfs to seed the disposable game")
    verify_review(game, game)
    output.mkdir(parents=True, exist_ok=True)
    clone = output / "game"
    clone_game(game, clone)
    vab = clone / "Ships/VAB"
    vab.mkdir(parents=True)
    for craft in (game / "Ships/VAB").glob(f"{PREFIX}*.craft"):
        shutil.copy2(craft, vab / craft.name)
    save = clone / "saves" / SAVE
    save.mkdir(parents=True)
    shutil.copy2(sandbox_save, save / "start.sfs")
    plugin = clone / "GameData/FAMRoboticsTest/Plugins/JamestownRoboticsFlightTest.dll"
    plugin.parent.mkdir(parents=True)
    managed = managed_directory(clone)
    compile_csharp(clone, dotnet, ROOT / "tools/JamestownRoboticsFlightTest.cs", plugin, "library", [
        managed / "UnityEngine.PhysicsModule.dll", managed / "UnityEngine.AnimationModule.dll",
        clone / "GameData/FAMSeasons/Plugins/FAMSeasons.dll",
    ], extra_sources=[ROOT / "tools/JamestownLightFlightTest.cs"])
    return clone


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ksp-root", type=Path, required=True)
    parser.add_argument("--sandbox-save", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New test game and Player.log directory")
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    game = prepare(args.ksp_root.resolve(), args.sandbox_save, output, args.dotnet)
    if args.prepare_only:
        print(f"Prepared {game}. Set FAM_ROBOTICS_TEST_SAVE='{SAVE}' when launching the clone.")
        return
    binary = next(game / name for name in ("KSP.app/Contents/MacOS/KSP", "KSP_x64.exe", "KSP_x64")
                  if (game / name).is_file())
    log = output / "Player.log"
    subprocess.run([binary, "-screen-fullscreen", "0", "-logFile", log], cwd=game,
                   env=dict(os.environ, FAM_ROBOTICS_TEST_SAVE=SAVE), timeout=420, check=True)
    if "[Jamestown test] PASS" not in log.read_text(errors="replace"):
        raise RuntimeError(f"KSP exited before the robotics test finished. See {log}")


if __name__ == "__main__":
    main()
