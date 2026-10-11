# Classic 7: Bazzite (Fedora Atomic, KDE Plasma, gaming-ready) with a Windows Standard look.

# --- Stage 1: build the GTK theme, icons and cursors from Chicago95 ------------------
FROM quay.io/fedora/fedora:44 AS assets
# Renovate/dependabot don't track this; bump the commit by hand when you want upstream fixes
ARG CHICAGO95_REF=5da19b8b1e2a886ebf6628403023d5fac3acc3ee
RUN dnf -y install --setopt=install_weak_deps=False git ImageMagick && dnf clean all
COPY build_files/assets.sh /assets.sh
RUN CHICAGO95_REF=${CHICAGO95_REF} bash /assets.sh

# --- Stage 2: build context (not copied into the final image) ------------------------
FROM scratch AS ctx
COPY build_files /
COPY system_files /system_files
COPY --from=assets /out /assets

# --- Stage 3: the image ---------------------------------------------------------------
# bazzite:stable = desktop KDE edition for AMD/Intel GPUs (the RX 7900 XTX needs nothing extra)
FROM ghcr.io/ublue-os/bazzite:stable

RUN --mount=type=bind,from=ctx,source=/,target=/ctx \
    --mount=type=cache,dst=/var/cache \
    --mount=type=cache,dst=/var/log \
    --mount=type=tmpfs,dst=/tmp \
    bash /ctx/build.sh

### LINTING
## Verify final image and contents are correct.
RUN bootc container lint
