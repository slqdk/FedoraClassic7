# shellcheck shell=bash
# Shared helpers for the Classic 7 repo scripts. Sourced, not run.
# Works in Git Bash on Windows, on Linux and on macOS.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

REPO_NAME="FedoraClassic7"                                       # the GitHub repository
IMAGE_NAME="$(printf '%s' "$REPO_NAME" | tr '[:upper:]' '[:lower:]')"  # image names must be lowercase
TOOLS_DIR="$REPO_ROOT/.tools"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✘ %s\033[0m\n' "$*" >&2; exit 1; }

is_windows() { case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) return 0 ;; *) return 1 ;; esac; }

need() {
    local cmd="$1" hint="$2"
    command -v "$cmd" >/dev/null 2>&1 || die "$cmd is not installed. $hint"
}

need_git_gh() {
    if is_windows; then
        need git "Install it: open PowerShell and run:  winget install --id Git.Git -e"
        need gh  "Install it: open PowerShell and run:  winget install --id GitHub.cli -e   (then reopen Git Bash)"
    else
        need git "Install git with your package manager."
        need gh  "Install the GitHub CLI: https://cli.github.com"
    fi
}

# GitHub login with the 'workflow' scope (needed to push .github/workflows)
gh_login() {
    if ! gh auth status >/dev/null 2>&1; then
        step "Logging in to GitHub (a browser window opens; paste the code it shows)"
        gh auth login --hostname github.com --git-protocol https --web --scopes workflow
    elif ! gh auth status 2>&1 | grep -q "'workflow'\|workflow"; then
        step "Giving the GitHub CLI permission to push workflow files"
        gh auth refresh --hostname github.com --scopes workflow
    fi
    gh auth setup-git >/dev/null 2>&1 || true
    GH_USER="$(gh api user --jq .login)"
    [[ -n "$GH_USER" ]] || die "Could not read your GitHub user name."
    GH_USER_LC="$(printf '%s' "$GH_USER" | tr '[:upper:]' '[:lower:]')"
    REPO="$GH_USER/$REPO_NAME"
    IMAGE_REF="ghcr.io/$GH_USER_LC/$IMAGE_NAME"
    export GH_USER GH_USER_LC REPO IMAGE_REF
}

# Download cosign into .tools if it is not installed
ensure_cosign() {
    if command -v cosign >/dev/null 2>&1; then
        COSIGN="cosign"
        return
    fi
    local os arch file
    case "$(uname -s)" in
        Linux) os=linux ;;
        Darwin) os=darwin ;;
        MINGW*|MSYS*|CYGWIN*) os=windows ;;
        *) die "Unknown system $(uname -s); install cosign yourself: https://docs.sigstore.dev/cosign/system_config/installation/" ;;
    esac
    case "$(uname -m)" in
        x86_64|amd64) arch=amd64 ;;
        aarch64|arm64) arch=arm64 ;;
        *) die "Unknown CPU $(uname -m); install cosign yourself." ;;
    esac
    file="cosign-$os-$arch"
    [[ "$os" == windows ]] && file="$file.exe"
    COSIGN="$TOOLS_DIR/cosign"
    [[ "$os" == windows ]] && COSIGN="$COSIGN.exe"
    if [[ ! -x "$COSIGN" ]]; then
        step "Downloading cosign (used once, to make the image signing key)"
        mkdir -p "$TOOLS_DIR"
        curl -fsSL -o "$COSIGN" "https://github.com/sigstore/cosign/releases/latest/download/$file"
        chmod +x "$COSIGN"
    fi
}

# Files that must stay executable even when committed from Windows
fix_exec_bits() {
    local f
    for f in build_files/*.sh scripts/*.sh system_files/usr/bin/* system_files/usr/libexec/* tools/*.py; do
        [[ -f "$f" ]] && git update-index --chmod=+x "$f" 2>/dev/null || true
    done
}

latest_run_id() {
    # $1 = workflow file name; only runs on main (Dependabot pull requests build on their own branches)
    gh run list --repo "$REPO" --workflow "$1" --branch main --limit 1 --json databaseId --jq '.[0].databaseId // empty'
}

image_is_public() {
    # Anonymous pull token works only for public packages
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' \
        "https://ghcr.io/token?scope=repository:$GH_USER_LC/$IMAGE_NAME:pull")"
    [[ "$code" == 200 ]] || return 1
    local token
    token="$(curl -s "https://ghcr.io/token?scope=repository:$GH_USER_LC/$IMAGE_NAME:pull" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')"
    code="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $token" \
        -H "Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json" \
        "https://ghcr.io/v2/$GH_USER_LC/$IMAGE_NAME/manifests/latest")"
    [[ "$code" == 200 ]]
}

package_settings_url() {
    echo "https://github.com/users/$GH_USER/packages/container/$IMAGE_NAME/settings"
}
