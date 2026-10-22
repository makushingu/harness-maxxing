#!/usr/bin/env bash
# =============================================================================================
#  Harness Maxxing - one-line installer (Ubuntu / Debian with systemd, x86_64 or arm64, as root)
#
#  Install from the public git repository (no key needed; updates come from git):
#    curl -fsSL https://get.harness-maxxing.com | bash
#  An Enterprise key (optional, companies only) can be given too: LICENSE=HM-XXXX-XXXX-XXXX-XXXX (recorded, nothing else changes)
#  From a private fork or mirror (read token): GH_TOKEN=$T REPO=owner/name bash install.sh
#  Install from a local copy of the code (an unpacked archive or a clone, web/dist built), no network
#  for the code itself (updates then come from a new copy: SOURCE_DIR=... bash install.sh again):
#    bash /path/to/harness-maxxing/install.sh        (or SOURCE_DIR=/path/to/harness-maxxing bash install.sh)
#  Options (pass them after `bash -s --` when piping):
#    --check              only look at this server and say what the install would do (changes nothing)
#    --update             update an existing install (= maxxing update)
#    --uninstall          remove service + integrations (= maxxing uninstall), keeps the workspace
#      --purge            ... also remove the code and the state directory
#      --purge-workspace  ... also remove the workspace (irreversible)
#    -h, --help
#
#  Unattended: answer with variables and ASSUME_YES=1, e.g.
#    curl -fsSL https://get.harness-maxxing.com | ACCESS=domain DOMAIN=ui.example.com ASSUME_YES=1 bash
#  Variables (default):
#    LICENSE (optional: an Enterprise key, recorded - or later in Settings -> License)  LICENSE_API (https://api.harness-maxxing.com)
#    REPO (makushingu/harness-maxxing)  BRANCH (stable)  GH_TOKEN (private fork or mirror only)  INSTALL_DIR (/opt/claude-maxxing)
#    WORKSPACE (/root/maxxing)  STATE_DIR (/var/lib/claude-maxxing)  PORT (8787)
#    ACCESS (domain|tailscale|local)  DOMAIN  ASSUME_YES (0)
#    TIMEZONE (system zone - also chosen later in the web onboarding, which switches the system clock)
#    RESTORE_FROM (owner/name of a memory backup repo)  RESTORE_TOKEN (asked when not set)
#    RESTORE_TRUST (0 - 1: turn on the restored jobs, extensions, hooks, MCP servers and customizations without asking)
#    ALLOW_UNPROTECTED (0 - 1: go on when a protection fails to turn on: security updates, fail2ban, firewall)
#    CLAUDE_TOKEN (output of `claude setup-token`, optional)  ANTHROPIC_API_KEY (optional)
#    VOICE (local - default: Whisper on this server, model downloaded in the background; under 3 GB of memory it is
#      off unless you set VOICE=local and confirm | groq | openai | off)
#    TOOLS (background - default: Node.js, Chromium, Remotion, Scrapling, the voice model are installed by
#      `maxxing deps update` once the service runs | foreground: wait for them | 0: skip, `maxxing deps update` later)
#    SWAP (auto - a 2 GB /swapfile when the server has under 4 GB of memory and no swap, on a fresh server only |
#          1 - the same on a server already in use | 0 never)
#    SOURCE_DIR (a local copy of the code to install instead of a git / release download)
#    FIREWALL (auto - enabled only on a server with nothing else exposed | 1 always | 0 never)
#    SSH_HARDEN (auto - SSH password logins are turned off only when this very session is proven to use a key
#      | 1 also when a key is installed but the session cannot be checked | 0 never touch SSH)
#    SYSTEM_CLOCK (auto | follow: the system zone follows yours | keep: never touch it - default on used servers)
#    CLAUDE_DIR (~/.claude - another folder, e.g. /root/.claude-harness, keeps Harness Maxxing apart from a Claude
#      Code already used here: its own skills, global CLAUDE.md, transcripts and sign-in. When Claude Code is
#      already used and CLAUDE_DIR is not set, the installer asks: own folder ~/.claude-harness (default) or share)
#
#  Re-runnable: every step keeps what exists. The server never listens on a public interface.
#  Secrets (license key, tokens) are best typed at the prompts (hidden) or set with `read -rs NAME; export NAME`:
#  never on the command line, where they stay in the shell history and are visible in `ps`.
# =============================================================================================
set -euo pipefail
umask 077                     # everything the installer creates is private unless it says otherwise (chmod)
cd /                          # never run from a directory another user controls
unset BASH_ENV ENV CDPATH PYTHONPATH PYTHONHOME PYTHONSTARTUP LD_PRELOAD LD_LIBRARY_PATH NODE_OPTIONS GIT_DIR GIT_WORK_TREE \
  GIT_CONFIG_PARAMETERS GIT_CONFIG_COUNT 2>/dev/null || true

REPO="${REPO:-makushingu/harness-maxxing}"
# every install follows `stable` (published versions); an Enterprise key changes nothing there (2.0.0a88)
BRANCH="${BRANCH:-stable}"
GH_TOKEN="${GH_TOKEN:-}"
LICENSE="${LICENSE:-}"
LICENSE_API="${LICENSE_API:-https://api.harness-maxxing.com}"
LICENSED=0          # 1 = code comes from a signed release (license), not from git
RELEASE_JSON=""
# public keys that sign the releases (message "harness-maxxing|<version>|<sha256>"), by key id: a release that names
# its key with `kid` is checked with that key only (an unknown id is refused), one without `kid` with every key below.
# Same list as PUBKEYS in server/maxxing/license.py.
RELEASE_KIDS="k1"
# shellcheck disable=SC2034  # read through ${!name} (release_pubkey)
RELEASE_PUBKEY_k1='-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAfg3vG94nEzS93VB0zGtE2RH+1VF317mLumbHgMMkOPY=
-----END PUBLIC KEY-----'
# a signed release older than this one is refused (an old version replayed with its known holes)
MIN_VERSION="2.0.0a68"

# ---- third-party downloads ------------------------------------------------------------------
# Versions, URLs and sha256 of uv, Claude Code, Node.js, Caddy's key... are in server/maxxing/deps.toml (the same
# manifest `maxxing deps` reads): `dep` below reads it from the code once it is here, and every download goes through
# fetch_verified (HTTPS, private work folder, sha256 checked before anything runs or is extracted).
# a script run from a source tree (bash ./install.sh in an unpacked archive or a clone) installs that tree
SELF_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SELF_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P || true)
fi
INSTALL_DIR="${INSTALL_DIR:-/opt/claude-maxxing}"
WORKSPACE="${WORKSPACE:-/root/maxxing}"
STATE_DIR="${STATE_DIR:-/var/lib/claude-maxxing}"
PORT="${PORT:-8787}"
ACCESS="${ACCESS:-}"
DOMAIN="${DOMAIN:-}"
TIMEZONE="${TIMEZONE:-}"
ASSUME_YES="${ASSUME_YES:-0}"
RESTORE_FROM="${RESTORE_FROM:-}"
RESTORE_TOKEN="${RESTORE_TOKEN:-}"
CLAUDE_TOKEN="${CLAUDE_TOKEN:-}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
VOICE_GIVEN="${VOICE:+1}"   # set by the caller (not the default): a small server asks before taking it
VOICE="${VOICE:-local}"
SOURCE_DIR="${SOURCE_DIR:-}"
TOOLS="${TOOLS:-background}"
SWAP="${SWAP:-auto}"
MEMINFO=/proc/meminfo
FIREWALL="${FIREWALL:-auto}"
SSH_HARDEN="${SSH_HARDEN:-auto}"
SYSTEM_CLOCK="${SYSTEM_CLOCK:-auto}"
CLAUDE_DIR="${CLAUDE_DIR:-}"
RESTORE_TRUST="${RESTORE_TRUST:-0}"
ALLOW_UNPROTECTED="${ALLOW_UNPROTECTED:-0}"
# secrets stay in shell variables: no child process (apt, curl, npm, the Claude installer...) inherits them
export -n LICENSE GH_TOKEN RESTORE_TOKEN CLAUDE_TOKEN ANTHROPIC_API_KEY 2>/dev/null || true
unset MAXXING_GITHUB_TOKEN 2>/dev/null || true
WORK=$(mktemp -d /tmp/harness-install.XXXXXXXX)   # every download, script and log of this run (removed at exit)
WORK0=$WORK                                        # the one on_exit removes (tests point WORK elsewhere)
export TMPDIR="$WORK"                              # temporary files of apt, uv, npm, claude... go there too

SERVICE=claude-maxxing
UNIT=/etc/systemd/system/$SERVICE.service
CADDY_SITE=/etc/caddy/claude-maxxing.caddy
CADDYFILE=/etc/caddy/Caddyfile
SSHD_CONFIG=/etc/ssh/sshd_config
SSH_DROPIN=/etc/ssh/sshd_config.d/01-harness-maxxing.conf
BIN=/usr/local/bin/maxxing
DEFAULT_STATE=/var/lib/claude-maxxing
TOTAL=11
LOCAL=0             # 1 = code copied from SOURCE_DIR (no license, no git remote)
STEP=0
IN_STEP=0
SPIN_PID=""
STEP_LOG=""
T_START=$SECONDS
BIND=127.0.0.1
PUBLIC_URL=""
AFTER=""
TOKEN_USED=0
# filled by detect_server (pre-flight check of a server that may already be in use)
EXISTING=0          # 1 = the server already runs other things: be careful
PRIOR=0             # 1 = Harness Maxxing was already installed here (a re-run)
PUBLIC_OTHER=""     # other services listening on public interfaces ("port/process ...")
WEB_BUSY=""         # process holding port 80/443 that is not Caddy (nginx, apache2, docker-proxy...)
FW_ACTIVE=""        # ufw | nftables | "" (no firewall rules)
HAS_DOCKER=0
OTHER_CRON=0        # root crontab lines that are not ours
NODE_OLD=""         # an older Node.js already installed (path) -> ours stays in <state>/tools/nodejs
BRIDGES=""          # other Telegram bridges / agents found (process or unit names)
CLAUDE_SETUP=""     # existing Claude Code setup (skills, CLAUDE.md, signed in)

# ---- output ---------------------------------------------------------------------------------
FANCY=0
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != dumb ]; then
  FANCY=1
  C_B=$'\033[1m'; C_D=$'\033[2m'; C_G=$'\033[38;5;42m'; C_Y=$'\033[38;5;214m'; C_R=$'\033[38;5;203m'
  C_C=$'\033[38;5;75m'; C_A=$'\033[38;5;33m'; C_W=$'\033[97m'; C_0=$'\033[0m'
  BLUES=(27 33 39 45 51 87)
else
  C_B=""; C_D=""; C_G=""; C_Y=""; C_R=""; C_C=""; C_A=""; C_W=""; C_0=""
  BLUES=()
fi
ok()   { printf '      %s✔%s %s\n' "$C_G" "$C_0" "$*"; }
warn() { printf '      %s!%s %s\n' "$C_Y" "$C_0" "$*"; }
info() { printf '      %s%s%s\n' "$C_D" "$*" "$C_0"; }
die()  { printf '      %s✘ %s%s\n' "$C_R" "$*" "$C_0" >&2; exit 1; }
section() { printf '\n  %s◆%s %s%s%s\n' "$C_A" "$C_0" "$C_B" "$*" "$C_0"; }
fmt_secs() { local s=$1; if [ "$s" -ge 60 ]; then printf '%d min %02d s' $((s / 60)) $((s % 60)); else printf '%d s' "$s"; fi; }

logo() {
  local lines=(
'███╗   ███╗ █████╗ ██╗  ██╗██╗  ██╗██╗███╗   ██╗ ██████╗ '
'████╗ ████║██╔══██╗╚██╗██╔╝╚██╗██╔╝██║████╗  ██║██╔════╝ '
'██╔████╔██║███████║ ╚███╔╝  ╚███╔╝ ██║██╔██╗ ██║██║  ███╗'
'██║╚██╔╝██║██╔══██║ ██╔██╗  ██╔██╗ ██║██║╚██╗██║██║   ██║'
'██║ ╚═╝ ██║██║  ██║██╔╝ ██╗██╔╝ ██╗██║██║ ╚████║╚██████╔╝'
'╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝ ╚═════╝ ')
  echo
  if [ "$FANCY" = 1 ] && [ "$(tput cols 2>/dev/null || echo 80)" -ge 64 ]; then
    printf '  %s%sH A R N E S S%s\n' "$C_B" "$C_C" "$C_0"
    local i
    for i in "${!lines[@]}"; do printf '  \033[38;5;%sm%s%s\n' "${BLUES[$i]}" "${lines[$i]}" "$C_0"; done
  else
    printf '  %sHARNESS MAXXING%s\n' "$C_B" "$C_0"
  fi
  printf '  %sThe control room for Claude Code on your own server%s\n' "$C_D" "$C_0"
}

# step_begin "Title" - numbered step; its output is captured and shown once it ends, a spinner runs meanwhile
step_begin() {
  STEP=$((STEP + 1)); STEP_TITLE=$1; STEP_T0=$SECONDS; IN_STEP=1
  if [ "$FANCY" = 1 ]; then
    STEP_LOG=$(mktemp "$WORK/step.XXXXXX")
    exec 3>&1 4>&2
    (
      trap 'exit 0' TERM
      f='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'; i=0; t0=$SECONDS
      while :; do
        printf '\r  %s%s%s %s%d/%d%s  %s  %s%s%s\033[K' "$C_A" "${f:i%10:1}" "$C_0" "$C_D" "$STEP" "$TOTAL" "$C_0" \
          "$STEP_TITLE" "$C_D" "$(fmt_secs $((SECONDS - t0)))" "$C_0" >&3
        i=$((i + 1)); sleep 0.1
      done
    ) &
    SPIN_PID=$!
    exec >"$STEP_LOG" 2>&1
  else
    printf '\n[%d/%d] %s\n' "$STEP" "$TOTAL" "$STEP_TITLE"
  fi
}

step_end() { # step_end ok|fail
  local status=${1:-ok} took=$((SECONDS - STEP_T0)) mark
  IN_STEP=0
  [ "$FANCY" = 1 ] || return 0
  if [ -n "$SPIN_PID" ]; then kill "$SPIN_PID" 2>/dev/null; wait "$SPIN_PID" 2>/dev/null || true; SPIN_PID=""; fi
  exec 1>&3 2>&4 3>&- 4>&-
  if [ "$status" = ok ]; then mark="$C_G✔$C_0"; else mark="$C_R✘$C_0"; fi
  printf '\r\033[K  %s %s%d/%d%s  %s%s%s  %s%s%s\n' "$mark" "$C_D" "$STEP" "$TOTAL" "$C_0" "$C_B" "$STEP_TITLE" "$C_0" \
    "$C_D" "$(fmt_secs "$took")" "$C_0"
  if [ -s "$STEP_LOG" ]; then
    if [ "$status" = ok ]; then cat "$STEP_LOG"; else tail -n 25 "$STEP_LOG"; fi
  fi
  rm -f "$STEP_LOG"
}

