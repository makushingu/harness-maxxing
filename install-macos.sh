#!/bin/bash
# Harness Maxxing on macOS. Started by install.sh when it runs on a Mac (the same command as on Linux):
#   curl --proto '=https' --tlsv1.2 -fsSL https://get.harness-maxxing.com | bash
# or directly, from a copy of the code:  bash install-macos.sh
#
# Always installed by you, without sudo, in your home folder - like "Install without root" on Linux:
#   ~/.harness-maxxing/app     the code            ~/.harness-maxxing/state   settings, sessions, keys, tools
#   ~/maxxing                  your workspace      ~/.local/bin               the commands (maxxing, uv, claude)
#   ~/Library/LaunchAgents/com.harness-maxxing.server.plist    the service (launchd): starts when you sign in
# It answers on http://127.0.0.1:8787, on this Mac only. Nothing of the system is changed.
# Not on a Mac: the sandbox mode (bubblewrap is Linux only), domain access (HTTPS with Caddy), the server hardening.
#
# Written for the bash 3.2 and the BSD tools of macOS: no associative array, no GNU option.
#
# Settings (environment, all optional): PORT (8787), BRANCH (main), REPO, SOURCE_DIR (a local copy of the code),
#   TOOLS (1 = Node.js, Chromium, Remotion, Scrapling installed now - the default -, 0 = later: maxxing deps update),
#   CLAUDE_TOKEN / ANTHROPIC_API_KEY (stored in the keys of Harness Maxxing).
# Remove: maxxing uninstall
set -euo pipefail

PORT="${PORT:-8787}"
BRANCH="${BRANCH:-main}"
REPO="${REPO:-makushingu/harness-maxxing}"
SOURCE_DIR="${SOURCE_DIR:-}"
TOOLS="${TOOLS:-1}"
CLAUDE_TOKEN="${CLAUDE_TOKEN:-}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"

USER_ROOT="$HOME/.harness-maxxing"
INSTALL_DIR="$USER_ROOT/app"
STATE_DIR="$USER_ROOT/state"
WORKSPACE="$HOME/maxxing"
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/maxxing"
UV="$BIN_DIR/uv"
LABEL=com.harness-maxxing.server
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BREW_PKGS="ffmpeg jq ripgrep imagemagick poppler"
STEP=0
TOTAL=8
T0=$(date +%s)

if [ -t 1 ]; then C_B=$'\033[1m'; C_D=$'\033[2m'; C_G=$'\033[32m'; C_Y=$'\033[33m'; C_R=$'\033[31m'; C_0=$'\033[0m'
else C_B=""; C_D=""; C_G=""; C_Y=""; C_R=""; C_0=""; fi
section() { STEP=$((STEP + 1)); printf '\n%s[%s/%s] %s%s\n' "$C_B" "$STEP" "$TOTAL" "$1" "$C_0"; }
ok()   { printf '      %s✔%s %s\n' "$C_G" "$C_0" "$1"; }
info() { printf '      %s%s%s\n' "$C_D" "$1" "$C_0"; }
warn() { printf '      %s!%s %s\n' "$C_Y" "$C_0" "$1"; }
die()  { printf '\n      %s✘ %s%s\n\n  Fix it, then run the same command again: every step keeps what is already done.\n\n' "$C_R" "$1" "$C_0" >&2; exit 1; }

WORK=$(mktemp -d "${TMPDIR:-/tmp}/hm-install.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
umask 022
PATH_AT_START=$PATH
export PATH="$BIN_DIR:/opt/homebrew/bin:/usr/local/bin:$PATH"

mx() { MAXXING_STATE="$STATE_DIR" "$BIN" "$@"; }
sha_of() { shasum -a 256 "$1" | awk '{print $1}'; }
machine() { case "$(uname -m)" in arm64|aarch64) echo darwin_aarch64 ;; *) echo darwin_x86_64 ;; esac; }

# dep NAME KEY [SUBKEY] - a value of server/maxxing/deps.toml (the pinned versions, URLs and sha256 of what is installed)
dep() {
  local line
  line=$(sed -n "/^\[$1\]/,/^\[/p" "$INSTALL_DIR/server/maxxing/deps.toml" | sed -n "s/^$2 = //p" | sed -n 1p)
  [ -n "$line" ] || return 1
  if [ -n "${3:-}" ]; then
    printf '%s\n' "$line" | sed -n "s/.*[{ ]$3 = \"\([^\"]*\)\".*/\1/p" | grep . || return 1
  else
    printf '%s\n' "$line" | sed -n 's/^"\([^"]*\)".*/\1/p' | grep . || return 1
  fi
}

