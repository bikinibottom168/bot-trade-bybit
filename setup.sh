#!/usr/bin/env bash
# ===========================================================================
#  setup.sh — ติดตั้ง / รันเบื้องหลัง / หยุด / รีสตาร์ท บอทเทรด Bybit
#
#    ./setup.sh            ติดตั้ง + ตั้งค่า .env (ถ้ายังไม่มี) + รันเบื้องหลัง
#    ./setup.sh stop       หยุดการทำงาน
#    ./setup.sh restart    รีสตาร์ท
#    ./setup.sh status     ดูสถานะ
#    ./setup.sh logs       ดู log สด (Ctrl+C เพื่อออก)
# ===========================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

PY_BIN="$APP_DIR/.venv/bin/python"
SERVICE="bot-trade"
UNIT="/etc/systemd/system/${SERVICE}.service"
PID_FILE="$APP_DIR/${SERVICE}.pid"
LOG_FILE="$APP_DIR/${SERVICE}.log"

c_ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m%s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m%s\033[0m\n' "$*" >&2; }
step()   { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# systemd ใช้ได้เมื่อ: มี systemctl + บูตด้วย systemd + เป็น root
use_systemd() {
  command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ] && [ "$(id -u)" -eq 0 ]
}

env_get() {  # env_get KEY -> ค่าใน .env (ว่างถ้าไม่มี)
  [ -f .env ] || return 0
  sed -n "s/^$1=//p" .env | tail -n 1
}

seed_env() {  # สร้าง .env จาก .env.example โดยล้างค่าตัวอย่างออก
  [ -f .env ] && return 0
  sed -E 's/^(BYBIT_API_[A-Z_]*)=.*/\1=/' .env.example > .env
  chmod 600 .env
}

env_set() {  # env_set KEY VALUE (แทนที่ถ้ามีอยู่แล้ว)
  local key="$1" val="$2"
  touch .env
  if grep -q "^${key}=" .env 2>/dev/null; then
    grep -v "^${key}=" .env > .env.tmp && mv .env.tmp .env
  fi
  printf '%s=%s\n' "$key" "$val" >> .env
}

# ---------------------------------------------------------------- ติดตั้ง --
install_deps() {
  step "ตรวจสอบ Python"
  local py="${PYTHON:-python3}"
  command -v "$py" >/dev/null 2>&1 || { c_err "ไม่พบ $py — ติดตั้ง Python 3 ก่อน"; exit 1; }

  # Debian/Ubuntu ต้องมี python3-venv ก่อนถึงจะสร้าง venv ได้ (PEP 668)
  if ! "$py" -m venv --help >/dev/null 2>&1; then
    step "ติดตั้ง python3-venv"
    if command -v apt-get >/dev/null 2>&1; then
      ${SUDO:-} apt-get update -qq
      ${SUDO:-} apt-get install -y python3-venv python3-full
    else
      c_err "ไม่พบโมดูล venv — ติดตั้งเองก่อนแล้วรัน ./setup.sh ใหม่"
      exit 1
    fi
  fi

  if [ ! -x "$PY_BIN" ]; then
    step "สร้าง virtual environment ที่ .venv"
    "$py" -m venv .venv
  fi

  step "ติดตั้งไลบรารีจาก requirements.txt"
  "$PY_BIN" -m pip install --upgrade pip -q
  "$PY_BIN" -m pip install -r requirements.txt -q
  c_ok "ไลบรารีพร้อมแล้ว"
}

# ----------------------------------------------------------- ฟอร์ม .env --
setup_env() {
  # มี .env และมีคีย์ Bybit แล้ว -> ข้าม
  if [ -f .env ]; then
    local k
    k="$(env_get BYBIT_API_KEY_TESTNET)$(env_get BYBIT_API_KEY_LIVE)$(env_get BYBIT_API_KEY)"
    if [ -n "$k" ]; then
      c_ok "พบไฟล์ .env และตั้งค่า API key ไว้แล้ว -> ข้ามขั้นตอนตั้งค่า"
      return 0
    fi
  fi

  if [ ! -t 0 ]; then
    c_warn "ยังไม่ได้ตั้งค่า .env แต่รันแบบไม่มีหน้าจอ -> ข้ามฟอร์ม"
    c_warn "ตั้งค่า API key ได้ทีหลังที่หน้าเว็บ แท็บ 'ตั้งค่า'"
    seed_env
    return 0
  fi

  cat <<'FORM'

┌──────────────────────────────────────────────────────────┐
│  ตั้งค่าครั้งแรก — ใส่ API key ของ Bybit                 │
│                                                          │
│  Testnet (เงินปลอม แนะนำให้เริ่มที่นี่):                 │
│      https://testnet.bybit.com -> API Management         │
│  Mainnet (เงินจริง):                                     │
│      https://www.bybit.com -> API Management             │
│                                                          │
│  * เปิดสิทธิ์ "Trade" เท่านั้น อย่าเปิด Withdraw เด็ดขาด │
│  * กด Enter เพื่อข้าม แล้วไปกรอกที่หน้าเว็บทีหลังก็ได้   │
└──────────────────────────────────────────────────────────┘

FORM

  local net key_field sec_field testnet_val
  read -rp "ใช้ Testnet (เงินปลอม) ไหม? [Y/n]: " net || net=""
  case "${net:-y}" in
    [Nn]*) net="live";  key_field="BYBIT_API_KEY_LIVE";    sec_field="BYBIT_API_SECRET_LIVE";    testnet_val="false" ;;
    *)     net="test";  key_field="BYBIT_API_KEY_TESTNET"; sec_field="BYBIT_API_SECRET_TESTNET"; testnet_val="true"  ;;
  esac

  local api_key api_secret
  read -rp "BYBIT_API_KEY    : " api_key || api_key=""
  read -rsp "BYBIT_API_SECRET : " api_secret || api_secret=""; echo

  # รหัสเข้าหน้า Dashboard (บังคับตั้งถ้าจะเปิดออกเน็ต)
  local dash_pass="" dash_pass2="" tries=0
  while [ "$tries" -lt 5 ]; do
    tries=$((tries + 1))
    read -rsp "รหัสผ่านเข้าหน้า Dashboard (user: admin): " dash_pass || { dash_pass=""; break; }; echo
    [ -z "$dash_pass" ] && { c_warn "ต้องตั้งรหัส — หน้านี้คุมบอทเทรดและเห็น API key ได้"; continue; }
    read -rsp "ยืนยันรหัสอีกครั้ง                      : " dash_pass2 || { dash_pass=""; break; }; echo
    [ "$dash_pass" = "$dash_pass2" ] && break
    c_warn "รหัสไม่ตรงกัน ลองใหม่"
    dash_pass=""
  done
  if [ -z "$dash_pass" ]; then
    dash_pass="$(head -c 12 /dev/urandom | base64 | tr -d '/+=' | head -c 12)"
    c_warn "ตั้งรหัสสุ่มให้แทน: $dash_pass  (จดไว้ หรือแก้ DASH_PASS ใน .env ทีหลัง)"
  fi

  local expose host
  read -rp "เปิดให้เข้าจากภายนอกด้วย IP เซิร์ฟเวอร์ไหม? (VPS ตอบ y) [y/N]: " expose || expose=""
  case "${expose:-n}" in [Yy]*) host="0.0.0.0" ;; *) host="127.0.0.1" ;; esac

  local port
  read -rp "พอร์ต [8000]: " port || port=""
  port="${port:-8000}"

  seed_env
  [ -n "$api_key" ]    && env_set "$key_field" "$api_key"
  [ -n "$api_secret" ] && env_set "$sec_field" "$api_secret"
  env_set TESTNET   "$testnet_val"
  env_set DRY_RUN   "true"
  env_set HOST      "$host"
  env_set PORT      "$port"
  env_set DASH_USER "admin"
  env_set DASH_PASS "$dash_pass"
  chmod 600 .env

  c_ok "บันทึกลง .env แล้ว (DRY_RUN=true — จำลองอย่างเดียว ยังไม่ส่งคำสั่งจริง)"
  [ -z "$api_key" ] && c_warn "ยังไม่ได้ใส่ API key — ไปกรอกที่หน้าเว็บ แท็บ 'ตั้งค่า' ได้"
  return 0
}

