#!/usr/bin/env bash
# Builds the Classic 7 installer ISO on GitHub and downloads it into ./output/
#   ./scripts/build-iso.sh            start a new ISO build, wait, download
#   ./scripts/build-iso.sh --download download the ISO from the newest finished ISO build
# The ISO is only needed for new installs. Installed systems update themselves.
source "$(dirname "$0")/lib.sh"
need_git_gh
need curl "curl is missing."
gh_login

if [[ "${1:-}" != "--download" ]]; then
    step "Checking that the image can be downloaded"
    if ! image_is_public; then
        die "The image $IMAGE_REF:latest isn't public yet (or no build has finished).
   1. Wait for a green build:  ./scripts/status.sh --watch
   2. Make it public:          $(package_settings_url)
      (Danger Zone -> Change visibility -> Public), then run this again."
    fi
    ok "Image is public"

    step "Starting the ISO build on GitHub"
    before="$(latest_run_id build-disk.yml)"
    gh workflow run build-disk.yml --repo "$REPO" -f platform=amd64 -f upload-to-s3=false
    echo "Waiting for GitHub to start it..."
    for _ in $(seq 1 30); do
        sleep 5
        id="$(latest_run_id build-disk.yml)"
        [[ -n "$id" && "$id" != "$before" ]] && break
    done
    [[ -n "${id:-}" && "$id" != "$before" ]] || die "The ISO build didn't start. Check https://github.com/$REPO/actions"
    ok "ISO build started: https://github.com/$REPO/actions/runs/$id"
    echo "This takes 30-60 minutes. You can close this window and later run:  ./scripts/build-iso.sh --download"
    gh run watch "$id" --repo "$REPO" --exit-status --interval 30 || die "The ISO build failed - open the link above and look at the red step."
else
    id="$(gh run list --repo "$REPO" --workflow build-disk.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId // empty')"
    [[ -n "$id" ]] || die "No finished ISO build yet. Start one with:  ./scripts/build-iso.sh"
fi

step "Downloading the ISO (several GB, takes a while)"
rm -rf output/iso-download
mkdir -p output/iso-download
gh run download "$id" --repo "$REPO" -D output/iso-download
iso="$(find output/iso-download -type f -name '*.iso' | head -1)"
[[ -n "$iso" ]] || die "No .iso in the download. Look at the artifacts on https://github.com/$REPO/actions/runs/$id"
final="output/classic7-$(date +%Y-%m-%d).iso"
mv "$iso" "$final"
rm -rf output/iso-download
ok "ISO ready: $REPO_ROOT/$final"
if is_windows; then
    echo "In Explorer: $(cygpath -w "$REPO_ROOT/$final" 2>/dev/null || echo "$final")"
fi
