"""
config.py
---------
โหลด/บันทึกค่าตั้งทั้งหมดจากไฟล์ .env (แก้ผ่านหน้า GUI ได้)
API key เก็บในเครื่องคุณเท่านั้น ไม่ถูกส่งออกไปไหน
"""

import os

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except Exception:
    pass


def _get(key, default=""):
    return os.getenv(key, default)


def _get_bool(key, default=False):
    return os.getenv(key, str(default)).strip().lower() in ("true", "1", "yes", "on")


def _get_float(key, default):
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return float(default)


def _get_int(key, default):
    try:
        return int(float(os.getenv(key, default)))
    except (TypeError, ValueError):
        return int(default)


# ==========================================================================
#  โครงสร้างค่าตั้ง (ใช้สร้างฟอร์มใน GUI ด้วย)
#  (env_key, ประเภท, ค่าเริ่มต้น, ป้ายภาษาไทย, กลุ่ม)
# ==========================================================================
SETTINGS_SCHEMA = [
    # --- Bybit (แยก key 2 ชุด บอทเลือกใช้ตามสวิตช์ Testnet) ---
    ("BYBIT_API_KEY_TESTNET",    "secret", "", "Testnet API Key (จาก testnet.bybit.com)",    "bybit"),
    ("BYBIT_API_SECRET_TESTNET", "secret", "", "Testnet API Secret",                          "bybit"),
    ("BYBIT_API_KEY_LIVE",       "secret", "", "Mainnet/จริง API Key (จาก bybit.com)",        "bybit"),
    ("BYBIT_API_SECRET_LIVE",    "secret", "", "Mainnet/จริง API Secret",                     "bybit"),
    ("TESTNET",          "bool",   True,   "ใช้ Testnet (เงินปลอม)",    "bybit"),
    ("DRY_RUN",          "bool",   True,   "DRY_RUN (จำลอง ไม่ส่งจริง)", "bybit"),

    # --- กลยุทธ์ ---
    ("SYMBOLS",          "text",   "BTC/USDT:USDT,ETH/USDT:USDT,XRP/USDT:USDT,BNB/USDT:USDT",
                                            "คู่เหรียญ (คั่นด้วย ,)",    "strategy"),
    ("TIMEFRAME",        "text",   "5m",   "Timeframe",                "strategy"),
    ("LEVERAGE",         "int",    10,     "Leverage (เท่า)",           "strategy"),
    ("TAKE_PROFIT_PCT",  "float",  0.2,    "Take Profit (%)",          "strategy"),
    ("USE_STOP_LOSS",    "bool",   True,   "เปิด Stop Loss",            "strategy"),
    ("STOP_LOSS_PCT",    "float",  1.0,    "Stop Loss (%)",            "strategy"),
    ("ORDER_USDT",       "float",  50.0,   "มาร์จิ้นต่อไม้ USDT (ขนาดจริง = ค่านี้ × leverage)", "strategy"),
    ("RSI_PERIOD",       "int",    14,     "RSI Period",               "strategy"),
    ("RSI_BUY_BELOW",    "float",  40.0,   "ซื้อเมื่อ RSI ต่ำกว่า",       "strategy"),
    ("RSI_SELL_ABOVE",   "float",  60.0,   "ขายเมื่อ RSI สูงกว่า",        "strategy"),
    ("MAX_OPEN_POSITIONS","int",   4,      "จำนวนเหรียญที่เปิดพร้อมกันสูงสุด",   "strategy"),
    ("MAX_ENTRIES_PER_SYMBOL","int",1,     "ไม้สะสมต่อเหรียญ (>1 = ถัวทิศเดียว)", "strategy"),
    ("DCA_MIN_LOSS_PCT", "float", 1.5,     "ถัวเมื่อไม้ติดลบ ≥ (%)",     "strategy"),
    ("DCA_ATR_PERIOD",   "int",   14,      "ATR period (คุมระยะห่างถัว)", "strategy"),
    ("DCA_ATR_MULT",     "float", 1.0,     "ระยะห่างถัวขั้นต่ำ = ATR ×",  "strategy"),
    ("MAX_DAILY_LOSS_USDT","float",20.0,   "เพดานขาดทุนต่อวัน (USDT)",  "strategy"),
    ("POLL_SECONDS",     "int",    15,     "ตรวจสัญญาณทุก (วินาที)",     "strategy"),

    # --- Telegram ---
    ("TELEGRAM_TOKEN",   "secret", "",     "Telegram Bot Token",       "telegram"),
    ("TELEGRAM_CHAT_ID", "text",   "",     "Telegram Chat ID",         "telegram"),
    ("TG_ALERT_TRADES",  "bool",   True,   "แจ้งเตือนทุกไม้ (เรียลไทม์)", "telegram"),
    ("DAILY_SUMMARY_TIME","text",  "21:00","เวลาส่งสรุปรายวัน (HH:MM)", "telegram"),
]