# ------------------------------------------------------------ start/stop --
write_unit() {
  cat > "$UNIT" <<UNITEOF
[Unit]
Description=Bybit Trading Bot Dashboard
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$PY_BIN $APP_DIR/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNITEOF
  systemctl daemon-reload
}

nohup_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

do_start() {
  step "เริ่มบอทแบบเบื้องหลัง"
  if use_systemd; then
    write_unit
    systemctl enable "$SERVICE" >/dev/null 2>&1 || true
    systemctl restart "$SERVICE"
    c_ok "รันด้วย systemd แล้ว (ปิด SSH หรือ reboot ก็ยังทำงานต่อ)"
  else
    if nohup_running; then
      c_warn "บอททำงานอยู่แล้ว (PID $(cat "$PID_FILE")) — ใช้ ./setup.sh restart ถ้าต้องการรีสตาร์ท"
      return 0
    fi
    nohup "$PY_BIN" app.py >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    c_ok "รันเบื้องหลังแล้ว (PID $(cat "$PID_FILE")) — log ที่ $LOG_FILE"
    c_warn "โหมดนี้ไม่รอด reboot (ไม่มี systemd หรือไม่ได้รันเป็น root)"
  fi
}

do_stop() {
  step "หยุดบอท"
  local stopped=0
  if use_systemd && systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE}.service"; then
    systemctl stop "$SERVICE" 2>/dev/null || true
    systemctl disable "$SERVICE" >/dev/null 2>&1 || true
    stopped=1
  fi
  if nohup_running; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
    stopped=1
  fi
  [ -f "$PID_FILE" ] && rm -f "$PID_FILE"
  if [ "$stopped" -eq 1 ]; then c_ok "หยุดแล้ว"; else c_warn "ไม่พบบอทที่กำลังทำงาน"; fi
  return 0
}