run_step() { # run_step "Title" function - runs in this shell (variables it sets are kept)
  step_begin "$1"
  "$2"
  step_end ok
}

on_exit() {
  local rc=$? keep=""
  if [ "$IN_STEP" = 1 ]; then
    step_end fail
    printf '\n  %sThe installation stopped.%s Fix the problem above, then run the same command again:\n' "$C_R$C_B" "$C_0"
    printf '  %severy step keeps what is already done.%s\n\n' "$C_D" "$C_0"
  fi
  # background downloads of this run die with it
  local j; for j in $(jobs -p 2>/dev/null); do kill "$j" 2>/dev/null || true; done
  if [ "$rc" != 0 ] && [ -d "$WORK" ] && ls "$WORK"/*.log >/dev/null 2>&1 && [ -d "$STATE_DIR" ]; then
    keep="$STATE_DIR/logs/install-failed-$(date +%Y%m%d-%H%M%S)"
    mkdir -p -m 700 "$STATE_DIR/logs" && mkdir -m 700 "$keep" && cp "$WORK"/*.log "$keep/" 2>/dev/null \
      && printf '  %slogs of this run: %s%s\n' "$C_D" "$keep" "$C_0"
  fi
  case "${WORK0:-}" in */harness-install.?*) rm -rf "$WORK0" ;; esac
  exit "$rc"
}
trap on_exit EXIT

# ---- questions (answers come from the terminal even when the script is piped) ---------------
has_tty() { [ "$ASSUME_YES" != 1 ] && (: </dev/tty) 2>/dev/null; }

# ask VAR "question" [default] - keeps a VAR that is already set
ask() {
  local __v=$1 __q=$2 __d=${3:-} __a=""
  [ -n "${!__v:-}" ] && return 0
  if ! has_tty; then printf -v "$__v" '%s' "$__d"; return 0; fi
  read -rp "    $C_A?$C_0 $__q${__d:+ ${C_D}[$__d]$C_0}: " __a </dev/tty || true
  printf -v "$__v" '%s' "${__a:-$__d}"
}

ask_secret() {
  local __v=$1 __q=$2 __a=""
  [ -n "${!__v:-}" ] && return 0
  has_tty || return 0
  read -rsp "    $C_A?$C_0 $__q: " __a </dev/tty || true
  echo
  printf -v "$__v" '%s' "$__a"
}

# ask_yn "question" default(y|n) -> 0 = yes
ask_yn() {
  local __a="" __d=${2:-n}
  if ! has_tty; then [ "$__d" = y ]; return; fi
  read -rp "    $C_A?$C_0 $1 ${C_D}[$( [ "$__d" = y ] && echo Y/n || echo y/N )]$C_0: " __a </dev/tty || true
  __a=${__a:-$__d}
  case "$__a" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ---- helpers --------------------------------------------------------------------------------
venv_py() { echo "$INSTALL_DIR/server/.venv/bin/python"; }

# cfg_get KEY - value from an existing config.json ("" when absent)
cfg_get() {
  local py
  py=$(venv_py)
  [ -x "$py" ] || py=$(command -v python3 || true)
  [ -n "$py" ] && [ -f "$STATE_DIR/config.json" ] || { echo ""; return 0; }
  "$py" -I - "$STATE_DIR/config.json" "$1" <<'PY' 2>/dev/null || echo ""
import json, sys
v = json.load(open(sys.argv[1])).get(sys.argv[2], "")
print("" if v is None else v)
PY
}

# git_tok ARGS... - git with the read token in its environment (GIT_CONFIG_*), never in its command line: the
# arguments of every process are visible to every user (ps), its environment only to root
git_tok() {
  if [ -n "$GH_TOKEN" ]; then
    GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.extraHeader \
      GIT_CONFIG_VALUE_0="Authorization: Basic $(printf 'x-access-token:%s' "$GH_TOKEN" | base64 | tr -d '\n')" git "$@"
  else
    git "$@"
  fi
}

# apt_get ARGS... - apt with the usual umask (package scripts create files other users must read)
apt_get() { (umask 022; DEBIAN_FRONTEND=noninteractive apt-get "$@"); }

# reset_env - a root shell of its own: HOME and PATH of root, whatever the caller had (sudo -E, su without -)
reset_env() {
  HOME=$(getent passwd root 2>/dev/null | cut -d: -f6)
  HOME=${HOME:-/root}
  export HOME
  export PATH="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
}

# ver_lt A B - version A is older than B (2.0.0a9 < 2.0.0a10 < 2.0.0); an unparsable A counts as older
ver_lt() {
  python3 -I - "$1" "$2" <<'PY'
import re, sys
def key(v):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-.]?(a|alpha|b|beta|rc)\.?(\d+))?$", v.strip())
    if not m:
        return None
    pre = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2}.get(m.group(4) or "", 3)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), pre, int(m.group(5) or 0))
a, b = key(sys.argv[1]), key(sys.argv[2])
sys.exit(0 if a is None or (b is not None and a < b) else 1)
PY
}

# url_ok URL - https://, or plain http to this machine only (tests)
url_ok() {
  case "$1" in
    https://*) return 0 ;;
    http://127.0.0.1:*|http://127.0.0.1/*|http://localhost:*|http://localhost/*) return 0 ;;
    *) return 1 ;;
  esac
}