def load():
    """คืน dict ของค่าตั้งปัจจุบัน (อ่านสดจาก env ทุกครั้ง)"""
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH, override=True)
    except Exception:
        pass

    s = {}
    for key, typ, default, _label, _group in SETTINGS_SCHEMA:
        if typ == "bool":
            s[key] = _get_bool(key, default)
        elif typ == "float":
            s[key] = _get_float(key, default)
        elif typ == "int":
            s[key] = _get_int(key, default)
        else:
            s[key] = _get(key, default)

    # เลือก key/secret ที่ใช้งานจริงตามสวิตช์ Testnet
    if s["TESTNET"]:
        key, sec = s["BYBIT_API_KEY_TESTNET"], s["BYBIT_API_SECRET_TESTNET"]
    else:
        key, sec = s["BYBIT_API_KEY_LIVE"], s["BYBIT_API_SECRET_LIVE"]
    # เผื่อผู้ใช้เดิมที่ตั้ง BYBIT_API_KEY ไว้ในไฟล์ .env รุ่นก่อน
    if not key:
        key = _get("BYBIT_API_KEY", "")
    if not sec:
        sec = _get("BYBIT_API_SECRET", "")
    s["BYBIT_API_KEY"] = key
    s["BYBIT_API_SECRET"] = sec
    return s


def save(values: dict):
    """เขียนค่าตั้งกลับไฟล์ .env (คงค่าเดิมที่ไม่ได้ส่งมา)"""
    current = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    current[k.strip()] = v.strip()

    for key, _typ, _default, _label, _group in SETTINGS_SCHEMA:
        if key in values and values[key] is not None:
            val = values[key]
            if isinstance(val, bool):
                val = "true" if val else "false"
            current[key] = str(val)

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("# ค่าตั้งบอทเทรด (แก้ผ่านหน้า GUI หรือแก้ไฟล์นี้ก็ได้)\n")
        for k, v in current.items():
            f.write(f"{k}={v}\n")

    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH, override=True)
    except Exception:
        pass


def symbols_list(settings=None):
    s = settings or load()
    return [x.strip() for x in str(s["SYMBOLS"]).split(",") if x.strip()]


# ==========================================================================
#  ค่าคงที่ระดับโมดูล (เผื่อสคริปต์เก่า เช่น backtest.py เรียกใช้)
# ==========================================================================
_s = load()
TESTNET = _s["TESTNET"]
DRY_RUN = _s["DRY_RUN"]
API_KEY = _s["BYBIT_API_KEY"]
API_SECRET = _s["BYBIT_API_SECRET"]
SYMBOLS = symbols_list(_s)
TIMEFRAME = _s["TIMEFRAME"]
LEVERAGE = _s["LEVERAGE"]
TAKE_PROFIT_PCT = _s["TAKE_PROFIT_PCT"] / 100.0
STOP_LOSS_PCT = _s["STOP_LOSS_PCT"] / 100.0
USE_STOP_LOSS = _s["USE_STOP_LOSS"]
ORDER_USDT = _s["ORDER_USDT"]
RSI_PERIOD = _s["RSI_PERIOD"]
RSI_BUY_BELOW = _s["RSI_BUY_BELOW"]
RSI_SELL_ABOVE = _s["RSI_SELL_ABOVE"]
MAX_OPEN_POSITIONS = _s["MAX_OPEN_POSITIONS"]
MAX_DAILY_LOSS_USDT = _s["MAX_DAILY_LOSS_USDT"]
POLL_SECONDS = _s["POLL_SECONDS"]