do_status() {
  if use_systemd && systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE}.service"; then
    systemctl status "$SERVICE" --no-pager || true
  elif nohup_running; then
    c_ok "กำลังทำงาน (PID $(cat "$PID_FILE"))"
  else
    c_warn "ไม่ได้ทำงานอยู่"
  fi
  local host port
  host="$(env_get HOST)"; port="$(env_get PORT)"
  echo
  echo "หน้าเว็บ: http://${host:-127.0.0.1}:${port:-8000}  (user: $(env_get DASH_USER || echo admin))"
}

do_logs() {
  if use_systemd && systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE}.service"; then
    journalctl -u "$SERVICE" -f -n 50
  else
    touch "$LOG_FILE"; tail -f -n 50 "$LOG_FILE"
  fi
}

show_url() {
  local host port
  host="$(env_get HOST)"; port="$(env_get PORT)"
  host="${host:-127.0.0.1}"; port="${port:-8000}"
  echo
  if [ "$host" = "0.0.0.0" ]; then
    local ip
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    c_ok "เปิดเบราว์เซอร์ที่  http://${ip:-<IP เซิร์ฟเวอร์>}:${port}"
    c_warn "อย่าลืมเปิดพอร์ตที่ firewall:  sudo ufw allow ${port}/tcp"
    c_warn "และเปิด TCP ${port} ที่ Vultr Firewall ใน portal ด้วย (ถ้าเปิดใช้อยู่)"
  else
    c_ok "เปิดเบราว์เซอร์ที่  http://127.0.0.1:${port}"
  fi
  echo
  echo "คำสั่งอื่น:  ./setup.sh stop | restart | status | logs"
}

# ------------------------------------------------------------------ main --
case "${1:-install}" in
  install|"")
    install_deps
    setup_env
    do_start
    show_url
    ;;
  start)   do_start; show_url ;;
  stop)    do_stop ;;
  restart) do_stop; do_start; show_url ;;
  status)  do_status ;;
  logs)    do_logs ;;
  *)
    c_err "ไม่รู้จักคำสั่ง: $1"
    echo "ใช้: ./setup.sh [install|start|stop|restart|status|logs]"
    exit 1
    ;;
esac
