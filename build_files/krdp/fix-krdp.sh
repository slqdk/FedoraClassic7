#!/bin/bash
# KRdp (KDE's Remote Desktop server) 6.7 lets nobody log in once FreeRDP is 3.32 or newer: FreeRDP
# 3.32 turned "extended security" on by default, so clients get Network Level Authentication, which
# KRdp 6.7 doesn't do, and every login fails ("The logon attempt failed"). KDE bug 526514; fixed on
# KRdp's 6.7 branch after 6.7.5 and in 6.8. This builds the installed KRdp version's library with
# that one-line fix and puts it in place of the packaged one (krdpserver itself is unchanged, so
# the library stays the same version). Nothing is done when the installed KRdp has the fix already.
#
# classic7-logon.patch, applied in the same build, makes logging on from Windows forgiving: KRdp 6.7
# only lets in the user name exactly as the account is called here, and turned non-ASCII names and
# passwords (Søren, æ ø å) into something else; now any case, COMPUTER\name, name@computer and the
# account's full name work, names and passwords stay UTF-8, PAM's information messages no longer
# fail the logon, and a refused logon says why in the log (Event Viewer > Application).
#
#   fix-krdp.sh check   exit 0 when the fix is needed
#   fix-krdp.sh deps    the packages the build needs
#   fix-krdp.sh build   build and install (the packages from "deps" must be installed)
set -euo pipefail
mode="${1:-build}"
DEPS="cmake gcc-c++ extra-cmake-modules git-core qt6-qtbase-devel qt6-qtbase-private-devel qt6-qtdeclarative-devel
      qt6-qtwayland-devel wayland-devel kf6-kconfig-devel kf6-kdbusaddons-devel kf6-kcmutils-devel kf6-ki18n-devel
      kf6-kcoreaddons-devel kf6-kstatusnotifieritem-devel kf6-kcrash-devel kf6-kguiaddons-devel freerdp-devel
      libwinpr-devel kpipewire-devel libxkbcommon-devel qtkeychain-qt6-devel plasma-wayland-protocols-devel
      pam-devel systemd-devel"
# commits of KDE's release tags, checked after cloning (more can be added; others are built unchecked)
declare -A TAG_COMMITS=([6.7.5]=270dcf01851229134f74fa7d90ac338ec788ec67)

krdp_ver="$(rpm -q --qf '%{VERSION}' krdp 2>/dev/null)" || { echo "fix-krdp: KRdp is not installed"; exit 1; }
rdp_ver="$(rpm -q --qf '%{VERSION}' freerdp-libs 2>/dev/null)" || rdp_ver=0

needed() {
    [[ "$krdp_ver" == 6.7.* ]] || return 1                  # 6.8 and newer have the fix
    printf '3.32\n%s\n' "$rdp_ver" | sort -V -C             # FreeRDP 3.32 or newer
}

case "$mode" in
check)
    if needed; then echo "fix-krdp: KRdp $krdp_ver with FreeRDP $rdp_ver needs the fix"; exit 0; fi
    echo "fix-krdp: not needed (KRdp $krdp_ver, FreeRDP $rdp_ver)"; exit 1 ;;
deps)
    echo $DEPS; exit 0 ;;
build) ;;
*) echo "usage: fix-krdp.sh check|deps|build" >&2; exit 2 ;;
esac

needed || { echo "fix-krdp: not needed (KRdp $krdp_ver, FreeRDP $rdp_ver)"; exit 0; }
work="${TMPDIR:-/var/tmp}/classic7-krdp"
rm -rf "$work" && mkdir -p "$work"
git clone --quiet --depth 1 --branch "v$krdp_ver" https://github.com/KDE/krdp.git "$work/src"
commit="$(git -C "$work/src" rev-parse HEAD)"
if [[ -n "${TAG_COMMITS[$krdp_ver]:-}" && "$commit" != "${TAG_COMMITS[$krdp_ver]}" ]]; then
    echo "fix-krdp: v$krdp_ver is $commit, expected ${TAG_COMMITS[$krdp_ver]}" >&2
    exit 1
fi
src="$work/src/src/RdpConnection.cpp"
if grep -q 'FreeRDP_ExtSecurity' "$src"; then
    echo "fix-krdp: KRdp $krdp_ver already sets extended security"; exit 0
fi
sed -i '/freerdp_settings_set_bool(settings, FreeRDP_NlaSecurity, false);/a\    freerdp_settings_set_bool(settings, FreeRDP_ExtSecurity, false); // Classic 7: KDE bug 526514' "$src"
grep -q 'FreeRDP_ExtSecurity, false' "$src" || { echo "fix-krdp: the patch didn't apply" >&2; exit 1; }
git -C "$work/src" apply "$(dirname "$(readlink -f "$0")")/classic7-logon.patch" \
    || { echo "fix-krdp: classic7-logon.patch didn't apply" >&2; exit 1; }
cmake -S "$work/src" -B "$work/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr -DBUILD_TESTING=OFF \
    > "$work/cmake.log" 2>&1 || { tail -n 40 "$work/cmake.log" >&2; exit 1; }
cmake --build "$work/build" --target KRdp -j"$(nproc)" > "$work/build.log" 2>&1 || { tail -n 40 "$work/build.log" >&2; exit 1; }
built="$(find "$work/build" -name "libKRdp.so.$krdp_ver" -type f | head -1)"
[[ -n "$built" ]] || built="$(find "$work/build" -name 'libKRdp.so.*' -type f | head -1)"
# the packaged library file (not the symlinks)
target="$(rpm -ql $(rpm -qa 'krdp*') 2>/dev/null | grep -E '/libKRdp\.so\.[0-9]+(\.[0-9]+)+$' | sort | tail -1)"
[[ -n "$built" && -n "$target" && -f "$target" ]] || { echo "fix-krdp: library not found (built: $built, packaged: $target)" >&2; exit 1; }
strip --strip-unneeded "$built"
install -m 755 "$built" "$target"
echo "fix-krdp: $target rebuilt from KRdp $krdp_ver ($commit) with the FreeRDP 3.32 fix and Classic 7's logon fixes"
rm -rf "$work"
