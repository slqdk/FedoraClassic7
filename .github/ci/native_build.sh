# Builds and installs build_files/native the way build.sh does (sourced by the CI scripts; the image
# under test may be older than the branch). Logs go to /out/native-*.log.
devel=()
for pkg in cmake gcc-c++ extra-cmake-modules libplasma-devel kf6-kcoreaddons-devel kf6-kconfig-devel \
           kf6-kpackage-devel kf6-kwindowsystem-devel kf6-kidletime-devel qt6-qtbase-devel qt6-qtdeclarative-devel; do
    rpm -q "$pkg" >/dev/null 2>&1 || devel+=("$pkg")
done
((${#devel[@]})) && dnf5 -y install --setopt=install_weak_deps=False "${devel[@]}" > /out/native-dnf.log 2>&1
cmake -S /src/build_files/native -B /tmp/native-build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    -DKDE_INSTALL_PLUGINDIR=lib64/qt6/plugins -DKDE_INSTALL_LIBEXECDIR=libexec -DBUILD_TESTING=OFF > /out/native-build.log 2>&1
cmake --build /tmp/native-build -j4 >> /out/native-build.log 2>&1
cmake --install /tmp/native-build >> /out/native-build.log 2>&1
ls -la /usr/libexec/classic7-grab /usr/libexec/classic7-idle /usr/lib64/qt6/plugins/plasma/containmentactions/ >> /out/native-build.log 2>&1
