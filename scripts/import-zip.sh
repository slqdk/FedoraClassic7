#!/usr/bin/env bash
# Copies a new classic7.zip (for example a newer version from Claude) over this repo,
# keeping your git history, your signing key and your GitHub name.
#   ./scripts/import-zip.sh ~/Downloads/classic7.zip
# Then publish it:  ./scripts/publish.sh "New version"
source "$(dirname "$0")/lib.sh"

zip="${1:-}"
[[ -n "$zip" && -f "$zip" ]] || die "Usage: ./scripts/import-zip.sh path/to/classic7.zip"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
if command -v unzip >/dev/null 2>&1; then
    unzip -q "$zip" -d "$tmp"
elif is_windows; then
    powershell.exe -NoProfile -Command "Expand-Archive -LiteralPath '$(cygpath -w "$zip")' -DestinationPath '$(cygpath -w "$tmp")'"
else
    die "unzip is missing - install the 'unzip' package."
fi
src="$(dirname "$(find "$tmp" -maxdepth 2 -name Containerfile | head -1)")"
[[ -f "$src/Containerfile" ]] || die "That zip doesn't look like Classic 7 (no Containerfile)."

# keep these from the current repo
keep_org="$(sed -n 's/^REPO_ORGANIZATION=//p' image-template.env)"
keep_name="$(sed -n 's/^IMAGE_NAME=//p' image-template.env)"
keep_iso="$(grep -o 'ghcr.io/[^ ]*:latest' disk_config/iso.toml || true)"

step "Copying new files"
# remove tracked files that no longer exist in the new version (but never .git, keys, output)
while IFS= read -r f; do
    case "$f" in .git/*|cosign.*|output/*|.tools/*) continue ;; esac
    [[ -e "$src/$f" ]] || { git rm -q "$f" && echo "  removed $f"; }
done < <(git ls-files)
(cd "$src" && tar cf - --exclude=.git --exclude='cosign.*' --exclude=output --exclude=.tools .) | tar xf -

[[ -n "$keep_name" ]] && sed -i.bak "s/^IMAGE_NAME=.*/IMAGE_NAME=$keep_name/" image-template.env && rm -f image-template.env.bak
[[ -n "$keep_org" ]] && sed -i.bak "s/^REPO_ORGANIZATION=.*/REPO_ORGANIZATION=$keep_org/" image-template.env && rm -f image-template.env.bak
[[ -n "$keep_iso" ]] && sed -i.bak "s#ghcr.io/[^ ]*:latest#$keep_iso#" disk_config/iso.toml && rm -f disk_config/iso.toml.bak

git add -A
fix_exec_bits
step "What changed"
git diff --cached --stat | tail -20
echo
ok "Imported. Publish it with:  ./scripts/publish.sh \"New Classic 7 version\""
