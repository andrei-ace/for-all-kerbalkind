#!/bin/zsh
set -e

launcher_dir="${0:A:h}"
repo_dir="${launcher_dir:h}"
game_dir="${FAM_KSP_ROOT:-}"
if [[ -z "$game_dir" && -f "$launcher_dir/.ksp-root" ]]; then
    game_dir="$(<"$launcher_dir/.ksp-root")"
fi
if [[ -z "$game_dir" ]]; then
    printf '%s\n' 'Set FAM_KSP_ROOT to your isolated KSP folder or save its full path in dist/.ksp-root.' >&2
    exit 1
fi
game_dir="${game_dir:A}"
game_binary="$game_dir/KSP.app/Contents/MacOS/KSP"

if [[ ! -x "$game_binary" ]]; then
    printf 'The isolated KSP copy is missing at %s.\n' "$game_dir" >&2
    exit 1
fi

install_args=(--ksp-root "$game_dir")
if [[ -f "$game_dir/saves/default/persistent.sfs" ]]; then
    install_args+=(--sandbox default)
fi
python3 "$repo_dir/tools/install_local.py" "${install_args[@]}"
if [[ "${1:-}" == "--install-only" ]]; then
    exit 0
fi
cd -- "$game_dir"
exec "$game_binary" -screen-fullscreen 0 -logFile "$game_dir/For All Kerbalkind Player.log"
