# SubSync Echo for home servers: the command line app (no window), running
# watch mode on /media by default. See doc/home-server.md.
#
# Made from the Linux package the release workflow builds and tests, so it is
# the same app: put the package in this folder as subsync-linux-x86_64.tar.xz
# and run "docker build -t subsync-echo docker". Ubuntu 22.04 is the system
# the package is built on.
FROM ubuntu:22.04

LABEL org.opencontainers.image.title="SubSync Echo" \
      org.opencontainers.image.description="Syncs subtitles to a video's audio, in almost any language; watch mode syncs new subtitles in media server libraries" \
      org.opencontainers.image.source="https://github.com/resonaut/SubSync-Echo" \
      org.opencontainers.image.documentation="https://github.com/resonaut/SubSync-Echo/blob/master/doc/home-server.md" \
      org.opencontainers.image.licenses="GPL-3.0-only"

# certificates for downloading the models the first time
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /config /media \
    && chmod 777 /config

# unpacks to /opt/subsync
ADD subsync-linux-x86_64.tar.xz /opt/

# settings, the watch state file and the downloaded models (about 980 MB)
# all go to /config, so they're kept when the container is replaced; any user
# can write there (run with --user to match the owner of your media)
ENV HOME=/config
VOLUME /config
USER 1000:1000

# docker stop sends Ctrl-C: watch mode stops between subtitles, or stops the
# sync in progress and leaves that subtitle as it was
STOPSIGNAL SIGINT

ENTRYPOINT ["/opt/subsync/subsync-cmd"]
CMD ["--cli", "watch", "--dir", "/media", "--state", "/config/watch-state.json"]