# ---- the dependency manifest (server/maxxing/deps.toml) --------------------------------------
deps_toml() { echo "$INSTALL_DIR/server/maxxing/deps.toml"; }
# dep NAME KEY [SUBKEY] - a value of deps.toml (only the subset it uses: [name], key = "s", key = ["a"], key = { k = "v" })
dep() {
  [ -f "$(deps_toml)" ] || return 1
  python3 -I - "$(deps_toml)" "$@" <<'PY'
import re, sys
path, name, key = sys.argv[1:4]
sub = sys.argv[4] if len(sys.argv) > 4 else None
sec = None
for ln in open(path, encoding="utf-8"):
    ln = ln.strip()
    if not ln or ln.startswith("#"):
        continue
    m = re.fullmatch(r"\[([A-Za-z0-9_-]+)\]", ln)
    if m:
        sec = m.group(1)
        continue
    m = re.fullmatch(r"([A-Za-z0-9_]+)\s*=\s*(.+)", ln)
    if sec != name or not m or m.group(1) != key:
        continue
    v = m.group(2)
    if v.startswith('"'):
        print(re.match(r'"([^"\\]*)"', v).group(1))
    elif v.startswith("["):
        print("\n".join(re.findall(r'"([^"\\]*)"', v)))
    elif v.startswith("{"):
        d = dict(re.findall(r'([A-Za-z0-9_]+)\s*=\s*"([^"\\]*)"', v))
        if sub is None:
            print("\n".join(k + "=" + x for k, x in d.items()))
        elif sub in d:
            print(d[sub])
        else:
            sys.exit(1)
    sys.exit(0)
sys.exit(1)
PY
}
machine() { case "$(uname -m)" in x86_64|amd64) echo x86_64 ;; aarch64|arm64) echo aarch64 ;; *) uname -m ;; esac; }
# dep_url NAME - the download URL of a component for this machine
dep_url() {
  local v a u
  v=$(dep "$1" version) && a=$(dep "$1" arch "$(machine)") && u=$(dep "$1" url) || return 1
  u=${u//\{version\}/$v}; printf '%s' "${u//\{arch\}/$a}"
}
# fetch_verified URL SHA256 DEST - THE way this installer downloads code: HTTPS only (plain http only to this
# machine, for tests), into DEST (inside $WORK), sha256 checked before the file is used; a mismatch deletes it
fetch_verified() {
  local url=$1 sum=$2 dest=$3 proto='=https'
  case "$url" in https://*) ;; *) url_ok "$url" || { warn "refused: $url is not HTTPS"; return 1; }; proto='=https,http' ;; esac
  printf '%s' "$sum" | grep -Eq '^[0-9a-f]{64}$' || { warn "no valid sha256 pinned for $url"; return 1; }
  if [ -f "$dest" ] && [ "$(sha256sum "$dest" | cut -d' ' -f1)" = "$sum" ]; then return 0; fi
  rm -f "$dest.part"
  curl -fsSL --proto "$proto" --retry 3 --connect-timeout 20 -o "$dest.part" "$url" || { rm -f "$dest.part"; warn "download failed: $url"; return 1; }
  if [ "$(sha256sum "$dest.part" | cut -d' ' -f1)" != "$sum" ]; then
    rm -f "$dest.part"; warn "checksum mismatch: $url (expected sha256 $sum)"; return 1
  fi
  mv -f "$dest.part" "$dest"
}
# dep_fetch NAME DEST - fetch_verified with the URL and the sha256 of deps.toml for this machine
dep_fetch() {
  local url sum
  url=$(dep_url "$1") && sum=$(dep "$1" sha256 "$(machine)") || { warn "$1: no build pinned for $(machine) in deps.toml"; return 1; }
  fetch_verified "$url" "$sum" "$2"
}

# ---- input checks (every value below ends up in files, units and commands run as root) --------
safe_path() { # safe_path NAME VALUE - absolute, no whitespace, quotes, %, $, backslash, backtick or ..
  case "$2" in
    /*) ;;
    *) die "$1 must be an absolute path (got '$2')" ;;
  esac
  case "$2" in
    *[[:space:]]*|*\"*|*\'*|*%*|*\$*|*\\*|*\`*|*/../*|*/..) die "$1 contains a character that is not allowed: '$2'" ;;
  esac
}
check_inputs() {
  safe_path INSTALL_DIR "$INSTALL_DIR"; safe_path WORKSPACE "$WORKSPACE"; safe_path STATE_DIR "$STATE_DIR"
  [ -z "$CLAUDE_DIR" ] || safe_path CLAUDE_DIR "$CLAUDE_DIR"
  case "$PORT" in ''|*[!0-9]*) die "PORT must be a number" ;; esac
  [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "PORT must be between 1 and 65535"
  case "$BRANCH" in -*|*..*|*//*|/*|*/) die "BRANCH is not a valid branch name (got '$BRANCH')" ;; esac
  printf '%s' "$BRANCH" | grep -Eq '^[A-Za-z0-9._/-]+$' || die "BRANCH may only contain letters, digits, . _ / - (got '$BRANCH')"
  printf '%s' "$REPO" | grep -Eq '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$' || die "REPO must be owner/name (got '$REPO')"
  if [ -n "$RESTORE_FROM" ] && ! printf '%s' "$RESTORE_FROM" | grep -Eq '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$'; then
    die "RESTORE_FROM must be owner/name (got '$RESTORE_FROM')"
  fi
  url_ok "$LICENSE_API" || die "LICENSE_API must be an https:// address (got '$LICENSE_API')"
  case "$RESTORE_TRUST" in 0|1) ;; *) die "RESTORE_TRUST must be 0 or 1" ;; esac
  case "$ALLOW_UNPROTECTED" in 0|1) ;; *) die "ALLOW_UNPROTECTED must be 0 or 1" ;; esac
  case "$FIREWALL" in auto|add|0|1) ;; *) die "FIREWALL must be auto, 1 or 0" ;; esac
  case "$SSH_HARDEN" in auto|0|1) ;; *) die "SSH_HARDEN must be auto, 1 or 0" ;; esac
  case "$TOOLS" in background|foreground|0) ;; *) die "TOOLS must be background, foreground or 0" ;; esac
  case "$SWAP" in auto|0|1) ;; *) die "SWAP must be auto, 1 or 0" ;; esac
  [ -z "$SOURCE_DIR" ] || safe_path SOURCE_DIR "$SOURCE_DIR"
  [ -z "$TIMEZONE" ] || valid_tz_name "$TIMEZONE" || die "TIMEZONE is not a time zone name (got '$TIMEZONE')"
}
valid_tz_name() { case "$1" in ""|/*|*..*) return 1 ;; esac; printf '%s' "$1" | grep -Eq '^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$'; }
valid_domain() { [ ${#1} -le 253 ] && printf '%s' "$1" | grep -Eq '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$'; }
valid_tz() {
  case "$1" in UTC|Etc/UTC) return 0 ;; esac
  valid_tz_name "$1" && [ -f "/usr/share/zoneinfo/$1" ]
}

mx() { MAXXING_STATE="$STATE_DIR" "$BIN" "$@"; }

usage() {
  cat <<'USAGE'
Harness Maxxing installer
  curl -fsSL https://get.harness-maxxing.com | bash        install or repair from the public git repository (re-runnable)
  ... | LICENSE=HM-XXXX-XXXX-XXXX-XXXX bash                 the same, recording an Enterprise key (companies only)
  GH_TOKEN=<token> REPO=owner/name bash install.sh         from a private fork or mirror
  bash /opt/claude-maxxing/install.sh --update              update (= maxxing update)
  bash /opt/claude-maxxing/install.sh --uninstall [--purge] [--purge-workspace]
  bash /opt/claude-maxxing/install.sh --tools               (re)install Node.js, Chromium, Remotion, Scrapling (= maxxing deps update)
  bash ./install.sh                                          from an unpacked copy of the code (or SOURCE_DIR=DIR)
  bash /opt/claude-maxxing/install.sh --secure              security updates, SSH by key, fail2ban, firewall (FIREWALL=0, SSH_HARDEN=0)
  curl -fsSL https://get.harness-maxxing.com | bash -s -- --check   look at this server first, change nothing
Variables: LICENSE LICENSE_API REPO BRANCH GH_TOKEN INSTALL_DIR WORKSPACE STATE_DIR PORT ACCESS(domain|tailscale|local)
           FIREWALL(auto|1|0) SSH_HARDEN(auto|1|0) SYSTEM_CLOCK(auto|follow|keep) DOMAIN TIMEZONE ASSUME_YES=1 RESTORE_FROM RESTORE_TOKEN
           CLAUDE_TOKEN ANTHROPIC_API_KEY CLAUDE_DIR (own Claude Code folder, default ~/.claude) VOICE TOOLS SWAP SOURCE_DIR
USAGE
}

# ---- checks ---------------------------------------------------------------------------------
check_system() {
  section "Server"
  [ "$(id -u)" = 0 ] || die "Run as root (sudo -i, then the command again)."
  command -v apt-get >/dev/null 2>&1 || die "Ubuntu or Debian required (apt-get not found)."
  if [ -r /etc/os-release ]; then
    local ids pretty
    # shellcheck disable=SC1091
    ids=$(. /etc/os-release && echo " ${ID:-} ${ID_LIKE:-} ")
    # shellcheck disable=SC1091
    pretty=$(. /etc/os-release && echo "${PRETTY_NAME:-${ID:-unknown}}")
    case "$ids" in
      *" debian "*|*" ubuntu "*) ok "$pretty" ;;
      *) warn "untested distribution ($pretty) - continuing because apt is present" ;;
    esac
  fi
  [ -d /run/systemd/system ] || die "systemd must be running (sessions and the service are systemd units)."
  case "$(uname -m)" in
    x86_64|amd64|aarch64|arm64) ok "architecture $(uname -m), systemd running" ;;
    *) die "unsupported architecture $(uname -m) (x86_64 or arm64 required)" ;;
  esac
  check_inputs
}

# ---- pre-flight check: is this server already in use? ----------------------------------------
# Nothing is changed here: detect_server fills the variables above, preflight prints them and says
# what the installer will do differently. `install.sh --check` stops after it.
manifest() { # remember what the installer changed on this server (read by maxxing uninstall)
  mkdir -p "$STATE_DIR"
  grep -qxF "$1" "$STATE_DIR/install-manifest" 2>/dev/null || echo "$1" >> "$STATE_DIR/install-manifest"
}
our_unit_active() { systemctl is-active -q "$SERVICE" 2>/dev/null; }

listeners() { # "addr port process" for every listening TCP socket
  command -v ss >/dev/null 2>&1 || return 0
  ss -ltnpH 2>/dev/null | awk '{
    a=$4; p=a; sub(/.*:/, "", p); sub(/:[0-9]+$/, "", a); gsub(/[\[\]]/, "", a)
    n="?"; if (match($0, /users:\(\("[^"]+"/)) { n=substr($0, RSTART+9, RLENGTH-10) }
    print a, p, n }'
}

detect_server() {
  local addr port name ssh_p seen=" "
  ssh_p=" $(ssh_ports | tr '\n' ' ') "
  while read -r addr port name; do
    [ -n "$port" ] || continue
    case "$addr" in 127.*|::1|localhost|100.*|fd7a:115c:a1e0:*) continue ;; esac   # loopback, Tailscale
    [ "$name" = tailscaled ] && continue
    case "$ssh_p" in *" $port "*) continue ;; esac
    case "$port:$name" in 53:systemd-resolve|5355:systemd-resolve) continue ;; esac   # DNS stub, LLMNR (Debian)
    if [ "$port" = "$PORT" ] && our_unit_active; then continue; fi
    case "$port" in
      80|443) case "$name" in caddy) [ -f "$CADDY_SITE" ] && continue ;; *) WEB_BUSY=${WEB_BUSY:-$name} ;; esac ;;
    esac
    case "$seen" in *" $port "*) continue ;; esac
    seen="$seen$port "
    if [ "$name" = "?" ]; then PUBLIC_OTHER="${PUBLIC_OTHER:+$PUBLIC_OTHER }$port"
    else PUBLIC_OTHER="${PUBLIC_OTHER:+$PUBLIC_OTHER }$port/$name"; fi
  done < <(listeners)
  # a Caddy that is not ours on 80/443 is fine: our site is added with an import line
  case "$WEB_BUSY" in caddy) WEB_BUSY="" ;; "?") WEB_BUSY="another web server" ;; esac

  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
    FW_ACTIVE=ufw
  elif command -v nft >/dev/null 2>&1 && [ "$(nft list ruleset 2>/dev/null | grep -c 'chain ')" -gt 0 ]; then
    FW_ACTIVE=nftables
  fi
  if command -v docker >/dev/null 2>&1 || systemctl is-active -q docker 2>/dev/null; then HAS_DOCKER=1; fi

  if crontab -l 2>/dev/null | sed "/^# >>> claude-maxxing/,/^# <<< claude-maxxing/d" \
       | grep -vE '^[[:space:]]*(#|$|[A-Za-z_]+=)' | grep . >/dev/null; then OTHER_CRON=1; fi

  local nv np
  np=$(command -v node 2>/dev/null || true)
  if [ -n "$np" ]; then
    nv=$(node --version 2>/dev/null | sed 's/^v//; s/\..*//')
    if [ -n "$nv" ] && [ "$nv" -lt 20 ] 2>/dev/null; then NODE_OLD="$np (v$nv)"; fi
  fi

  local pat='telegram|hermes|openclaw|claudegram|ccbot'
  BRIDGES=$( { systemctl list-units --type=service --all --no-legend --plain 2>/dev/null | awk '{print $1}' | sed 's/\.service$//';
               ps -eo args= 2>/dev/null | awk '{for (i = 1; i <= 2 && i <= NF; i++) { n = $i; sub(/.*\//, "", n); print n }}'; } \
             | grep -iE "$pat" | grep -vE "^($SERVICE|maxxing-)" | sort -u | head -n 5 | tr '\n' ' ' | sed 's/ $//' || true)

  local sk=0
  [ -d "$HOME/.claude/skills" ] && sk=$(ls -A "$HOME/.claude/skills/" 2>/dev/null | wc -l)
  local parts=()
  [ -f "$HOME/.claude/.credentials.json" ] && parts+=("signed in")
  [ "$sk" -gt 0 ] && parts+=("$sk skill(s)")
  [ -f "$HOME/.claude/CLAUDE.md" ] && parts+=("~/.claude/CLAUDE.md")
  local conv=0
  [ -d "$HOME/.claude/projects" ] && conv=$(ls -A "$HOME/.claude/projects/" 2>/dev/null | wc -l)
  [ "$conv" -gt 0 ] && parts+=("conversations in $conv folder(s)")
  [ ${#parts[@]} -gt 0 ] && CLAUDE_SETUP=$(IFS=,; echo "${parts[*]}" | sed 's/,/, /g')
  [ -f "$STATE_DIR/config.json" ] && CLAUDE_SETUP=""   # a re-run: that setup is Harness Maxxing's own (its skills)
  [ -f "$STATE_DIR/config.json" ] && PRIOR=1

  if [ -n "$PUBLIC_OTHER$WEB_BUSY$BRIDGES" ] || [ "$HAS_DOCKER" = 1 ] || [ "$OTHER_CRON" = 1 ] \
     || [ -n "$FW_ACTIVE" ] || [ -n "$CLAUDE_SETUP" ]; then EXISTING=1; fi

  # port of the web server: another program already on it -> the next free one
  if [ ! -d "$INSTALL_DIR/.git" ] && ! our_unit_active; then
    local p=$PORT
    while listeners | awk -v p="$p" '$2==p {f=1} END {exit !f}'; do p=$((p + 1)); done
    PORT_MOVED_FROM=""
    [ "$p" = "$PORT" ] || { PORT_MOVED_FROM=$PORT; PORT=$p; }
  fi

  if [ "$SYSTEM_CLOCK" = auto ]; then
    SYSTEM_CLOCK=$(cfg_get system_clock)
    [ -n "$SYSTEM_CLOCK" ] || { [ "$EXISTING" = 1 ] && SYSTEM_CLOCK=keep || SYSTEM_CLOCK=follow; }
  fi
  if [ "$FIREWALL" = auto ]; then
    if [ -n "$FW_ACTIVE" ]; then FIREWALL=add                 # keep theirs, only add our rules
    elif [ -n "$PUBLIC_OTHER" ] || [ "$HAS_DOCKER" = 1 ]; then FIREWALL=0
    else FIREWALL=1; fi
  fi
}

preflight() {
  section "Server check"
  local free_gb mem_gb
  free_gb=$(df -Pk / 2>/dev/null | awk 'NR==2{printf "%d", $4/1048576}')
  mem_gb=$(awk '/MemTotal/{printf "%.1f", $2/1048576}' /proc/meminfo 2>/dev/null)
  if [ "${free_gb:-0}" -lt 5 ]; then warn "only ${free_gb} GB free on / - about 4 GB are needed (tools, voice model)"
  else ok "${free_gb} GB free, ${mem_gb} GB of memory"; fi
  local sp
  sp=$(ssh_plan)
  case "$sp" in
    done)  ok "SSH: logins by key only" ;;
    apply) ok "SSH: this session uses a key - password logins will be turned off (open sessions stay connected; SSH_HARDEN=0 keeps them)" ;;
    *)     info "SSH: ${sp#skip:}" ;;
  esac
  if [ "$EXISTING" = 0 ]; then
    ok "fresh server: nothing else runs here"
    return 0
  fi
  info "this server is already in use - the installer adapts:"
  if [ -n "$PUBLIC_OTHER" ]; then
    warn "other services reachable from outside: $PUBLIC_OTHER"
  fi
  case "$FIREWALL:$FW_ACTIVE" in
    add:ufw) ok "firewall: your ufw rules are kept - only the ports Harness Maxxing needs are added" ;;
    add:*)   ok "firewall: your $FW_ACTIVE rules are left as they are (open 80/443 yourself for a domain)" ;;
    0:*)     warn "firewall: not enabled, it could cut these services off (to force it: FIREWALL=1 install.sh --secure)" ;;
  esac
  [ "$HAS_DOCKER" = 1 ] && info "Docker found: its published ports bypass ufw - the firewall is left alone"
  if [ -n "$WEB_BUSY" ]; then
    warn "$WEB_BUSY already serves ports 80/443: Caddy is not installed; with a domain you get a ready-made"
    warn "reverse-proxy block to paste into $WEB_BUSY (or pick tailscale / local)"
  fi
  [ -n "${PORT_MOVED_FROM:-}" ] && warn "port $PORT_MOVED_FROM is taken by another program: Harness Maxxing uses $PORT"
  if [ "$SYSTEM_CLOCK" = keep ]; then
    ok "server clock: left as it is ($(system_tz)) - your jobs still run at the times you choose"
  fi
  [ -n "$NODE_OLD" ] && ok "Node.js: your $NODE_OLD is kept, the pinned one goes to $STATE_DIR/tools/nodejs for Harness Maxxing only"
  if [ -n "$CLAUDE_DIR" ]; then
    ok "Claude Code folder for Harness Maxxing: $CLAUDE_DIR (your ~/.claude is not used nor touched)"
  elif [ -n "$CLAUDE_SETUP" ]; then
    ok "Claude Code already used on this server ($CLAUDE_SETUP): kept as it is"
    if [ -f "$STATE_DIR/config.json" ]; then
      info "Harness Maxxing already shares it - its setting is kept"
    else
      info "next question: give Harness Maxxing its own Claude Code folder, or share this one"
    fi
  fi
  if [ -n "$BRIDGES" ]; then
    warn "other Telegram bridge / agent running: $BRIDGES"
    warn "give Harness Maxxing a NEW bot (BotFather): one bot token can only be read by one program"
  fi
  [ "$OTHER_CRON" = 1 ] && ok "your crontab lines are kept (Harness Maxxing only edits its own block)"
  info "nothing else is touched: your files, services and settings stay as they are"
}

# ---- choices (asked up front, then everything runs unattended) ------------------------------
# Claude Code folder. Asked only when Claude Code is already used on this server (sign-in, skills, CLAUDE.md or
# conversations in ~/.claude) and Harness Maxxing is not installed yet: its own folder (default) keeps that setup
# untouched; sharing makes the existing skills and global instructions apply to Harness Maxxing sessions.
# An existing installation keeps its setting (switching would lose its sign-in and its conversations).
CLAUDE_DIR_DEFAULT_NAME=".claude-harness"
choose_claude_dir() {
  [ -n "$CLAUDE_DIR" ] && return 0
  if [ -f "$STATE_DIR/config.json" ]; then
    CLAUDE_DIR=$(cfg_get claude_dir)
    return 0
  fi
  [ -n "$CLAUDE_SETUP" ] || return 0
  local own="$HOME/$CLAUDE_DIR_DEFAULT_NAME" n=1
  if has_tty; then
    echo "      Claude Code is already used on this server ($CLAUDE_SETUP)."
    printf '        %s1%s  %sown folder%s  %s - your ~/.claude is not touched %s(recommended)%s\n' "$C_A$C_B" "$C_0" "$C_B" "$C_0" "$own" "$C_G" "$C_0"
    printf '        %s2%s  %sshare%s       ~/.claude - your skills, CLAUDE.md and sign-in also apply to Harness Maxxing\n' "$C_A$C_B" "$C_0" "$C_B" "$C_0"
    ask CDIR "Choice (1/2)" "$n"
    case "${CDIR:-$n}" in 2|share|shared) CLAUDE_DIR="" ;; *) CLAUDE_DIR=$own ;; esac
  else
    CLAUDE_DIR=$own
  fi
  if [ -n "$CLAUDE_DIR" ]; then
    ok "Claude Code folder for Harness Maxxing: $CLAUDE_DIR (sign in again in the web setup; bring skills over later)"
  else
    ok "Claude Code folder shared with your existing setup (~/.claude)"
  fi
}

# choose_source - where the code comes from: an existing install keeps its source; a new one uses a local copy
# (SOURCE_DIR / the folder of this script), otherwise the public git repository (no token: updates come from git).
# An install still on signed archives (before 2.0.0a87) keeps them until it moves to git by itself.
choose_source() {
  if [ -d "$INSTALL_DIR/.git" ]; then
    if [ -f "$STATE_DIR/secrets.json" ] && grep -q '"license_token"' "$STATE_DIR/secrets.json" 2>/dev/null; then LICENSED=1
    elif [ -n "$SOURCE_DIR" ] || ! git -C "$INSTALL_DIR" remote get-url origin >/dev/null 2>&1; then LOCAL=1; fi
  elif [ -z "$GH_TOKEN" ] && local_source; then
    LOCAL=1
    ok "code: the local copy in $SOURCE_DIR (no download - updates: a newer copy, then this again)"
  else
    ok "code: the git repository github.com/$REPO ($BRANCH) - updates come from git"
  fi
}

