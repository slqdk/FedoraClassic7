#!/usr/bin/env bash
# Publishes your changes: commit, upload, and GitHub builds a new image.
# Installed Classic 7 PCs pick it up with their next update.
#   ./scripts/publish.sh "What I changed"
#   ./scripts/publish.sh --regen "New colours"   also redraw the theme files first (needs Python 3)
source "$(dirname "$0")/lib.sh"
need_git_gh
gh_login

regen=false
if [[ "${1:-}" == "--regen" ]]; then
    regen=true
    shift
fi
msg="${1:-Update Classic 7}"

if $regen; then
    step "Redrawing the theme files"
    py="$(command -v python3 || command -v python || true)"
    [[ -n "$py" ]] || die "Python 3 is needed for --regen."
    "$py" tools/generate_theme.py
fi

step "Checking scripts"
for f in build_files/*.sh scripts/*.sh system_files/usr/libexec/*; do
    bash -n "$f" || die "Syntax error in $f"
done
[[ ! -f cosign.key ]] || git check-ignore -q cosign.key || die "cosign.key is not ignored by git - refusing to publish it."
ok "Scripts look fine"

step "Committing"
git add -A
fix_exec_bits
if git diff --cached --quiet; then
    warn "No changes to publish."
else
    git -c core.autocrlf=false commit -q -m "$msg"
    ok "Committed: $msg"
fi

step "Uploading"
git pull --rebase -q origin main || die "Could not merge GitHub's version (did you edit files on github.com too?). Fix it with 'git status'."
git push -q origin main
ok "Uploaded. GitHub is building the new image."
echo "Follow it:  ./scripts/status.sh --watch"
echo "Then on the Classic 7 PC:  classic7-update"
