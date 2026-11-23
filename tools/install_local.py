"""Build, synchronize, and verify the isolated KSP installation."""

import argparse
import os
import re
from pathlib import Path
from shutil import copy2, copytree, rmtree
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from config import Node, read_node
from verify import verify
from parts import PARTS, ROOT

RELEASE = "FAMSeasons.zip"
REVIEW = "sandbox-review"
DIST = ROOT / "dist"

def tree(folder):
    return {
        path.relative_to(folder): path.read_bytes()
        for path in folder.rglob("*")
        if path.is_file()
    }


def same_file(source, destination):
    return destination.is_file() and source.read_bytes() == destination.read_bytes()


def replace_tree(source, destination):
    if tree(source) == tree(destination):
        return False
    # Use the receiving volume so the rename works with a Steam library on another disk.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as scratch:
        staged, previous = [Path(scratch) / name for name in ("staged", "previous")]
        copytree(source, staged)
        if destination.exists():
            os.replace(destination, previous)
        try:
            os.replace(staged, destination)
        except OSError:
            if previous.exists():
                os.replace(previous, destination)
            raise
    return True


def replace_file(source, destination):
    if same_file(source, destination):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as scratch:
        staged = Path(scratch) / destination.name
        copy2(source, staged)
        os.replace(staged, destination)
    return True


def old_fleet_save(path, retired_parts):
    game = read_node(path).children("GAME")[0]
    flight = game.children("FLIGHTSTATE")
    if not flight:
        return None
    old = [v for v in flight[0].children("VESSEL") if any(
        (name.startswith("fam") and name.endswith("Review")) or name in retired_parts
        for part in v.children("PART") for name in part.values("name"))]
    if not old:
        return None
    crew = {c for vessel in old for part in vessel.children("PART") for c in part.values("crew")}
    flight[0].entries = [e for e in flight[0].entries if not isinstance(e, Node) or e not in old]
    if flight[0].values("activeVessel"):
        flight[0].set("activeVessel", 0)
    if game.values("scene"):
        game.set("scene", 5)  # Space Center
    for roster in game.children("ROSTER"):
        for kerbal in roster.children("KERBAL"):
            if kerbal.values("name")[0] in crew:
                kerbal.set("state", "Available")
                if kerbal.values("seatIdx"):
                    kerbal.set("seatIdx", -1)
    return game


def install(game, sandbox=None, check=False):
    if not (game / "GameData/Squad").is_dir():
        raise ValueError(f"Squad is missing at {game}")
    if sandbox and (Path(sandbox).name != sandbox or not (game / "saves" / sandbox / "persistent.sfs").is_file()):
        raise ValueError("Choose an existing Sandbox save")
    archive = DIST / RELEASE
    with TemporaryDirectory() as scratch:
        payload = Path(scratch)
        with ZipFile(archive) as zipfile:
            zipfile.extractall(payload)
        verify(payload, game)
        core = Path("GameData/FAMSeasons")
        scenarios = Path("saves/scenarios")
        sources = [*(payload / "Ships/VAB").glob("*.craft"), *(payload / scenarios).glob("*.sfs"),
                   *(payload / scenarios / "banners").glob("*.png")]
        files = [(source, game / source.relative_to(payload)) for source in sources]
        if sandbox:
            files.extend((s, game / "saves" / sandbox / s.relative_to(payload)) for s in sources if s.suffix == ".craft")
        current_scenarios = {p.stem for p in sources if p.suffix == ".sfs"}
        retired = [game / "GameData/FAMSeasonsReview", DIST / REVIEW]
        for directory in [game / "Ships/VAB", *(game / "saves").glob("*/Ships/VAB")]:
            retired.extend(directory.glob("FAM S1 Review - *.craft"))
            retired.extend(directory.glob("FAM S1 Review - *.loadmeta"))
        for path in (game / scenarios).glob("FAM S1.*"):
            if path.is_dir():
                save = path / "persistent.sfs"
                if path.name not in current_scenarios or (save.is_file() and
                    not any(n.values("name") == ["FAMScenarioObjectives"] and n.values("fleet") == ["modular"]
                            for n in read_node(save).children("GAME")[0].children("SCENARIO"))):
                    retired.append(path)
            elif path.stem not in current_scenarios:
                retired.append(path)
        retired.extend(p for p in (game / scenarios / "banners").glob("FAM S1.*.png") if p.stem not in current_scenarios)
        retired.extend(p for p in DIST.glob("FAMSeasons-*.zip") if re.fullmatch(r"FAMSeasons-\d+\.\d+\.\d+\.zip", p.name))
        # Clear only the first-release project's retired craft from the isolated Sandbox.
        default = game / "saves/default"
        released_parts = {p.stem for p in (payload / core / "Season1/Parts").glob("*.cfg")}
        retired_parts = PARTS.keys() - released_parts
        for save in default.glob("*.sfs"):
            cleaned = old_fleet_save(save, retired_parts)
            if cleaned:
                target = payload / "cleaned" / save.name
                cleaned.write(target)
                files.append((target, save))
                retired.append(save.with_suffix(".loadmeta"))
        obsolete = [p for p in retired if p.exists()]
        diffs = [str(p) for p in obsolete]
        if not check:
            for path in obsolete:
                if path.is_dir():
                    rmtree(path)
                else:
                    path.unlink()
            changed = replace_tree(payload / core, game / core)
            if changed or game / "GameData/FAMSeasonsReview" in obsolete:
                for ext in ("ConfigCache", "ConfigSHA", "Physics", "TechTree"):
                    (game / "GameData" / ("ModuleManager." + ext)).unlink(missing_ok=True)
                (game / "PartDatabase.cfg").unlink(missing_ok=True)
            for source, target in files:
                if replace_file(source, target) and target.suffix == ".craft":
                    target.with_suffix(".loadmeta").unlink(missing_ok=True)
            diffs = [str(p) for p in retired if p.exists()]
        if tree(payload / core) != tree(game / core):
            diffs.append(str(game / core))
        diffs.extend(str(target) for source, target in files if not same_file(source, target))
        if diffs:
            raise ValueError("Installed game differs from " + archive.name + "\n" + "\n".join(diffs))
        print(f"Verified all modular parts, six VAB ships and three scenarios from {archive.name} in {game}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ksp-root", type=Path, required=True)
    parser.add_argument("--sandbox", help="Also copy the supplied craft into an existing Sandbox save.")
    parser.add_argument("--check", action="store_true", help="Compare the archive and installed game without writing.")
    args = parser.parse_args()
    install(args.ksp_root.resolve(), args.sandbox, args.check)