choose_access() {
  section "Setup"
  local cur_url cur_bind def=local
  cur_url=$(cfg_get public_url)
  cur_bind=$(cfg_get bind)
  if [ -z "$ACCESS" ]; then
    case "$cur_url" in
      https://*) def=domain; [ -n "$DOMAIN" ] || DOMAIN=$(printf '%s' "$cur_url" | sed -E 's#^https://([^/:]+).*#\1#') ;;
      *) case "$cur_bind" in
           100.*) def=tailscale ;;
           *) if [ -z "$cur_url$cur_bind" ] && has_tty; then def=domain; fi ;;
         esac ;;
    esac
    if has_tty; then
      echo "      How will you reach the web UI?"
      if [ -n "$WEB_BUSY" ]; then
        printf '        %s1%s  %sdomain%s     https://ui.example.com - through your %s (block to paste)\n' "$C_A$C_B" "$C_0" "$C_B" "$C_0" "$WEB_BUSY"
      else
        printf '        %s1%s  %sdomain%s     https://ui.example.com - automatic HTTPS %s(recommended)%s\n' "$C_A$C_B" "$C_0" "$C_B" "$C_0" "$C_G" "$C_0"
      fi
      printf '        %s2%s  %stailscale%s  http://<tailscale-ip>:%s - your Tailscale devices only\n' "$C_A$C_B" "$C_0" "$C_B" "$C_0" "$PORT"
      printf '        %s3%s  %slocal%s      127.0.0.1 only - through an SSH tunnel\n' "$C_A$C_B" "$C_0" "$C_B" "$C_0"
      local n
      case "$def" in domain) n=1 ;; tailscale) n=2 ;; *) n=3 ;; esac
      ask ACC "Choice (1/2/3)" "$n"
      case "${ACC:-$n}" in 1|domain) ACCESS=domain ;; 2|tailscale) ACCESS=tailscale ;; *) ACCESS=local ;; esac
    else
      ACCESS=$def
    fi
  fi
  case "$ACCESS" in
    domain)
      ask DOMAIN "Domain name (its DNS A/AAAA record must point to this server)" ""
      DOMAIN=$(printf '%s' "$DOMAIN" | sed -E 's#^https?://##; s#/.*$##' | tr '[:upper:]' '[:lower:]')
      [ -n "$DOMAIN" ] || die "ACCESS=domain needs DOMAIN=ui.example.com"
      valid_domain "$DOMAIN" || die "'$DOMAIN' is not a valid domain name (e.g. ui.example.com)"
      PUBLIC_URL="https://$DOMAIN"; BIND=127.0.0.1 ;;
    tailscale)
      command -v tailscale >/dev/null 2>&1 || die "Tailscale is not installed: install it (https://tailscale.com/download/linux), run tailscale up, then this again"
      BIND=$(tailscale ip -4 2>/dev/null | head -n1 || true)
      [ -n "$BIND" ] || die "Tailscale is not connected (run: tailscale up)."
      PUBLIC_URL="http://$BIND:$PORT"; AFTER=" tailscaled.service" ;;
    local)
      PUBLIC_URL=""; BIND=127.0.0.1 ;;
    *) die "ACCESS must be domain, tailscale or local" ;;
  esac
  ok "access: $ACCESS${PUBLIC_URL:+ ($PUBLIC_URL)}, server bound to $BIND:$PORT"

  if [ -z "$RESTORE_FROM" ] && [ ! -f "$WORKSPACE/memory.md" ] && has_tty; then
    if ask_yn "Restore your memory from an existing Harness Maxxing GitHub backup?" n; then
      ask RESTORE_FROM "Backup repository (owner/name)" ""
    fi
  fi
  if [ -n "$RESTORE_FROM" ]; then
    ask_secret RESTORE_TOKEN "GitHub token with read access to $RESTORE_FROM"
    [ -n "$RESTORE_TOKEN" ] || die "RESTORE_FROM needs RESTORE_TOKEN"
    ok "restore from $RESTORE_FROM after the installation"
  fi

  choose_claude_dir
  if [ "$SSH_HARDEN" = auto ] && has_tty && [ "$(ssh_plan)" = apply ]; then
    ask_yn "You are connected with an SSH key: turn SSH password logins off (open sessions stay connected)?" y || SSH_HARDEN=0
  fi

  case "$VOICE" in ""|off|local|groq|openai) ;; *) die "VOICE must be local, groq, openai or off" ;; esac
  voice_memory_check
  [ "$VOICE" = off ] || ok "voice messages: $VOICE (change it later in Settings -> Voice)"

  choose_source
  [ "$ACCESS" = domain ] && dns_check

  SYS_TZ=$(system_tz)
  [ -n "$TIMEZONE" ] || TIMEZONE=$(cfg_get timezone)
  [ -n "$TIMEZONE" ] || TIMEZONE=$SYS_TZ                 # chosen in the web onboarding
  if [ ! -d /usr/share/zoneinfo ] || [ ! -e /usr/share/zoneinfo/UTC ]; then   # minimal images ship without tzdata
    apt_get update -qq >/dev/null 2>&1; apt_get install -y -qq tzdata >/dev/null 2>&1 || true
  fi
  valid_tz "$TIMEZONE" || die "unknown time zone '$TIMEZONE' (see: timedatectl list-timezones)"
  if [ "$TIMEZONE" != "$SYS_TZ" ] && [ "$SYSTEM_CLOCK" = keep ]; then
    ok "time zone: $TIMEZONE (the server clock stays at $SYS_TZ, jobs follow your zone)"
  elif [ "$TIMEZONE" != "$SYS_TZ" ]; then
    ok "time zone: $TIMEZONE (the server clock is switched from $SYS_TZ so jobs fire at the times you see)"
  else
    ok "time zone: $TIMEZONE for now - you pick yours in the web onboarding"
  fi
}

