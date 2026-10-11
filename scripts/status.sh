#!/usr/bin/env bash
# Shows how the GitHub builds are doing and whether the image is ready to install.
#   ./scripts/status.sh          overview
#   ./scripts/status.sh --watch  follow the newest image build live until it finishes
source "$(dirname "$0")/lib.sh"
need_git_gh
gh_login

if [[ "${1:-}" == "--watch" ]]; then
    id="$(latest_run_id build.yml)"
    [[ -n "$id" ]] || die "No image build has run yet."
    gh run watch "$id" --repo "$REPO" --exit-status && ok "Image build finished" || die "Image build failed - see https://github.com/$REPO/actions/runs/$id"
    exit 0
fi

bold "Classic 7 - $REPO"
step "Image builds (newest first)"
gh run list --repo "$REPO" --workflow build.yml --limit 5 || true
step "Installer (ISO) builds"
gh run list --repo "$REPO" --workflow build-disk.yml --limit 3 || true

step "Image"
if image_is_public; then
    ok "$IMAGE_REF:latest is published and public - installs and updates can download it"
else
    warn "$IMAGE_REF:latest is not downloadable yet."
    echo "  - If no build is green yet: wait for it (./scripts/status.sh --watch)."
    echo "  - If a build is green: make the package public here:"
    echo "      $(package_settings_url)"
    echo "    (Danger Zone -> Change visibility -> Public)"
fi
