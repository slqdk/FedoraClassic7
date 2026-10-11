#!/usr/bin/env bash
# One-time setup: puts this folder on GitHub as <you>/FedoraClassic7 and starts the first image build.
#
#   1. logs you in to GitHub (browser)
#   2. makes the image signing key (cosign) and stores it as the repo secret SIGNING_SECRET
#   3. creates the public repo, pushes everything, and the build starts by itself
#
# Run it from Git Bash (Windows) or a terminal (Linux/macOS):   ./scripts/setup-github.sh
# Safe to run again: steps already done are skipped.
source "$(dirname "$0")/lib.sh"

bold "Classic 7 - GitHub setup"
need_git_gh
need curl "curl is missing."
gh_login
ok "Logged in as $GH_USER"

# --- Your name in the files ---------------------------------------------------------
step "Putting your GitHub name into the config"
sed -i.bak "s/^REPO_ORGANIZATION=.*/REPO_ORGANIZATION=\"$GH_USER_LC\"/" image-template.env && rm -f image-template.env.bak
sed -i.bak "s#ghcr.io/[^ ]*:latest#$IMAGE_REF:latest#" disk_config/iso.toml && rm -f disk_config/iso.toml.bak
ok "image-template.env and disk_config/iso.toml now point at $IMAGE_REF"

# --- Local git repository -------------------------------------------------------------
step "Preparing the local git repository"
if [[ ! -d .git ]]; then
    git init -q -b main
fi
git config core.autocrlf false
git config core.filemode false
if [[ -z "$(git config user.name || true)" ]]; then
    git config user.name "$(gh api user --jq '.name // .login')"
fi
if [[ -z "$(git config user.email || true)" ]]; then
    git config user.email "$(gh api user --jq '.id')+$GH_USER@users.noreply.github.com"
fi

# --- Signing key ------------------------------------------------------------------------
KEY_BACKUP="$HOME/.classic7/cosign.key"
if [[ ! -f cosign.pub ]]; then
    ensure_cosign
    step "Making the image signing key"
    COSIGN_PASSWORD="" "$COSIGN" generate-key-pair
    mkdir -p "$(dirname "$KEY_BACKUP")"
    cp cosign.key "$KEY_BACKUP"
    ok "Key made. A backup of the private key is in $KEY_BACKUP (never share it, never commit it)"
else
    ok "cosign.pub already exists - keeping the existing key"
fi
grep -qx 'cosign.key' .gitignore || echo 'cosign.key' >> .gitignore
grep -qx '.tools/' .gitignore || echo '.tools/' >> .gitignore
grep -qx 'output/' .gitignore || echo 'output/' >> .gitignore

# --- Commit -------------------------------------------------------------------------------
step "Committing the files"
git add -A
fix_exec_bits
git rm -q --cached cosign.key 2>/dev/null || true
if ! git diff --cached --quiet; then
    git commit -q -m "Classic 7 setup"
    ok "Committed"
else
    ok "Nothing new to commit"
fi

# --- GitHub repository ----------------------------------------------------------------
step "Creating the GitHub repository $REPO"
if gh repo view "$REPO" >/dev/null 2>&1; then
    ok "Repository already exists"
else
    gh repo create "$REPO" --public --description "Classic 7: a Windows 7 Classic style gaming desktop on Bazzite"
    ok "Repository created"
fi
if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "https://github.com/$REPO.git"
else
    git remote add origin "https://github.com/$REPO.git"
fi

# --- Secret before the first push, so the first build can sign -------------------------
step "Storing the signing key as the repository secret SIGNING_SECRET"
if [[ -f cosign.key ]]; then
    gh secret set SIGNING_SECRET --repo "$REPO" < cosign.key
elif [[ -f "$KEY_BACKUP" ]]; then
    gh secret set SIGNING_SECRET --repo "$REPO" < "$KEY_BACKUP"
else
    die "cosign.key not found. Delete cosign.pub and run this script again to make a new key."
fi
ok "Secret stored"

# --- Push = first build -----------------------------------------------------------------
step "Uploading (this starts the first build on GitHub)"
git push -u origin main
gh api -X PUT "repos/$REPO/actions/permissions" -F enabled=true -f allowed_actions=all >/dev/null 2>&1 || true
ok "Uploaded: https://github.com/$REPO"

# A push made before GitHub has registered the workflows starts nothing; start it by hand then
sleep 15
if [[ -z "$(latest_run_id build.yml)" ]]; then
    step "Starting the first build"
    gh workflow run build.yml --repo "$REPO" --ref main
fi

cat <<EOF

$(bold "Done. What happens now:")
  - GitHub is building your image (about 20-40 minutes). Watch it with:
        ./scripts/status.sh
    or in the browser: https://github.com/$REPO/actions
  - When the build is green, make the image public (one click, see the guide):
        $(package_settings_url)
  - Then build the installer:
        ./scripts/build-iso.sh
EOF