# local_source - a source tree to install: SOURCE_DIR, or the folder this script was run from (not the install itself)
local_source() {
  if [ -n "$SOURCE_DIR" ]; then return 0; fi
  [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/server/maxxing/__init__.py" ] && [ -f "$SELF_DIR/install.sh" ] || return 1
  [ "$SELF_DIR" != "$(cd "$INSTALL_DIR" 2>/dev/null && pwd -P)" ] || return 1
  safe_path SOURCE_DIR "$SELF_DIR"
  SOURCE_DIR=$SELF_DIR
}

mem_mb() { awk '/MemTotal/{print int($2/1024)}' "$MEMINFO" 2>/dev/null || echo 0; }
swap_kb() { awk '/SwapTotal/{print $2}' "$MEMINFO" 2>/dev/null || echo 0; }
VOICE_MIN_MB=2800      # a "3 GB" server reports a bit less; local Whisper + a browser + Claude turns need that much
# voice_memory_check - local Whisper on a small server: off by default, refused unless confirmed
voice_memory_check() {
  [ "$VOICE" = local ] || return 0
  [ -f "$STATE_DIR/voice/extra-installed" ] && return 0                # chosen before on this server: kept
  local m
  m=$(mem_mb)
  [ "${m:-0}" -ge "$VOICE_MIN_MB" ] && return 0
  if [ -z "$VOICE_GIVEN" ]; then
    VOICE=off
    info "voice messages: off - local Whisper needs about 3 GB of memory, this server has ${m} MB (Settings -> Voice: Groq or OpenAI)"
    return 0
  fi
  if has_tty; then
    ask_yn "Local voice (Whisper) needs about 3 GB of memory and this server has ${m} MB - use it anyway?" n && return 0
    VOICE=off; info "voice messages: off (Settings -> Voice: Groq or OpenAI)"; return 0
  fi
  die "VOICE=local needs about 3 GB of memory (this server: ${m} MB) - set VOICE=off, groq or openai, or run in a terminal to confirm"
}

# system_tz - the zone the cron daemon uses
system_tz() {
  local z=""
  z=$(timedatectl show -p Timezone --value 2>/dev/null || true)
  [ -n "$z" ] || z=$(cat /etc/timezone 2>/dev/null || true)
  [ -n "$z" ] || z=$(readlink /etc/localtime 2>/dev/null | sed 's#.*/zoneinfo/##' || true)
  echo "${z:-UTC}"
}

# align_tz - cron fires in the system zone: make it equal to the configured one
align_tz() {
  local cur
  cur=$(system_tz)
  [ "$TIMEZONE" = "$cur" ] && return 0
  [ "$SYSTEM_CLOCK" = keep ] && return 0
  if timedatectl set-timezone "$TIMEZONE" 2>/dev/null; then
    systemctl restart cron >/dev/null 2>&1 || true
    manifest "timezone $cur"
    ok "system time zone set to $TIMEZONE (was $cur), cron restarted"
  else
    warn "could not set the system time zone - run: timedatectl set-timezone $TIMEZONE && systemctl restart cron"
  fi
}

# ---- packages -------------------------------------------------------------------------------
# One apt pass: everything this installer and the tools need, checked first (nothing to do on a re-run when all of
# it is there). Each "a:b" entry takes the first name this release knows (Ubuntu 24.04 renamed libraries to *t64).
BASE_PKGS="git curl ca-certificates cron openssl python3 gnupg openssh-client xz-utils tzdata"
TOOL_PKGS="ffmpeg zip unzip jq ripgrep imagemagick poppler-utils"
SEC_PKGS="unattended-upgrades fail2ban python3-systemd"
BROWSER_PKGS="libnss3 libnspr4 libdbus-1-3 libatk1.0-0t64:libatk1.0-0 libatk-bridge2.0-0t64:libatk-bridge2.0-0 libgbm1
  libasound2t64:libasound2 libxrandr2 libxkbcommon0 libxfixes3 libxcomposite1 libxdamage1 libdrm2 libpango-1.0-0
  libcairo2 libcups2t64:libcups2 libatspi2.0-0t64:libatspi2.0-0 fonts-liberation fonts-noto-color-emoji"
pkg_installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'; }
pkg_known() { apt-cache show -q=0 "$1" >/dev/null 2>&1; }

# ubuntu_universe - ffmpeg, jq, ripgrep, fail2ban... are in Ubuntu's universe component: turned on when an image
# shipped without it (otherwise every one of them silently fails)
ubuntu_universe() {
  # shellcheck disable=SC1091
  [ "$(. /etc/os-release 2>/dev/null && echo "${ID:-}")" = ubuntu ] || return 0
  grep -rhsE '^[[:space:]]*(deb|Components:)' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null | grep -w universe >/dev/null && return 0   # no -q: an early exit fails the pipe
  local f=/etc/apt/sources.list.d/ubuntu.sources
  if [ -f "$f" ] && grep -q '^Components:' "$f"; then
    cp -p "$f" "$WORK/ubuntu.sources.bak"
    sed -i -E '/^Components:/{/universe/!s/$/ universe/}' "$f"
    manifest "universe enabled"
    ok "Ubuntu's universe component turned on ($f)"
  elif command -v add-apt-repository >/dev/null 2>&1; then
    add-apt-repository -y universe >>"$WORK/apt.log" 2>&1 && manifest "universe enabled" && ok "Ubuntu's universe component turned on"
  else
    warn "Ubuntu's universe component is off: ffmpeg, jq, ripgrep, fail2ban may be missing (turn it on in /etc/apt/sources.list)"
  fi
}

install_packages() {
  local want=() p n missing=() opt_missing=()
  local wants_fw=0
  [ "$FIREWALL" = 1 ] && ! systemd-detect-virt -cq 2>/dev/null && wants_fw=1
  for p in $BASE_PKGS; do pkg_installed "$p" || missing+=("$p"); done
  for p in $TOOL_PKGS $SEC_PKGS $BROWSER_PKGS $([ "$wants_fw" = 1 ] && echo ufw); do
    for n in ${p//:/ }; do pkg_installed "$n" && continue 2; done
    opt_missing+=("$p")
  done
  if [ ${#missing[@]} -eq 0 ] && [ ${#opt_missing[@]} -eq 0 ]; then
    ok "system packages already installed"
  else
    ubuntu_universe
    apt_get update -qq >>"$WORK/apt.log" 2>&1 || warn "apt-get update reported errors (see below if something is missing)"
    want=("${missing[@]}")
    local skipped=()
    for p in "${opt_missing[@]}"; do
      for n in ${p//:/ }; do
        if pkg_known "$n"; then want+=("$n"); continue 2; fi
      done
      skipped+=("${p%%:*}")
    done
    apt_get install -y -qq --no-install-recommends "${want[@]}" >>"$WORK/apt.log" 2>&1 \
      || apt_get install -y -qq "${want[@]}" >>"$WORK/apt.log" 2>&1 \
      || { tail -n 15 "$WORK/apt.log"; die "apt-get install failed"; }
    [ ${#skipped[@]} -eq 0 ] || warn "not available on this system: ${skipped[*]}"
    ok "${#want[@]} package(s) installed in one pass"
  fi
  command -v ffmpeg >/dev/null 2>&1 || warn "ffmpeg not installed: no video thumbnails in Files, no voice messages"
  systemctl enable --now cron >/dev/null 2>&1 || warn "could not start the cron service"
  ensure_swap
}

# ensure_swap - a small server without swap is killed by the first big turn: 2 GB /swapfile under 4 GB of memory
ensure_swap() {
  local m sw f=/swapfile free_mb
  [ "$SWAP" = 0 ] && return 0
  m=$(mem_mb); sw=$(swap_kb)
  [ "${m:-0}" -lt 4096 ] && [ "${sw:-0}" -eq 0 ] || return 0
  if [ "$SWAP" = auto ] && { [ "$EXISTING" = 1 ] || [ "$PRIOR" = 1 ]; }; then   # a server in use: no swap may be deliberate
    info "${m} MB of memory and no swap - SWAP=1 adds a 2 GB /swapfile"; return 0
  fi
  if systemd-detect-virt -cq 2>/dev/null; then
    info "${m} MB of memory and no swap - a container gets its swap from the host"; return 0
  fi
  if [ -e "$f" ]; then warn "$f exists but is not in use - left as it is (swapon $f)"; return 0; fi
  free_mb=$(df -Pm / | awk 'NR==2{print $4}')
  [ "${free_mb:-0}" -ge 6144 ] || { warn "${m} MB of memory, no swap, and too little disk to add one"; return 0; }
  if { fallocate -l 2G "$f" 2>/dev/null || dd if=/dev/zero of="$f" bs=1M count=2048 status=none; } \
     && chmod 600 "$f" && mkswap "$f" >/dev/null 2>&1 && swapon "$f" 2>/dev/null; then
    grep -qE "^${f}[[:space:]]" /etc/fstab || (umask 022; echo "$f none swap sw 0 0" >> /etc/fstab)
    manifest "swapfile $f"
    ok "2 GB of swap added ($f) - this server has ${m} MB of memory"
  else
    rm -f "$f"; warn "could not add swap - with ${m} MB of memory, several Claude turns at once may run out of memory"
  fi
}

# ---- toolchain (pinned in deps.toml, downloaded with fetch_verified) --------------------------
UV=/usr/local/bin/uv
# prefetch - start the big downloads in the background as soon as the code (and its deps.toml) is here
prefetch() {
  CLAUDE_DL=""
  if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ]; then
    ( dep_fetch claude "$WORK/claude.bin" ) >"$WORK/claude-download.log" 2>&1 &
    CLAUDE_DL=$!
  fi
}

install_uv() {
  local want have d="$WORK/uv"
  want=$(dep uv version) || die "deps.toml not found in $INSTALL_DIR"
  have=$("$UV" --version 2>/dev/null | awk '{print $2}' || true)
  if [ "$have" = "$want" ]; then ok "uv $have"; return; fi
  if [ -n "$have" ] && ! grep -qx "uv installed" "$STATE_DIR/install-manifest" 2>/dev/null; then
    ok "uv $have (already on this server, not ours: kept)"; return    # another tool's uv is not replaced nor removed
  fi
  dep_fetch uv "$WORK/uv.tar.gz" || die "uv download failed or its sha256 does not match deps.toml"
  if ! { mkdir -p "$d" && tar -xzf "$WORK/uv.tar.gz" -C "$d" --strip-components=1 --no-same-owner \
          && install -m 755 -o root -g root "$d/uv" "$d/uvx" /usr/local/bin/; }; then die "uv installation failed"; fi
  [ -n "$have" ] || manifest "uv installed"
  ok "uv $("$UV" --version 2>/dev/null | awk '{print $2}') in /usr/local/bin (sha256 checked)"
}

# Claude Code: the pinned build of deps.toml, its sha256 checked, then its own `claude install` (what Anthropic's
# install.sh does, without running a script fetched at install time). It updates itself afterwards.
install_claude() {
  local log="$WORK/claude-install.log" v
  if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ]; then
    v=$(dep claude version)
    if [ -n "${CLAUDE_DL:-}" ]; then wait "$CLAUDE_DL" || true; fi
    if [ ! -f "$WORK/claude.bin" ]; then dep_fetch claude "$WORK/claude.bin" >>"$log" 2>&1 || true; fi
    [ -f "$WORK/claude.bin" ] || { cat "$WORK/claude-download.log" >>"$log" 2>/dev/null; claude_install_failed "$log"; }
    chmod 700 "$WORK/claude.bin"
    (cd "$WORK" && CLAUDE_INSTALL_ALLOW_SUDO=1 "$WORK/claude.bin" install "$v") >>"$log" 2>&1 || claude_install_failed "$log"
    rm -f "$WORK/claude.bin"
    manifest "claude installed"
  fi
  if [ ! -e /usr/local/bin/claude ] && [ -x "$HOME/.local/bin/claude" ]; then
    ln -s "$HOME/.local/bin/claude" /usr/local/bin/claude
  fi
  command -v claude >/dev/null 2>&1 || die "claude not found after installation"
  ok "Claude Code $(claude --version 2>/dev/null | head -n1)"
  if [ -f "${CLAUDE_DIR:-$HOME/.claude}/.credentials.json" ]; then
    info "the Claude CLI is already signed in on this server"
  fi
}

claude_install_failed() { # explain the most common causes, then stop
  local log=$1
  printf '\n'; tail -n 12 "$log" | sed 's/^/      | /'; printf '\n'
  if ! curl -fsS -o /dev/null --max-time 15 https://downloads.claude.ai/claude-code-releases/stable 2>/dev/null; then
    warn "downloads.claude.ai is not reachable from this server: check DNS / the provider's outgoing"
    warn "firewall, or the country (https://www.anthropic.com/supported-countries)."
  elif grep -qi "not available in your region\|unexpected content" "$log"; then
    warn "Claude Code is not available from this server's country (https://www.anthropic.com/supported-countries)."
  elif grep -qi "checksum" "$log"; then
    warn "the download did not match its pinned sha256 - re-run the installer."
  elif grep -qi "No space left" "$log"; then
    warn "the disk is full - free some space (df -h) and re-run the installer."
  fi
  die "Claude Code installation failed - re-run the installer once fixed"
}

# Node.js, Chromium (Playwright's, shared by Scrapling, Remotion and PDFs), Remotion, Scrapling and the voice model:
# `maxxing deps update` installs the versions of deps.toml, each checked, next to the old ones. In the background
# once the service runs (TOOLS=background), or now (TOOLS=foreground, install.sh --tools).
DEPS_LOG_NAME=deps-install.log
install_tools_now() {
  local log="$STATE_DIR/logs/$DEPS_LOG_NAME"
  if mx deps update >"$log" 2>&1; then
    ok "tools ready: $(mx deps list 2>/dev/null | awk '$2 ~ /^(node|chromium|remotion|scrapling)$/ {printf "%s %s · ", $2, $3}' | sed 's/ · $//')"
  else
    grep -E 'failed' "$log" | tail -n 5 | sed 's/^/      | /'
    warn "some tools could not be installed - re-run: maxxing deps update (log: $log)"
  fi
}
start_tools() {
  case "$TOOLS" in
    0) info "tools skipped (TOOLS=0) - install them later: maxxing deps update"; return 0 ;;
    foreground) run_step "Tools (Node.js, Chromium, Remotion, Scrapling)" install_tools_now; return 0 ;;
  esac
  local log="$STATE_DIR/logs/$DEPS_LOG_NAME"
  mkdir -p "$STATE_DIR/tmp" && chmod 700 "$STATE_DIR/tmp"
  systemctl reset-failed maxxing-deps-install >/dev/null 2>&1 || true
  if systemd-run --quiet --collect --unit maxxing-deps-install -p MemoryMax=2G -p "StandardOutput=append:$log" \
       -p "StandardError=append:$log" -E "MAXXING_STATE=$STATE_DIR" -E "HOME=$HOME" -E "PATH=$PATH" -E "TMPDIR=$STATE_DIR/tmp" \
       "$BIN" deps update --notify >/dev/null 2>&1; then
    TOOLS_BG=1
  else
    warn "could not start the background tools install - run: maxxing deps update"
  fi
}

# ---- server security ------------------------------------------------------------------------
# Automatic security updates, fail2ban for SSH, and a firewall that only lets SSH (+ 80/443 for a
# domain, + the Tailscale interface) in - so a dev server Claude starts on 0.0.0.0 is not exposed.
# The SSH ports are detected first (never lock the user out); FIREWALL=0 skips the firewall.
ssh_ports() {
  local p
  p=$( { sshd -T 2>/dev/null | awk '$1=="port"{print $2}'; ssh_connection 2>/dev/null | awk 'NF==4{print $4}'; } | sort -un)
  [ -n "$p" ] && echo "$p" || echo 22
}

# SSH by key only. Never risk locking the user out: in auto mode the drop-in is written only when the
# session running this installer is proven (sshd log "Accepted publickey ... port <its port>") to be a
# key login; the result is checked with `sshd -t` and `sshd -T`, anything unexpected removes it again.
# Existing connections are never cut (a reload only applies to new logins).
ssh_connection() { # SSH_CONNECTION of this session, also through sudo -i (read from an ancestor's environment)
  local pid=$$ c
  [ -n "${SSH_CONNECTION:-}" ] && { echo "$SSH_CONNECTION"; return 0; }
  while [ "${pid:-1}" -gt 1 ]; do
    c=$(tr '\0' '\n' <"/proc/$pid/environ" 2>/dev/null | sed -n 's/^SSH_CONNECTION=//p' | head -n1) || true
    [ -n "$c" ] && { echo "$c"; return 0; }
    pid=$(awk '{print $4}' "/proc/$pid/stat" 2>/dev/null) || true
  done
  return 1
}

ssh_session_uses_key() {
  local conn ip port
  conn=$(ssh_connection) || return 1
  ip=$(echo "$conn" | awk '{print $1}'); port=$(echo "$conn" | awk '{print $2}')
  [ -n "$ip" ] && [ -n "$port" ] || return 1
  { journalctl -q --no-pager -o cat -t sshd -t sshd-session --since "-60 days" 2>/dev/null; cat /var/log/auth.log 2>/dev/null; } \
    | grep "Accepted publickey for " | grep -F " from $ip port $port " >/dev/null    # no -q: an early exit fails the pipe
}

ssh_has_keys() { # a non-empty authorized_keys for root or a sudo/admin user
  local h
  for h in /root $(getent group sudo admin 2>/dev/null | cut -d: -f4 | tr ',' '\n' | xargs -r -n1 getent passwd | cut -d: -f6); do
    [ -s "$h/.ssh/authorized_keys" ] && grep -qE '^(ssh-|ecdsa-|sk-)' "$h/.ssh/authorized_keys" && return 0
  done
  return 1
}

# ssh_plan - prints "skip:<why>" | "done" | "apply"
ssh_plan() {
  [ "$SSH_HARDEN" = 0 ] && { echo "skip:SSH left as it is (SSH_HARDEN=0)"; return; }
  command -v sshd >/dev/null 2>&1 && [ -f "$SSHD_CONFIG" ] || { echo "skip:no OpenSSH server here"; return; }
  local eff
  eff=$(sshd -T 2>/dev/null | awk '$1=="passwordauthentication"||$1=="kbdinteractiveauthentication"{print $2}' | sort -u) || true
  [ "$eff" = no ] && { echo "done"; return; }
  grep -qiE '^[[:space:]]*Include[[:space:]]+(/etc/ssh/)?sshd_config\.d/\*\.conf' "$SSHD_CONFIG" \
    || { echo "skip:$SSHD_CONFIG does not include sshd_config.d - password logins left on (turn them off yourself)"; return; }
  ssh_has_keys || { echo "skip:no SSH key installed - password logins left on (add a key, then: SSH_HARDEN=1 install.sh --secure)"; return; }
  if ssh_session_uses_key; then echo apply
  elif [ "$SSH_HARDEN" = 1 ]; then echo apply
  else echo "skip:this session could not be proven to use an SSH key - password logins left on (SSH_HARDEN=1 install.sh --secure once you log in with a key)"
  fi
}

ssh_key_only() { # called by secure_server: adds to its "done" list
  local plan prl
  plan=$(ssh_plan)
  case "$plan" in
    done) done+=("SSH by key only (already)"); return 0 ;;
    "skip:SSH left as it is"*) info "${plan#skip:}"; return 0 ;;
    skip:*) warn "${plan#skip:}"; return 0 ;;
  esac
  prl=$(sshd -T 2>/dev/null | awk '$1=="permitrootlogin"{print $2}') || true
  mkdir -p "$(dirname "$SSH_DROPIN")"
  {
    echo "# Harness Maxxing (install.sh --secure): SSH logins by key only. To undo: rm $SSH_DROPIN && systemctl reload ssh"
    echo "PasswordAuthentication no"
    echo "KbdInteractiveAuthentication no"
    [ "$prl" = yes ] && echo "PermitRootLogin prohibit-password"     # only tightened, never loosened
  } > "$SSH_DROPIN"
  chmod 644 "$SSH_DROPIN"
  if ! sshd -t 2>/dev/null \
     || [ "$(sshd -T 2>/dev/null | awk '$1=="passwordauthentication"||$1=="kbdinteractiveauthentication"{print $2}' | sort -u)" != no ]; then
    rm -f "$SSH_DROPIN"
    warn "SSH configuration not changed (it did not validate) - password logins left on"
    return 0
  fi
  if systemctl is-active -q ssh 2>/dev/null; then systemctl reload ssh >/dev/null 2>&1 || true
  elif systemctl is-active -q sshd 2>/dev/null; then systemctl reload sshd >/dev/null 2>&1 || true
  fi                                                    # socket-activated sshd reads it on the next login
  manifest "ssh key-only"
  info "SSH password logins turned off (open sessions stay connected) - undo: rm $SSH_DROPIN && systemctl reload ssh"
  done+=("SSH by key only")
}

# ufw_has_port "RULES" PORT - a ufw rule already names this port (22, 22/tcp, OpenSSH for 22, or a range holding it)
ufw_has_port() {
  local r lo hi
  for r in $1; do
    r=${r%/tcp}; r=${r%/udp}
    case "$r" in
      "$2") return 0 ;;
      OpenSSH) [ "$2" = 22 ] && return 0 ;;
      *:*) lo=${r%%:*}; hi=${r##*:}
           case "$lo$hi" in *[!0-9]*) ;; *) [ "$2" -ge "$lo" ] && [ "$2" -le "$hi" ] && return 0 ;; esac ;;
      *,*) case ",$r," in *",$2,"*) return 0 ;; esac ;;
    esac
  done
  return 1
}

# ufw_tailscale - on the Tailscale interface: the web UI and SSH only (not every port of the server)
ufw_tailscale() {
  local p
  ufw allow in on tailscale0 to any port "$PORT" proto tcp comment 'Harness Maxxing (Tailscale)' >/dev/null
  for p in $(ssh_ports); do ufw allow in on tailscale0 to any port "$p" proto tcp comment 'SSH (Tailscale)' >/dev/null; done
}

ufw_ipv6_warn() {
  if grep -qE '^[[:space:]]*IPV6=no' /etc/default/ufw 2>/dev/null && [ -n "$(ip -6 addr show scope global 2>/dev/null)" ]; then
    warn "ufw is set to IPV6=no (/etc/default/ufw) but this server has IPv6: IPv6 traffic is NOT filtered"
  fi
}

# f2b_jail - our fail2ban jail for SSH, on the ports sshd really listens on (fail2ban's default is "ssh" = 22 only)
f2b_jail() {
  printf '# Harness Maxxing (written by install.sh, re-written by each run: put your own settings in another jail.d file)\n'
  printf '# ban an IP for 1 h after 5 failed SSH logins in 10 min, on the SSH ports of this server\n'
  printf '[sshd]\nenabled = true\nport = %s\nbackend = systemd\nmaxretry = 5\nfindtime = 10m\nbantime = 1h\n' \
    "$(ssh_ports | tr '\n' ',' | sed 's/,$//')"
}

# auto_upgrades_on - unattended security updates are really enabled (apt's own view, not just our file)
auto_upgrades_on() {
  systemctl is-enabled -q unattended-upgrades 2>/dev/null || return 1
  apt-config dump 2>/dev/null | grep '^APT::Periodic::Unattended-Upgrade "1"' >/dev/null   # no -q (pipefail + SIGPIPE)
}