# dep_fetch NAME DEST - download the macOS build of a component and check its pinned sha256
dep_fetch() {
  local url sum v a
  v=$(dep "$1" version) && url=$(dep "$1" url_darwin) && a=$(dep "$1" arch "$(machine)") && sum=$(dep "$1" sha256 "$(machine)") \
    || { warn "$1: no macOS build pinned in deps.toml"; return 1; }
  url=$(printf '%s' "$url" | sed "s/{version}/$v/g; s/{arch}/$a/g")
  curl -fsSL --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 20 -o "$2" "$url" || { warn "download failed: $url"; return 1; }
  [ "$(sha_of "$2")" = "$sum" ] || { rm -f "$2"; warn "checksum mismatch: $url (expected sha256 $sum)"; return 1; }
}

# ---- 1. this Mac ------------------------------------------------------------------------------
check_mac() {
  section "This Mac"
  [ "$(uname -s)" = Darwin ] || die "this installer is for macOS (on Linux: install.sh)"
  [ "$(id -u)" != 0 ] || die "run it as yourself, without sudo: on a Mac Harness Maxxing lives in your home folder"
  local v major
  v=$(sw_vers -productVersion 2>/dev/null || echo 0)
  major=${v%%.*}
  [ "$major" -ge 13 ] 2>/dev/null || die "macOS 13 (Ventura) or later is needed - this Mac runs $v"
  ok "macOS $v, $(uname -m), installing for $(id -un)"
  case "$PORT" in ''|*[!0-9]*) die "PORT must be a number" ;; esac
  if ! xcode-select -p >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
    xcode-select --install >/dev/null 2>&1 || true
    die "the Command Line Tools of Apple are needed (git): a window just opened to install them - accept it, wait for the end, then run this again"
  fi
  ok "git $(git --version | awk '{print $3}')"
  if command -v brew >/dev/null 2>&1; then
    local missing="" p
    for p in $BREW_PKGS; do brew list --formula "$p" >/dev/null 2>&1 || missing="$missing $p"; done
    if [ -n "$missing" ]; then
      info "installing with Homebrew:$missing"
      # shellcheck disable=SC2086
      if brew install -q $missing >"$WORK/brew.log" 2>&1; then ok "tools of the system installed:$missing"
      else tail -n 5 "$WORK/brew.log" | sed 's/^/      | /'; warn "some could not be installed - later: brew install$missing"; fi
    else
      ok "tools of the system already here ($BREW_PKGS)"
    fi
  else
    warn "Homebrew is not installed: videos, PDFs and voice messages need ffmpeg, jq, ripgrep, imagemagick and poppler"
    info "install Homebrew (https://brew.sh), then: brew install $BREW_PKGS"
  fi
}

