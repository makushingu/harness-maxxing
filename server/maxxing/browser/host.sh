#!/bin/sh
# The Harness Browser, inside its systemd unit (user maxxing-browser, no network of its own: PrivateNetwork).
# Two bridges, then Chromium:
#  - 127.0.0.1:3128 (this unit's own loopback) -> the proxy of Harness Maxxing (a unix socket of the run folder);
#  - the run folder's cdp.sock (0600) -> Chromium's DevTools port (this unit's own loopback, unreachable outside).
# Paths are the unit's mount points; MX_* override them (tests run it without a unit).
# Inside the unit, HOME is always the unit's private /tmp, whatever the launcher passed (a wrapper's --setenv wins
# over the unit's Environment=): Chromium's crash handler needs a writable HOME, or Chromium stops at once.
[ -z "$MX_RUN" ] && export HOME=/tmp XDG_CONFIG_HOME=/tmp/.config XDG_CACHE_HOME=/tmp/.cache
R="${MX_RUN:-/mxrun}"
P="${MX_PROXY_PORT:-3128}"
D="${MX_CDP_PORT:-9222}"
socat "TCP-LISTEN:$P,bind=127.0.0.1,reuseaddr,fork" "UNIX-CONNECT:$R/proxy.sock" &
socat "UNIX-LISTEN:$R/cdp.sock,mode=600,unlink-early,fork" "TCP:127.0.0.1:$D" &
exec "${MX_CHROME:-/opt/mxchrome/chrome}" --remote-debugging-port="$D" --remote-debugging-address=127.0.0.1 \
  --proxy-server="127.0.0.1:$P" --proxy-bypass-list='<-loopback>' "$@"