secure_server() {
  local done=() failed=()
  if apt_get install -y -qq unattended-upgrades >>"$WORK/apt.log" 2>&1; then
    [ -f /etc/apt/apt.conf.d/20auto-upgrades ] && [ "$EXISTING" = 1 ] \
      || (umask 022; printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
           > /etc/apt/apt.conf.d/20auto-upgrades)
    systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true
    if auto_upgrades_on; then done+=("security updates")
    else failed+=("automatic security updates (unattended-upgrades is not enabled - see /etc/apt/apt.conf.d/20auto-upgrades)"); fi
  else
    failed+=("automatic security updates (unattended-upgrades could not be installed)")
  fi
  ssh_key_only
  if apt_get install -y -qq fail2ban python3-systemd >>"$WORK/apt.log" 2>&1; then
    rm -f /etc/fail2ban/jail.d/agent-maxxing.local                   # name used by early 2.0.0a5 builds
    local ours=/etc/fail2ban/jail.d/harness-maxxing.local
    if [ ! -f "$ours" ] \
       && ls /etc/fail2ban/jail.local /etc/fail2ban/jail.d/*.local /etc/fail2ban/jail.d/*.conf 2>/dev/null \
            | grep -v '/defaults-debian.conf$' | xargs -r grep -lqs '^\[sshd\]'; then   # the package's own default is not "theirs"
      info "fail2ban already guards SSH: your jail is kept"
    else
      (umask 022; f2b_jail > "$ours")
    fi
    systemctl enable fail2ban >/dev/null 2>&1 || true
    systemctl restart fail2ban >/dev/null 2>&1 || true
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do fail2ban-client status sshd >/dev/null 2>&1 && break; sleep 1; done
    if fail2ban-client status sshd >/dev/null 2>&1; then done+=("fail2ban (SSH $(ssh_ports | tr '\n' '/' | sed 's#/$##'))")
    else failed+=("fail2ban (its sshd jail is not running - journalctl -u fail2ban -n 30)"); fi
  else
    failed+=("fail2ban (could not be installed)")
  fi
  if [ "$FIREWALL" = 0 ]; then
    if [ -n "$PUBLIC_OTHER" ] || [ "$HAS_DOCKER" = 1 ]; then
      info "firewall not enabled: other services are reachable here (FIREWALL=1 install.sh --secure to force it)"
    else
      info "firewall skipped (FIREWALL=0)"
    fi
  elif systemd-detect-virt -cq 2>/dev/null; then
    info "container: the firewall is left to the host"; FW_ON=host
  elif [ "$FIREWALL" = add ]; then
    if [ "$FW_ACTIVE" = ufw ]; then
      local added="" p cur rules
      rules=$(ufw status 2>/dev/null | awk 'NR > 4 && $1 != "" {print $1}')
      # SSH: their rules stay as they are; only the port of this very connection, if no rule mentions it at all
      cur=$(ssh_connection 2>/dev/null | awk 'NF==4{print $4}')
      if [ -n "$cur" ] && ! ufw_has_port "$rules" "$cur"; then
        ufw allow "$cur/tcp" comment 'SSH' >/dev/null && added="$added + SSH $cur"
      fi
      if [ "$ACCESS" = domain ] && [ -z "$WEB_BUSY" ]; then
        for p in 80 443; do
          ufw_has_port "$rules" "$p" || { ufw allow "$p/tcp" comment 'Caddy' >/dev/null; added="$added + $p"; }
        done
      fi
      [ "$ACCESS" = tailscale ] && { ufw_tailscale; added="$added + tailscale0 ($PORT, SSH)"; }
      ufw_ipv6_warn
      done+=("your firewall kept${added:+ (${added# + } added)}"); FW_ON=1
    else
      info "your $FW_ACTIVE firewall is left as it is${ACCESS:+ - for a domain, ports 80/443 must be open}"; FW_ON=1
    fi
  elif apt_get install -y -qq ufw >>"$WORK/apt.log" 2>&1; then
    local p ports
    ports=$(ssh_ports)
    for p in $ports; do ufw allow "$p/tcp" comment 'SSH' >/dev/null; done
    if [ "$ACCESS" = domain ]; then
      ufw allow 80/tcp comment 'HTTP (Caddy)' >/dev/null
      ufw allow 443/tcp comment 'HTTPS (Caddy)' >/dev/null
    fi
    [ "$ACCESS" = tailscale ] && ufw_tailscale
    ufw default deny incoming >/dev/null
    ufw default allow outgoing >/dev/null
    local open
    open="SSH $(echo "$ports" | tr ' \n' '//' | sed 's#/$##')"
    [ "$ACCESS" = domain ] && open="$open 80 443"
    [ "$ACCESS" = tailscale ] && open="$open, tailscale0: $PORT + SSH"
    ufw_ipv6_warn
    ufw --force enable >/dev/null 2>&1 || true
    if ufw status 2>/dev/null | grep -q '^Status: active'; then done+=("firewall ($open)"); manifest "ufw enabled"; FW_ON=1
    else failed+=("firewall (ufw could not be turned on - ufw status verbose)"); fi
  else
    failed+=("firewall (ufw could not be installed)")
  fi
  if [ ${#done[@]} -gt 0 ]; then local out="" d; for d in "${done[@]}"; do out="${out:+$out · }$d"; done; ok "$out"; fi
  if [ ${#failed[@]} -gt 0 ]; then
    local f
    for f in "${failed[@]}"; do warn "NOT protected: $f"; done
    if [ "$ALLOW_UNPROTECTED" = 1 ]; then
      warn "continuing without it because ALLOW_UNPROTECTED=1"
    elif [ "$EXISTING" = 1 ] || [ "$PRIOR" = 1 ]; then   # its admin may have chosen otherwise: never stop a re-run halfway
      warn "continuing: this server was already in use (fix it, or ALLOW_UNPROTECTED=1 to silence this)"
    else
      die "a protection this installer turns on failed - fix it and run the same command again, or accept a server without it: ALLOW_UNPROTECTED=1 (FIREWALL=0 skips the firewall on purpose)"
    fi
  fi
}

# ---- license --------------------------------------------------------------------------------
machine_hash() {
  local raw=""
  raw=$(tr -d '[:space:]' </etc/machine-id 2>/dev/null || true)
  [ -n "$raw" ] || raw=$(tr -d '[:space:]' </var/lib/dbus/machine-id 2>/dev/null || true)
  [ -n "$raw" ] || die "/etc/machine-id is missing (run: systemd-machine-id-setup)"
  printf 'harness-maxxing:%s' "$raw" | sha256sum | cut -d' ' -f1
}

# json_get FILE KEY.SUBKEY - prints a value of a JSON file ("" when absent)
json_get() {
  python3 -I - "$1" "$2" <<'PY' 2>/dev/null || true
import json, sys
v = json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."):
    v = v.get(k) if isinstance(v, dict) else None
print("" if v is None else v)
PY
}

license_activate() {
  command -v curl >/dev/null 2>&1 || { apt_get update -qq >/dev/null 2>&1; apt_get install -y -qq curl ca-certificates >/dev/null 2>&1; }
  command -v python3 >/dev/null 2>&1 || { apt_get update -qq >/dev/null 2>&1; apt_get install -y -qq python3 >/dev/null 2>&1; }
  RELEASE_JSON="$WORK/activation.json"
  local code msg mh os
  mh=$(machine_hash)
  os=$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-linux}")
  # the key goes from a shell variable to python's stdin, then to curl's stdin: never in a command line (ps)
  code=$(printf '%s' "$LICENSE" \
    | python3 -I -c 'import json,sys; print(json.dumps({"key": sys.stdin.read().strip(), "machine_id": sys.argv[1], "hostname": sys.argv[2], "os": sys.argv[3]}))' \
        "$mh" "$(hostname)" "$os" \
    | curl -sS --proto '=https,http' -o "$RELEASE_JSON" -w '%{http_code}' -X POST -H 'content-type: application/json' \
        --data-binary @- "$LICENSE_API/v1/activate" 2>/dev/null || echo 000)
  if [ "$code" != 200 ]; then
    msg=$(json_get "$RELEASE_JSON" message)
    [ "$code" = 000 ] && msg="cannot reach $LICENSE_API (network?)"
    die "license refused: ${msg:-HTTP $code}"
  fi
  [ -n "$(json_get "$RELEASE_JSON" release.url)" ] || die "license OK but $(json_get "$RELEASE_JSON" message || echo 'no version is available yet')"
  ok "license ${LICENSE:0:7}…${LICENSE: -4} ($(json_get "$RELEASE_JSON" license.kind), $(json_get "$RELEASE_JSON" license.email)) - version $(json_get "$RELEASE_JSON" release.version)"
}

# the signed release of the activation -> $INSTALL_DIR as a git repository (origin/main = this version)
# release_pubkey KID - the public key of a key id, nothing (status 1) for an unknown id
release_pubkey() {
  local k
  for k in $RELEASE_KIDS; do
    if [ "$k" = "$1" ]; then local v="RELEASE_PUBKEY_$k"; printf '%s' "${!v}"; return 0; fi
  done
  return 1
}

# release_verified DIR KID - DIR/msg is signed (DIR/sig) by the key KID, or by any known key when KID is empty
release_verified() {
  local k
  for k in ${2:-$RELEASE_KIDS}; do
    release_pubkey "$k" > "$1/pub.pem" || return 1
    openssl pkeyutl -verify -pubin -inkey "$1/pub.pem" -rawin -in "$1/msg" -sigfile "$1/sig" >/dev/null 2>&1 && return 0
  done
  return 1
}

fetch_release() {
  local tmp ver sha sig url kid got
  tmp="$WORK/release"; mkdir -p "$tmp"
  ver=$(json_get "$RELEASE_JSON" release.version); sha=$(json_get "$RELEASE_JSON" release.sha256)
  sig=$(json_get "$RELEASE_JSON" release.signature); url=$(json_get "$RELEASE_JSON" release.url)
  kid=$(json_get "$RELEASE_JSON" release.kid)
  url_ok "$url" || die "the release is not served over HTTPS ($url) - refused"
  [ -z "$kid" ] || release_pubkey "$kid" >/dev/null \
    || die "the release is signed with a key this installer does not know ($kid) - get the latest installer"
  printf '%s' "$sha" | grep -Eq '^[0-9a-f]{64}$' || die "the license server sent an invalid checksum - refused"
  ver_lt "$ver" "$MIN_VERSION" && die "the license server offers version $ver, older than $MIN_VERSION - refused"
  fetch_verified "$url" "$sha" "$tmp/release.tar.gz" || die "download of version $ver failed or does not match its sha256 - run the command again"
  command -v openssl >/dev/null 2>&1 || apt_get install -y -qq openssl >/dev/null 2>&1
  printf 'harness-maxxing|%s|%s' "$ver" "$sha" > "$tmp/msg"
  printf '%s' "$sig" | base64 -d > "$tmp/sig" 2>/dev/null || die "the downloaded archive is not signed by Harness Maxxing - refused"
  release_verified "$tmp" "$kid" \
    || die "the downloaded archive is not signed by Harness Maxxing - refused"
  # the signed version must be the one inside the archive (a signature is only worth the version it names)
  got=$(tar -xzOf "$tmp/release.tar.gz" ./server/maxxing/__init__.py 2>/dev/null || tar -xzOf "$tmp/release.tar.gz" server/maxxing/__init__.py 2>/dev/null || true)
  got=$(printf '%s\n' "$got" | sed -n 's/^__version__ = "\(.*\)"$/\1/p' | head -n1)
  [ "$got" = "$ver" ] || die "the archive holds version '${got:-?}', not the signed $ver - refused"
  (umask 022; mkdir -p "$INSTALL_DIR")
  (umask 022; tar -xzf "$tmp/release.tar.gz" -C "$INSTALL_DIR" --no-same-owner --no-same-permissions) || die "cannot extract version $ver"
  local id=(-c user.name="Harness Maxxing" -c user.email="releases@harness-maxxing.com")
  git -C "$INSTALL_DIR" init -q -b "$BRANCH" --
  git -C "$INSTALL_DIR" add -A -f
  git "${id[@]}" -C "$INSTALL_DIR" commit -q -m "Harness Maxxing $ver" || die "git commit of version $ver failed"
  git -C "$INSTALL_DIR" update-ref "refs/remotes/origin/$BRANCH" HEAD
  rm -rf "$tmp"                                  # the archive is in git now: no copy is kept
  ok "version $ver downloaded, signature verified, installed in $INSTALL_DIR"
}

# ---- code -----------------------------------------------------------------------------------
# fetch_local - SOURCE_DIR copied into $INSTALL_DIR as a git repository without remote (= what a release does)
fetch_local() {
  local src=$SOURCE_DIR ver id=(-c user.name="Harness Maxxing" -c user.email="local@localhost")
  if [ -z "$src" ]; then ok "local install in $INSTALL_DIR (no remote) - kept"; return; fi
  src=$(cd "$src" 2>/dev/null && pwd -P) || die "SOURCE_DIR=$SOURCE_DIR not found"
  [ -f "$src/server/maxxing/__init__.py" ] && [ -f "$src/install.sh" ] || die "$src is not a Harness Maxxing source tree"
  [ -f "$src/web/dist/index.html" ] || die "$src/web/dist is missing (the built web UI): use a release archive, or build it (cd web && npm ci && npm run build)"
  ver=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$src/server/maxxing/__init__.py" | head -n1)
  if [ -d "$INSTALL_DIR/.git" ]; then
    if [ -n "$(git -C "$INSTALL_DIR" status --porcelain 2>/dev/null)" ]; then
      warn "changes in $INSTALL_DIR are not committed - kept as it is (maxxing custom save, then run this again)"; return
    fi
    git -C "$INSTALL_DIR" ls-files -z | (cd "$INSTALL_DIR" && xargs -0 -r rm -f)
  elif [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
    die "$INSTALL_DIR exists and is not a Harness Maxxing install - move it away or set INSTALL_DIR"
  fi
  (umask 022; mkdir -p "$INSTALL_DIR")
  if git -C "$src" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    (cd "$src" && git ls-files -z -co --exclude-standard | grep -zv '^web/node_modules' | tar --null -cf - -T -) \
      | (umask 022; tar -xf - -C "$INSTALL_DIR" --no-same-owner) || die "cannot copy $src"
  else
    (cd "$src" && tar -cf - --exclude=./.git --exclude=./server/.venv --exclude=./web/node_modules --exclude='__pycache__' .) \
      | (umask 022; tar -xf - -C "$INSTALL_DIR" --no-same-owner) || die "cannot copy $src"
  fi
  [ -d "$INSTALL_DIR/.git" ] || git -C "$INSTALL_DIR" init -q -b "$BRANCH" --
  git -C "$INSTALL_DIR" add -A
  if git -C "$INSTALL_DIR" diff --cached --quiet 2>/dev/null; then ok "local copy $ver - unchanged"; return; fi
  git "${id[@]}" -C "$INSTALL_DIR" commit -q -m "Harness Maxxing $ver (local copy of $src)" || die "git commit of the local copy failed"
  ok "version $ver copied from $src into $INSTALL_DIR (no remote: updates come from a newer copy)"
}

fetch_code() {
  local url="https://github.com/$REPO.git"
  export GIT_TERMINAL_PROMPT=0
  if [ "$LOCAL" = 1 ]; then fetch_local; return; fi
  if [ -d "$INSTALL_DIR/.git" ] && [ "$LICENSED" = 1 ]; then
    ok "licensed install in $INSTALL_DIR - kept (update with: maxxing update)"
    return
  fi
  if [ "$LICENSED" = 1 ]; then
    if [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
      die "$INSTALL_DIR exists and is not a Harness Maxxing install - move it away or set INSTALL_DIR"
    fi
    fetch_release
    return
  fi
  if [ -d "$INSTALL_DIR/.git" ]; then
    if [ -z "$GH_TOKEN" ]; then
      GH_TOKEN=$(MAXXING_STATE="$STATE_DIR" "$(venv_py)" -I -c 'from maxxing import config; print(config.get_secret("github_update_token") or "")' 2>/dev/null || true)
    fi
    if git_tok -C "$INSTALL_DIR" fetch -q origin -- "$BRANCH" 2>/dev/null; then
      [ -n "$GH_TOKEN" ] && TOKEN_USED=1
      git -C "$INSTALL_DIR" checkout -q "$BRANCH" -- 2>/dev/null || git -C "$INSTALL_DIR" checkout -q -b "$BRANCH" --track "origin/$BRANCH" --
      if git -C "$INSTALL_DIR" merge -q --ff-only "origin/$BRANCH" >/dev/null 2>&1; then
        ok "updated to $(git -C "$INSTALL_DIR" rev-parse --short HEAD)"
      else
        warn "customizations in $INSTALL_DIR - kept; update with: maxxing update (carries them over)"
      fi
    else
      warn "could not reach $url - keeping the current code"
    fi
    return
  fi
  if [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
    die "$INSTALL_DIR exists and is not a git clone - move it away or set INSTALL_DIR"
  fi
  mkdir -p "$(dirname "$INSTALL_DIR")"
  if [ -z "$GH_TOKEN" ] && (umask 022; git clone -q -b "$BRANCH" -- "$url" "$INSTALL_DIR") 2>/dev/null; then
    ok "cloned into $INSTALL_DIR"
    return
  fi
  rm -rf "$INSTALL_DIR"
  [ -n "$GH_TOKEN" ] || die "cannot clone $url (private repository? set GH_TOKEN)"
  (umask 022; git_tok clone -q -b "$BRANCH" -- "$url" "$INSTALL_DIR") 2>/dev/null \
    || die "cannot clone $url with this token (needs Contents: read on $REPO)"
  TOKEN_USED=1
  ok "cloned into $INSTALL_DIR (token kept out of .git/config)"
}

setup_python() {
  local extra=()
  if [ "$VOICE" = local ] || [ -f "$STATE_DIR/voice/extra-installed" ]; then
    extra=(--extra voice)                       # faster-whisper (local voice transcription)
    mkdir -p "$STATE_DIR/voice" && touch "$STATE_DIR/voice/extra-installed"
  fi
  # the managed Python goes to <state>/tools/python (not ~/.local: a cleanup there would break the service)
  mkdir -p "$STATE_DIR/tools/python" && chmod 700 "$STATE_DIR"
  (cd "$INSTALL_DIR/server" && UV_PYTHON_INSTALL_DIR="$STATE_DIR/tools/python" UV_PYTHON_PREFERENCE=only-managed \
     "$UV" sync --frozen --no-dev --quiet --python "$(dep python version || echo 3.12)" "${extra[@]}") \
    || die "uv sync failed in $INSTALL_DIR/server"
  local exe="$INSTALL_DIR/server/.venv/bin/maxxing"
  [ -x "$exe" ] || die "$exe missing after uv sync"
  if [ "$STATE_DIR" = "$DEFAULT_STATE" ]; then
    ln -sfn "$exe" "$BIN"
  else
    rm -f "$BIN"
    printf '#!/bin/bash\n# claude-maxxing CLI wrapper (custom state dir)\nexport MAXXING_STATE=%q\nexec %q "$@"\n' \
      "$STATE_DIR" "$exe" > "$BIN"
    chmod 755 "$BIN"
  fi
  ok "$(mx --version 2>/dev/null || echo maxxing) -> $BIN"
}

init_state() {
  mkdir -p -m 700 "$STATE_DIR" "$STATE_DIR/logs"
  chmod 700 "$STATE_DIR" "$STATE_DIR/logs"
  local args=(init --workspace "$WORKSPACE" --port "$PORT" --bind "$BIND" --public-url "$PUBLIC_URL")
  "$(venv_py)" -m maxxing init --help 2>/dev/null | grep -- --system-clock >/dev/null && args+=(--system-clock "$SYSTEM_CLOCK")
  if [ -n "$CLAUDE_DIR" ]; then
    mkdir -p "$CLAUDE_DIR" && chmod 700 "$CLAUDE_DIR"
    args+=(--claude-dir "$CLAUDE_DIR")
  fi
  [ -n "$TIMEZONE" ] && args+=(--timezone "$TIMEZONE")
  :
  rm -f "$STATE_DIR/logs/install-init.log"     # holds the setup link: 0600 (umask), removed after the banner
  mx "${args[@]}" > "$STATE_DIR/logs/install-init.log" 2>&1 || { cat "$STATE_DIR/logs/install-init.log"; die "maxxing init failed"; }
  grep -E '^ *[✔!✘–]' "$STATE_DIR/logs/install-init.log" | sed -E 's/^ *//; s/^/      /' || true
  if [ "$TOKEN_USED" = 1 ] && [ -n "$GH_TOKEN" ]; then
    printf '%s' "$GH_TOKEN" | mx init --quiet --no-crons --secret-from-stdin github_update_token \
      && ok "update token stored in $STATE_DIR/secrets.json (used by maxxing update)"
  fi
  if [ -n "$LICENSE" ]; then                       # optional Enterprise key: recorded, checked by the license server
    LICENSE=$(printf '%s' "$LICENSE" | tr -d '[:space:]' | tr '[:lower:]' '[:upper:]')
    local lic_env=()
    [ "$LICENSE_API" = https://api.harness-maxxing.com ] || lic_env=(MAXXING_LICENSE_API="$LICENSE_API")
    printf '%s\n' "$LICENSE" | env ${lic_env[@]+"${lic_env[@]}"} MAXXING_STATE="$STATE_DIR" "$BIN" license activate --key-from-stdin --no-fetch >/dev/null \
      && ok "Enterprise key recorded (Settings -> License, maxxing license status)" \
      || warn "could not record the Enterprise key ${LICENSE:0:7}…${LICENSE: -4} - Settings -> License, or: maxxing license activate"
  fi
  if [ -n "$CLAUDE_TOKEN" ]; then
    printf '%s' "$CLAUDE_TOKEN" | mx init --quiet --no-crons --secret-from-stdin claude_oauth_token && ok "Claude token stored"
  fi
  if [ -n "$ANTHROPIC_API_KEY" ]; then
    printf '%s' "$ANTHROPIC_API_KEY" | mx init --quiet --no-crons --secret-from-stdin anthropic_api_key && ok "Anthropic API key stored"
  fi
  if [ -n "$VOICE" ]; then
    mx voice set --engine "$VOICE" >/dev/null || warn "could not enable voice messages (Settings -> Voice)"
    case "$VOICE" in
      local)                                    # the model comes with the tools (maxxing deps update)
        info "the speech model (~150-500 MB) is downloaded with the tools" ;;
      groq|openai)
        info "add your ${VOICE^^}_API_KEY in Settings -> Voice to finish" ;;
    esac
  fi
}

