#!/bin/sh
# The Harness Browser, inside its systemd unit (user maxxing-browser, no network of its own: PrivateNetwork).
# Two bridges, then Chromium:
#  - 127.0.0.1:3128 (this unit's own loopback) -> the proxy of Harness Maxxing (a unix socket of the run folder);
#  - the run folder's cdp.sock (0600) -> Chromium's DevTools port (this unit's own loopback, unreachable outside).
# Paths are the unit's mount points; MX_* override them (tests run it without a unit).
R="${MX_RUN:-/mxrun}"
P="${MX_PROXY_PORT:-3128}"
D="${MX_CDP_PORT:-9222}"
socat "TCP-LISTEN:$P,bind=127.0.0.1,reuseaddr,fork" "UNIX-CONNECT:$R/proxy.sock" &
socat "UNIX-LISTEN:$R/cdp.sock,mode=600,unlink-early,fork" "TCP:127.0.0.1:$D" &
exec "${MX_CHROME:-/opt/mxchrome/chrome}" --remote-debugging-port="$D" --remote-debugging-address=127.0.0.1 \
  --proxy-server="127.0.0.1:$P" --proxy-bypass-list='<-loopback>' "$@"