# ---- 2. the code ------------------------------------------------------------------------------
fetch_code() {
  section "Harness Maxxing code"
  mkdir -p "$USER_ROOT"; chmod 700 "$USER_ROOT"
  local here=""
  [ -z "${BASH_SOURCE[0]:-}" ] || here=$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)
  [ -n "$SOURCE_DIR" ] || { [ -n "$here" ] && [ -f "$here/server/pyproject.toml" ] && [ "$here" != "$INSTALL_DIR" ] && SOURCE_DIR=$here; } || true
  if [ -n "$SOURCE_DIR" ]; then
    [ -f "$SOURCE_DIR/server/pyproject.toml" ] || die "$SOURCE_DIR is not a copy of Harness Maxxing (no server/pyproject.toml)"
    mkdir -p "$INSTALL_DIR"
    rsync -a --delete --exclude .git --exclude node_modules --exclude .venv --exclude __pycache__ "$SOURCE_DIR/" "$INSTALL_DIR/" \
      || die "could not copy $SOURCE_DIR"
    ok "copied from $SOURCE_DIR (no remote: updates come from a newer copy)"
  elif [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" fetch --quiet origin "$BRANCH" || die "git fetch failed (network?)"
    if [ -n "$(git -C "$INSTALL_DIR" status --porcelain 2>/dev/null)" ]; then
      warn "the code has local changes: kept as it is (maxxing update carries them over)"
    else
      git -C "$INSTALL_DIR" checkout --quiet -B "$BRANCH" "origin/$BRANCH" || die "could not move the code to $BRANCH"
      ok "up to date on $BRANCH ($(git -C "$INSTALL_DIR" rev-parse --short HEAD))"
    fi
  else
    [ ! -e "$INSTALL_DIR" ] || [ -z "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ] || die "$INSTALL_DIR exists and is not an installation: move it away"
    git clone --quiet --filter=blob:none --branch "$BRANCH" "https://github.com/$REPO.git" "$INSTALL_DIR" \
      || die "could not download the code (https://github.com/$REPO, branch $BRANCH)"
    ok "downloaded into $INSTALL_DIR ($BRANCH, $(git -C "$INSTALL_DIR" rev-parse --short HEAD))"
  fi
  [ -f "$INSTALL_DIR/server/maxxing/deps.toml" ] || die "deps.toml not found in $INSTALL_DIR"
}

# ---- 3. uv, Claude Code, Python ---------------------------------------------------------------
install_uv() {
  section "Python toolchain (uv)"
  local want have
  want=$(dep uv version) || die "uv is not pinned in deps.toml"
  have=$("$UV" --version 2>/dev/null | awk '{print $2}' || true)
  if [ "$have" != "$want" ]; then
    dep_fetch uv "$WORK/uv.tar.gz" || die "uv download failed or its sha256 does not match deps.toml"
    mkdir -p "$WORK/uv" "$BIN_DIR"
    tar -xzf "$WORK/uv.tar.gz" -C "$WORK/uv" --strip-components=1 || die "uv archive could not be unpacked"
    install -m 755 "$WORK/uv/uv" "$WORK/uv/uvx" "$BIN_DIR/" || die "uv installation failed"
  fi
  ok "uv $("$UV" --version | awk '{print $2}') in $BIN_DIR (sha256 checked)"
}

install_claude() {
  section "Claude Code"
  if ! command -v claude >/dev/null 2>&1; then
    local v
    v=$(dep claude version) || die "Claude Code is not pinned in deps.toml"
    dep_fetch claude "$WORK/claude.bin" || die "Claude Code download failed or its sha256 does not match deps.toml"
    chmod 700 "$WORK/claude.bin"
    (cd "$WORK" && "$WORK/claude.bin" install "$v") >"$WORK/claude.log" 2>&1 \
      || { tail -n 8 "$WORK/claude.log" | sed 's/^/      | /'; die "Claude Code installation failed"; }
    rm -f "$WORK/claude.bin"
    mkdir -p "$STATE_DIR"; chmod 700 "$STATE_DIR"
    grep -qx "claude installed" "$STATE_DIR/install-manifest" 2>/dev/null || echo "claude installed" >> "$STATE_DIR/install-manifest"
  fi
  command -v claude >/dev/null 2>&1 || die "claude not found after installation (expected in $BIN_DIR)"
  ok "Claude Code $(claude --version 2>/dev/null | head -n 1)"
}

setup_python() {
  section "Python environment"
  mkdir -p "$STATE_DIR/tools/python" "$STATE_DIR/logs"; chmod 700 "$STATE_DIR" "$STATE_DIR/logs"
  (cd "$INSTALL_DIR/server" && UV_PYTHON_INSTALL_DIR="$STATE_DIR/tools/python" UV_PYTHON_PREFERENCE=only-managed \
     "$UV" sync --frozen --no-dev --quiet --python "$(dep python version || echo 3.12)") >"$WORK/uv-sync.log" 2>&1 \
    || { tail -n 12 "$WORK/uv-sync.log" | sed 's/^/      | /'; die "uv sync failed in $INSTALL_DIR/server"; }
  local exe="$INSTALL_DIR/server/.venv/bin/maxxing"
  [ -x "$exe" ] || die "$exe missing after uv sync"
  mkdir -p "$BIN_DIR"
  rm -f "$BIN"
  printf '#!/bin/bash\n# Harness Maxxing command (its state folder is in your home)\nexport MAXXING_STATE=%q\nexec %q "$@"\n' "$STATE_DIR" "$exe" > "$BIN"
  chmod 755 "$BIN"
  ok "$(mx --version 2>/dev/null || echo maxxing) -> $BIN"
}

# ---- 4. workspace, settings -------------------------------------------------------------------
init_state() {
  section "Workspace, skills and jobs"
  local log="$STATE_DIR/logs/install-init.log"
  rm -f "$log"
  mx init --workspace "$WORKSPACE" --port "$PORT" --bind 127.0.0.1 --public-url "" --system-clock keep > "$log" 2>&1 \
    || { cat "$log"; die "maxxing init failed"; }
  grep -E '^ *[✔!✘–]' "$log" | sed -E 's/^ *//; s/^/      /' || true
  if [ -n "$CLAUDE_TOKEN" ]; then
    printf '%s' "$CLAUDE_TOKEN" | mx init --quiet --no-crons --secret-from-stdin claude_oauth_token && ok "Claude token stored"
  fi
  if [ -n "$ANTHROPIC_API_KEY" ]; then
    printf '%s' "$ANTHROPIC_API_KEY" | mx init --quiet --no-crons --secret-from-stdin anthropic_api_key && ok "Anthropic API key stored"
  fi
}

# ---- 5. the service (launchd) -----------------------------------------------------------------
plist_text() {
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$BIN</string><string>serve</string></array>
  <key>WorkingDirectory</key><string>$WORKSPACE</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MAXXING_STATE</key><string>$STATE_DIR</string>
    <key>HOME</key><string>$HOME</string>
    <key>PATH</key><string>$BIN_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>LANG</key><string>en_US.UTF-8</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>3</integer>
  <key>AbandonProcessGroup</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$STATE_DIR/logs/server.log</string>
  <key>StandardErrorPath</key><string>$STATE_DIR/logs/server.log</string>
</dict>
</plist>
EOF
}

setup_service() {
  section "Service"
  local domain target i
  domain="gui/$(id -u)"; target="$domain/$LABEL"
  mkdir -p "$(dirname "$PLIST")"
  plist_text > "$PLIST"
  chmod 644 "$PLIST"
  plutil -lint "$PLIST" >/dev/null || die "$PLIST is not a valid property list"
  launchctl bootout "$target" >/dev/null 2>&1 || true           # an earlier run: stopped, then started from the new file
  for i in 1 2 3 4 5; do launchctl print "$target" >/dev/null 2>&1 || break; sleep 1; done
  launchctl bootstrap "$domain" "$PLIST" 2>"$WORK/launchctl.log" \
    || { sed 's/^/      | /' "$WORK/launchctl.log"; die "launchd refused the service (launchctl bootstrap $domain $PLIST) - are you signed in to this Mac's desktop?"; }
  launchctl enable "$target" >/dev/null 2>&1 || true
  for i in $(seq 1 90); do
    curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/api/auth/state" 2>/dev/null && break
    sleep 1
  done
  curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/api/auth/state" 2>/dev/null \
    || { tail -n 15 "$STATE_DIR/logs/server.log" 2>/dev/null | sed 's/^/      | /'; die "the server does not answer on 127.0.0.1:$PORT (log: $STATE_DIR/logs/server.log)"; }
  ok "running on 127.0.0.1:$PORT (launchd agent $LABEL): starts when you sign in to this Mac"
}

# ---- 6. tools ---------------------------------------------------------------------------------
install_tools() {
  section "Tools (Node.js, Chromium, Remotion, Scrapling)"
  if [ "$TOOLS" = 0 ]; then info "skipped (TOOLS=0) - later: maxxing deps update"; return 0; fi
  local log="$STATE_DIR/logs/install-tools.log"
  info "a few minutes..."
  if mx deps update >"$log" 2>&1; then
    ok "tools ready: $(mx deps list 2>/dev/null | awk '$2 ~ /^(node|chromium|remotion|scrapling)$/ {printf "%s %s · ", $2, $3}' | sed 's/ · $//')"
  else
    grep -E 'failed' "$log" | tail -n 5 | sed 's/^/      | /'
    warn "some tools could not be installed - re-run: maxxing deps update (log: $log)"
  fi
}

banner() {
  local link took
  took=$(( $(date +%s) - T0 ))
  link=$(mx setup-link 2>/dev/null | grep -Eo 'https?://[^ ]+' | head -n 1 || true)
  rm -f "$STATE_DIR/logs/install-init.log"
  printf '\n  %s✔  Harness Maxxing is installed%s  %s(%s s)%s\n\n' "$C_G$C_B" "$C_0" "$C_D" "$took" "$C_0"
  if [ -n "$link" ]; then
    printf '  Open this link in the browser of this Mac to create your password:\n\n    %s%s%s\n\n' "$C_B" "$link" "$C_0"
    printf '  %s! One-time link, valid 1 hour. Expired or lost? run: maxxing setup-link%s\n\n' "$C_Y" "$C_0"
  else
    printf '  Open http://127.0.0.1:%s in the browser of this Mac.\n\n' "$PORT"
  fi
  case ":$PATH_AT_START:" in *":$BIN_DIR:"*) ;; *)
    printf '  The commands are in %s, which is not in your PATH yet:\n    echo '"'"'export PATH="$HOME/.local/bin:$PATH"'"'"' >> ~/.zshrc && exec zsh\n\n' "$BIN_DIR" ;;
  esac
  printf '  maxxing doctor   check everything      maxxing update   update      maxxing uninstall   remove\n\n'
}

[ "${MAXXING_INSTALL_LIB:-0}" != 1 ] || return 0      # tests: the functions only
printf '\n  %sHarness Maxxing%s - installation on macOS\n' "$C_B" "$C_0"
check_mac
fetch_code
install_uv
install_claude
setup_python
init_state
setup_service
install_tools
banner