restore_backup() {
  if [ -z "$RESTORE_FROM" ]; then
    info "skipped (no RESTORE_FROM) - configure the backup later in Settings -> Backup"
    return
  fi
  if ! mx backup restore --help >/dev/null 2>&1; then
    warn "this version has no 'maxxing backup restore' - restore later from Settings -> Backup"
    return
  fi
  # held like on a server in use: whoever can push to the backup repository must not get code run here before
  # you said yes (jobs, extensions, Claude Code hooks, local MCP servers; product patches are not applied)
  if MAXXING_GITHUB_TOKEN="$RESTORE_TOKEN" mx backup restore --from "$RESTORE_FROM" --hold </dev/null >"$WORK/restore.log" 2>&1; then
    ok "memory restored from $RESTORE_FROM"
    RESTORED=1
  else
    tail -n 5 "$WORK/restore.log" | sed 's/^/      | /'
    warn "restore failed - retry with: maxxing backup restore --from $RESTORE_FROM  (it asks for the token)"
  fi
}

# restore_review - outside a step (it may ask): what the restore kept off, then turn it on only on an explicit yes
restore_review() {
  [ "${RESTORED:-0}" = 1 ] || return 0
  local held patches=""
  held=$(mx backup held 2>/dev/null | grep '^  - ' || true)
  if [ -d "$WORKSPACE/customizations" ] && mx custom --help >/dev/null 2>&1; then
    patches=$(mx custom restore --stat 2>/dev/null | grep -v '^No saved customization' || true)
  fi
  [ -n "$held$patches" ] || return 0
  section "Restored but kept off"
  [ -z "$held" ] || printf '%s\n' "$held" | sed 's/^  /      /'
  if [ -n "$patches" ]; then
    info "changes to the product code saved in the backup (not applied):"
    printf '%s\n' "$patches" | head -n 40 | sed 's/^/        /'
  fi
  info "they come from $RESTORE_FROM: whoever can write to that repository wrote them"
  if [ "$RESTORE_TRUST" = 1 ] || ask_yn "Turn all of this on now? (only if you trust everything in $RESTORE_FROM)" n; then
    mx backup release >/dev/null 2>&1 && ok "restored jobs, extensions, hooks and MCP servers turned on" \
      || warn "could not turn them on - run: maxxing backup release"
    if [ -n "$patches" ]; then
      if mx custom restore >/dev/null 2>&1; then
        ok "customizations of the product code re-applied (CUSTOMIZATIONS.md)"
        systemctl restart "$SERVICE" >/dev/null 2>&1 || true
      else
        warn "saved customizations do not apply to this version - ask Claude in the topic system/update"
      fi
    fi
  else
    ok "kept off - check them, then: maxxing backup release${patches:+ and maxxing custom restore} (or the Crons / Extensions pages)"
  fi
}

# ---- access ---------------------------------------------------------------------------------
setup_caddy() {
  if ! command -v caddy >/dev/null 2>&1; then
    command -v gpg >/dev/null 2>&1 || apt_get install -y -qq gnupg >>"$WORK/apt.log" 2>&1 || true
    caddy_repo || die "Caddy's signing key does not match the expected fingerprint - refused"
    { apt_get update -qq -o Dir::Etc::sourcelist="$(dep caddy apt_list)" -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 \
        && apt_get install -y -qq caddy; } >>"$WORK/apt.log" 2>&1 \
      || { tail -n 15 "$WORK/apt.log"; die "Caddy installation failed"; }
    ok "Caddy installed"
    manifest "caddy installed"
  fi
  (umask 022; mkdir -p /etc/caddy /etc/caddy/maxxing-paths)
  local before_cf=""
  [ -f "$CADDYFILE" ] && before_cf=$(cat "$CADDYFILE")
  (umask 022; cat > "$CADDY_SITE") <<EOF
# Harness Maxxing (written by install.sh - re-run the installer to change it)
$DOMAIN {
	encode zstd gzip
	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options "nosniff"
		X-Frame-Options "SAMEORIGIN"
		Referrer-Policy "same-origin"
		-Server
	}
	request_body {
		max_size 2100MB
	}
	# sites under this address (maxxing infra site add): https://$DOMAIN/<name>/, sandboxed
	import /etc/caddy/maxxing-paths/*.caddy
	reverse_proxy 127.0.0.1:$PORT {
		flush_interval -1
	}
}
EOF
  # a Caddyfile that is ours (stock welcome page, empty, or only our import): written whole, with Caddy's admin
  # API on a socket only root and caddy can open instead of 127.0.0.1:2019 (any local user could reconfigure it)
  if [ ! -s "$CADDYFILE" ] || grep -q '/usr/share/caddy' "$CADDYFILE" \
     || ! grep -vE "^[[:space:]]*(#.*)?$|^import $CADDY_SITE\$|^\{\$|^\}\$|^[[:space:]]*admin unix//run/caddy/admin\.sock\$" "$CADDYFILE" | grep . >/dev/null; then
    caddy_admin_dropin
    (umask 022; printf '{\n\tadmin unix//run/caddy/admin.sock\n}\n\nimport %s\n' "$CADDY_SITE" > "$CADDYFILE")
  elif ! grep -qF "$CADDY_SITE" "$CADDYFILE"; then
    if grep -qE "^[[:space:]]*${DOMAIN//./\\.}([[:space:]:,{]|$)" "$CADDYFILE"; then
      die "$CADDYFILE already serves $DOMAIN - remove that block, then re-run"
    fi
    printf '\nimport %s\n' "$CADDY_SITE" >> "$CADDYFILE"
  fi
  chmod 644 "$CADDY_SITE" "$CADDYFILE"; chmod 755 /etc/caddy/maxxing-paths
  caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1 \
    || die "invalid Caddy configuration - see: caddy validate --config $CADDYFILE --adapter caddyfile"
  systemctl enable --now caddy >/dev/null 2>&1 || true
  if [ "$before_cf" != "$(cat "$CADDYFILE")" ]; then          # the admin address may have changed: reload cannot
    systemctl restart caddy >/dev/null 2>&1 || die "Caddy did not start: journalctl -u caddy -n 50"
  else
    systemctl reload caddy >/dev/null 2>&1 || systemctl restart caddy >/dev/null 2>&1 || die "Caddy did not start: journalctl -u caddy -n 50"
  fi
  ok "Caddy serves https://$DOMAIN -> 127.0.0.1:$PORT"
}

# caddy_repo - Caddy's apt repository: its signing key checked against the fingerprint of deps.toml, our own source line
caddy_repo() {
  local g="$WORK/gnupg" fpr want url ring list
  want=$(dep caddy key_fingerprint) && url=$(dep caddy key_url) && ring=$(dep caddy keyring) && list=$(dep caddy apt_list) \
    || { warn "Caddy is not described in deps.toml"; return 1; }
  mkdir -p -m 700 "$g"
  case "$url" in https://*) ;; *) return 1 ;; esac
  curl -fsSL --proto '=https' "$url" -o "$WORK/caddy.key" || return 1
  fpr=$(GNUPGHOME="$g" gpg --batch --show-keys --with-colons "$WORK/caddy.key" 2>/dev/null | awk -F: '/^fpr/ {print $10; exit}')
  [ "$fpr" = "$want" ] || { warn "Caddy key fingerprint ${fpr:-?} != $want (deps.toml)"; return 1; }
  (umask 022
   GNUPGHOME="$g" gpg --batch --yes --dearmor -o "$ring" "$WORK/caddy.key" \
   && printf '%s\n' "$(dep caddy apt_source)" > "$list") || return 1
  chmod 644 "$ring" "$list"
}

# caddy_admin_dropin - /run/caddy (owned by caddy) for the admin socket of the Caddyfile we write
caddy_admin_dropin() {
  local d=/etc/systemd/system/caddy.service.d
  [ -f "$d/harness-maxxing-admin.conf" ] && return 0
  (umask 022; mkdir -p "$d" && printf '# Harness Maxxing: directory of the admin socket (admin unix//run/caddy/admin.sock)\n[Service]\nRuntimeDirectory=caddy\nRuntimeDirectoryPreserve=yes\n' \
    > "$d/harness-maxxing-admin.conf")
  systemctl daemon-reload
  manifest "caddy admin socket"
}

# dns_check - does DOMAIN point to this server? (warning only: proxies and NAT exist)
dns_check() {
  local resolved mine
  resolved=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || true)
  mine=$(curl -4 -fsS --max-time 4 https://api.ipify.org 2>/dev/null || true)
  if [ -z "$resolved" ]; then
    warn "$DOMAIN does not resolve yet - create its DNS A record; the certificate is issued once it does"
  elif [ "$resolved" = "$mine" ] || hostname -I 2>/dev/null | tr ' ' '\n' | grep -qxF "$resolved"; then
    ok "$DOMAIN points to this server ($resolved)"
  else
    warn "$DOMAIN resolves to $resolved, not to this server${mine:+ ($mine)} - behind a proxy? turn it off (DNS only)"
  fi
}

# proxy_snippet - another web server (nginx, apache...) already owns 80/443: leave it alone and give
# the block to add to it (saved in <state>/reverse-proxy.conf).
proxy_snippet() {
  local f="$STATE_DIR/reverse-proxy.conf"
  mkdir -p "$STATE_DIR"
  case "$WEB_BUSY" in
    nginx*) cat > "$f" <<NGINX
# Harness Maxxing behind nginx - e.g. /etc/nginx/sites-available/harness-maxxing, then:
#   ln -s /etc/nginx/sites-available/harness-maxxing /etc/nginx/sites-enabled/ && nginx -t && systemctl reload nginx
#   certbot --nginx -d $DOMAIN        (HTTPS certificate)
server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 500m;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 1h;
    }
}
NGINX
    ;;
    apache*|httpd*) cat > "$f" <<APACHE
# Harness Maxxing behind Apache - e.g. /etc/apache2/sites-available/harness-maxxing.conf, then:
#   a2enmod proxy proxy_http && a2ensite harness-maxxing && systemctl reload apache2
#   certbot --apache -d $DOMAIN       (HTTPS certificate)
<VirtualHost *:80>
    ServerName $DOMAIN
    ProxyPreserveHost On
    ProxyTimeout 3600
    ProxyPass / http://127.0.0.1:$PORT/ flushpackets=on
    ProxyPassReverse / http://127.0.0.1:$PORT/
    LimitRequestBody 524288000
</VirtualHost>
APACHE
    ;;
    *) cat > "$f" <<OTHER
# Harness Maxxing behind your own reverse proxy ($WEB_BUSY on ports 80/443):
#   https://$DOMAIN  ->  http://127.0.0.1:$PORT
# keep responses unbuffered (live updates use server-sent events), allow uploads up to 500 MB
# and long requests (1 h).
OTHER
    ;;
  esac
  ok "$WEB_BUSY keeps ports 80/443 - add the block saved in $f to it"
  info "then https://$DOMAIN opens Harness Maxxing (Caddy was not installed)"
}

setup_access() {
  case "$ACCESS" in
    domain) if [ -n "$WEB_BUSY" ]; then proxy_snippet; else setup_caddy; fi ;;
    tailscale) ok "reachable at $PUBLIC_URL from your Tailscale devices" ;;
    local) ok "listening on 127.0.0.1:$PORT only (SSH tunnel)" ;;
  esac
  if [ "$ACCESS" != domain ] && [ -f "$CADDY_SITE" ]; then
    warn "an old Caddy site exists ($CADDY_SITE) - remove it and its import line in $CADDYFILE if unused"
  fi
}

# ---- service --------------------------------------------------------------------------------
# service_memory_max - the web server's memory cap (F01: a flood of requests must not take the whole server down):
# 60 % of the memory, at least 1 GB. Sessions and jobs run in their own units, outside this cap.
service_memory_max() {
  local m cap
  m=$(mem_mb)
  cap=$(( ${m:-0} * 60 / 100 ))
  [ "$cap" -ge 1024 ] || cap=1024
  echo "${cap}M"
}

# unit_text - the systemd unit of the web server
unit_text() {
  cat <<EOF
[Unit]
Description=Harness Maxxing - web control room for Claude Code
After=network-online.target$AFTER
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=root
ExecStart=$BIN serve
WorkingDirectory=$WORKSPACE
Environment=MAXXING_STATE=$STATE_DIR
Environment=HOME=$HOME
Environment=PATH=$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Restart=always
RestartSec=3
TimeoutStopSec=15
MemoryMax=$(service_memory_max)

[Install]
WantedBy=multi-user.target
EOF
}

setup_service() {
  mkdir -p "$WORKSPACE"
  (umask 022; unit_text > "$UNIT")
  rm -f "$UNIT.d/20-memory.conf"                # added by `maxxing init` to units without MemoryMax
  # sandboxing drop-in: same text as HARDENING in server/maxxing/cmd_core.py (`maxxing harden --undo` removes it)
  (umask 022; mkdir -p "$UNIT.d")
  (umask 022; cat > "$UNIT.d/10-hardening.conf") <<'EOF'
# Harness Maxxing - sandboxing of the server process (`maxxing harden --undo` removes it)
[Service]
NoNewPrivileges=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictRealtime=yes
LockPersonality=yes
SystemCallArchitectures=native
TasksMax=2048
EOF
  systemctl daemon-reload
  systemctl enable "$SERVICE" >/dev/null 2>&1
  systemctl restart "$SERVICE"
  local url="http://$BIND:$PORT/api/auth/state" i
  for i in $(seq 1 30); do
    curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null && break
    sleep 1
  done
  curl -fsS -o /dev/null --max-time 3 "$url" 2>/dev/null \
    || die "the server does not answer on $url - journalctl -u $SERVICE -n 50 --no-pager"
  ok "running on $BIND:$PORT (systemctl status $SERVICE)"
}

# tunnel_cmd - the SSH tunnel to type on your computer: the user, address and port this very session came in with
# (an Ubuntu cloud server is reached as ubuntu@, often on another port; root@<first address> was often wrong)
tunnel_cmd() {
  local conn addr sport user opt=""
  conn=$(ssh_connection 2>/dev/null || true)
  addr=$(echo "$conn" | awk 'NF==4{print $3}'); sport=$(echo "$conn" | awk 'NF==4{print $4}')
  [ -n "$addr" ] || addr=$(hostname -I 2>/dev/null | awk '{print $1}')
  user=${SUDO_USER:-}
  [ -n "$user" ] || user=$(logname 2>/dev/null || true)
  [ -n "$user" ] || user=root
  [ -n "$sport" ] && [ "$sport" != 22 ] && opt=" -p $sport"
  printf 'ssh -N -L %s:127.0.0.1:%s%s %s@%s' "$PORT" "$PORT" "$opt" "$user" "${addr:-<server address>}"
}

# box_row "text with colours" - one line of the final box, padded to BOX_W visible characters
box_row() {
  local plain pad
  plain=$(printf '%s' "$1" | sed $'s/\033\\[[0-9;]*m//g')
  pad=$((BOX_W - ${#plain}))
  [ "$pad" -lt 0 ] && pad=0
  printf '  %s│%s  %s%*s  %s│%s\n' "$C_A" "$C_0" "$1" "$pad" "" "$C_A" "$C_0"
}
box_rule() { # box_rule ╭ ╮
  local line
  line=$(printf '%*s' $((BOX_W + 4)) '' | sed 's/ /─/g')
  printf '  %s%s%s%s%s\n' "$C_A" "$1" "$line" "$2" "$C_0"
}

banner() {
  local link took
  link=$(mx setup-link 2>/dev/null || true)
  took=$(fmt_secs $((SECONDS - T_START)))
  BOX_W=62
  [ ${#link} -gt $BOX_W ] && BOX_W=${#link}
  echo
  box_rule ╭ ╮
  box_row ""
  box_row "$C_G$C_B✔  Harness Maxxing is installed$C_0  $C_D($took)$C_0"
  box_row ""
  if [ "$ACCESS" = local ]; then
    box_row "From your computer, open an SSH tunnel and keep it open:"
    box_row "$C_B$(tunnel_cmd)$C_0"
    box_row ""
  fi
  case "$link" in
    http*)
      box_row "Open this link to create your password:"
      box_row ""
      box_row "$C_W$C_B$link$C_0"
      box_row ""
      box_row "$C_Y!$C_0 $C_D""One-time link, valid 1 hour: whoever opens it first owns$C_0"
      box_row "$C_D""  this server. Expired or lost? run: maxxing setup-link$C_0" ;;
    *)
      box_row "Already set up - sign in at:"
      box_row "$C_W$C_B${PUBLIC_URL:-http://127.0.0.1:$PORT}$C_0"
      box_row "$C_D""Password lost? run: maxxing password$C_0" ;;
  esac
  if [ "${FW_ON:-0}" = 0 ]; then
    box_row ""
    box_row "$C_Y!$C_0 No firewall was turned on (other services run here)."
    box_row "$C_D""  To turn it on anyway: FIREWALL=1 bash $INSTALL_DIR/install.sh --secure$C_0"
  fi
  box_row ""
  if [ "${TOOLS_BG:-0}" = 1 ]; then
    box_row "$C_D""Tools (browser, video, voice model) are installing in the$C_0"
    box_row "$C_D""background - maxxing deps list shows them.$C_0"
    box_row ""
  fi
  box_row "The web onboarding then connects Claude, your first project,"
  box_row "Telegram, voice and the memory backup."
  box_row ""
  box_rule ╰ ╯
  echo
  printf '  %smaxxing doctor%s   check everything      %smaxxing update%s   update\n' "$C_C" "$C_0" "$C_C" "$C_0"
  printf '  %smaxxing status%s   summary               %smaxxing --help%s   all commands\n' "$C_C" "$C_0" "$C_C" "$C_0"
  echo
  rm -f "$STATE_DIR/logs/install-init.log"
}

# ---- entry points ---------------------------------------------------------------------------
do_update() {
  [ "$(id -u)" = 0 ] || die "Run as root."
  [ -x "$BIN" ] || die "Harness Maxxing is not installed ($BIN missing) - run the installer without --update"
  mx update
}

do_uninstall() {
  [ "$(id -u)" = 0 ] || die "Run as root."
  local args=(uninstall)
  [ "$ASSUME_YES" = 1 ] && args+=(--yes)
  [ "$PURGE" = 1 ] && args+=(--purge)
  [ "$PURGE_WS" = 1 ] && args+=(--purge-workspace)
  if [ -x "$BIN" ]; then
    mx "${args[@]}"
  else
    warn "maxxing CLI not found - removing the service only"
    systemctl disable --now "$SERVICE" >/dev/null 2>&1 || true
    rm -f "$UNIT"
    systemctl daemon-reload
    ok "service removed"
  fi
}

main() {
  local mode=install
  PURGE=0
  PURGE_WS=0
  reset_env                                   # every mode: root's HOME and PATH, not the caller's
  while [ $# -gt 0 ]; do
    case "$1" in
      --update) mode=update ;;
      --uninstall) mode=uninstall ;;
      --tools) mode=tools ;;
      --secure) mode=secure ;;
      --check) mode=check ;;
      --purge) PURGE=1 ;;
      --purge-workspace) PURGE_WS=1 ;;
      -y|--yes) ASSUME_YES=1 ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown option: $1 (see --help)" ;;
    esac
    shift
  done
  case "$mode" in
    update) do_update; exit $? ;;
    uninstall) do_uninstall; exit $? ;;
    secure) [ "$(id -u)" = 0 ] || die "Run as root."
            check_inputs
            if [ -z "$ACCESS" ]; then
              if [ -f "$CADDY_SITE" ]; then ACCESS=domain
              else case "$(cfg_get bind)" in 100.*) ACCESS=tailscale ;; *) ACCESS=local ;; esac; fi
            fi
            detect_server
            TOTAL=1; run_step "Server security ($ACCESS)" secure_server; exit $? ;;
    tools) [ "$(id -u)" = 0 ] || die "Run as root."; check_inputs
           [ -x "$BIN" ] || die "Harness Maxxing is not installed ($BIN missing)"
           TOTAL=1; run_step "Tools (Node.js, Chromium, Remotion, Scrapling)" install_tools_now; exit $? ;;
  esac
  logo
  check_system
  detect_server
  preflight
  if [ "$mode" = check ]; then
    printf '\n      %snothing was changed (--check)%s\n\n' "$C_D" "$C_0"
    exit 0
  fi
  if [ "$EXISTING" = 1 ] && has_tty && ! ask_yn "Continue the installation?" y; then
    echo "      Stopped - nothing was changed."; exit 0
  fi
  choose_access
  [ -n "$RESTORE_FROM" ] || TOTAL=$((TOTAL - 1))
  [ "$TOOLS" = foreground ] || TOTAL=$((TOTAL - 1))
  section "Installing"
  if [ -x "$BIN" ]; then printf '      %sre-run: only what changed is redone - nothing else to answer%s\n\n' "$C_D" "$C_0"
  else printf '      %s3 to 6 minutes on a small server - nothing else to answer%s\n\n' "$C_D" "$C_0"; fi
  run_step "System packages" install_packages
  align_tz
  run_step "Harness Maxxing code" fetch_code
  prefetch
  run_step "Python toolchain (uv)" install_uv
  run_step "Python environment" setup_python
  run_step "Claude Code" install_claude
  run_step "Workspace, skills and jobs" init_state
  [ -z "$RESTORE_FROM" ] || { run_step "Memory restore" restore_backup; restore_review; }
  case "$ACCESS" in
    domain) run_step "HTTPS with Caddy" setup_access ;;
    *) run_step "Access ($ACCESS)" setup_access ;;
  esac
  run_step "Server security" secure_server
  run_step "Service" setup_service
  start_tools
  banner
}

# MAXXING_INSTALL_LIB=1: only define the functions (tests source the script; nothing runs)
[ "${MAXXING_INSTALL_LIB:-0}" = 1 ] || main "$@"
