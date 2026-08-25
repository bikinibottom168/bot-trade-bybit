"""
app.py
------
Web Dashboard (Flask) สำหรับบอทเทรด Bybit
- ตั้งค่า Bybit API key / Telegram / กลยุทธ์ ผ่านหน้าเว็บ
- ปุ่ม Start / Stop บอท และปุ่มทดสอบการเชื่อมต่อ
- ตาราง log เทรดสด ๆ + กราฟกำไรสะสม + สรุปรายวัน

รัน:  python app.py   แล้วเปิดเบราว์เซอร์ http://127.0.0.1:5000
"""

import os
import hmac

from flask import (Flask, render_template, request, jsonify, send_file,
                   redirect, url_for, Response)

import config
import trade_logger
import notifier
from bot import engine

app = Flask(__name__)

# ---- ระบบล็อกอินหน้า Dashboard (HTTP Basic Auth) ----
# เปลี่ยนรหัส/เกณฑ์ได้ด้วย env DASH_USER / DASH_PASS / DASH_MAX_FAILS
DASH_USER = os.getenv("DASH_USER", "admin")
DASH_PASS = os.getenv("DASH_PASS", "IIceza0251ZA**##")
MAX_FAILS = int(os.getenv("DASH_MAX_FAILS", "3"))

_fail_counts = {}        # ip -> จำนวนครั้งที่ใส่รหัสผิด
_blocked_ips = set()     # ip ที่ถูกบล็อก (จนกว่าจะรีสตาร์ทโปรแกรม)
_notified_ips = set()    # ip ที่แจ้งเตือนล็อกอินสำเร็จไปแล้ว (กันแจ้งซ้ำทุก request)


def _is_loopback(ip):
    return ip in ("127.0.0.1", "::1", "localhost", None)


def _tg_notify(text):
    try:
        s = config.load()
        notifier.send(s.get("TELEGRAM_TOKEN", ""), s.get("TELEGRAM_CHAT_ID", ""), text)
    except Exception:
        pass


@app.before_request
def _require_login():
    ip = request.remote_addr or "?"

    # ถูกบล็อกอยู่ -> ปฏิเสธทันที (ยกเว้นเครื่องตัวเอง กันล็อกเอาต์ตัวเอง)
    if ip in _blocked_ips and not _is_loopback(ip):
        return Response("IP ของคุณถูกบล็อกเนื่องจากใส่รหัสผิดหลายครั้ง", 403)

    auth = request.authorization

    # ยังไม่ส่งรหัสมา -> ขอให้ล็อกอิน (ไม่นับเป็นครั้งที่ผิด)
    if auth is None:
        return Response("ต้องล็อกอินก่อนใช้งาน", 401,
                        {"WWW-Authenticate": 'Basic realm="Bybit Trading Bot"'})

    ok = (hmac.compare_digest(auth.username or "", DASH_USER)
          and hmac.compare_digest(auth.password or "", DASH_PASS))

    if ok:
        _fail_counts.pop(ip, None)
        # แจ้งเตือน Telegram ครั้งแรกที่ล็อกอินสำเร็จจาก IP นี้
        if ip not in _notified_ips:
            _notified_ips.add(ip)
            _tg_notify(f"✅ มีการล็อกอิน Dashboard สำเร็จ\nผู้ใช้: {DASH_USER}\nIP: {ip}")
        return  # ผ่าน

    # ใส่รหัสผิด -> นับครั้ง และบล็อกถ้าเกินเกณฑ์
    n = _fail_counts.get(ip, 0) + 1
    _fail_counts[ip] = n
    if n >= MAX_FAILS and not _is_loopback(ip):
        _blocked_ips.add(ip)
        _tg_notify(f"⛔ บล็อก IP {ip}\nใส่รหัส Dashboard ผิด {n} ครั้ง")
        return Response("IP ของคุณถูกบล็อกเนื่องจากใส่รหัสผิดหลายครั้ง", 403)
    _tg_notify(f"⚠️ ใส่รหัส Dashboard ผิด ({n}/{MAX_FAILS})\nIP: {ip}")
    return Response("รหัสไม่ถูกต้อง", 401,
                    {"WWW-Authenticate": 'Basic realm="Bybit Trading Bot"'})


@app.route("/")
def index():
    settings = config.load()
    # จัดกลุ่ม field ตาม schema เพื่อ render ฟอร์ม
    groups = {"bybit": [], "strategy": [], "telegram": []}
    for key, typ, default, label, group in config.SETTINGS_SCHEMA:
        groups[group].append({
            "key": key, "type": typ, "label": label, "value": settings.get(key, default),
        })
    return render_template("index.html", groups=groups)


@app.route("/save", methods=["POST"])
def save():
    values = {}
    for key, typ, default, label, group in config.SETTINGS_SCHEMA:
        if typ == "bool":
            values[key] = (request.form.get(key) == "on")
        else:
            v = request.form.get(key, "")
            # ถ้าเว้นว่างช่อง secret ไว้ ให้คงค่าเดิม
            if typ == "secret" and v == "":
                continue
            values[key] = v
    config.save(values)
    return redirect(url_for("index"))


@app.route("/api/start", methods=["POST"])
def api_start():
    ok = engine.start()
    return jsonify({"ok": ok, "running": engine.running})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    engine.stop()
    return jsonify({"ok": True, "running": engine.running})


@app.route("/api/test-bybit", methods=["POST"])
def api_test_bybit():
    import ccxt
    s = config.load()
    try:
        ex = ccxt.bybit({
            "apiKey": s["BYBIT_API_KEY"], "secret": s["BYBIT_API_SECRET"],
            "enableRateLimit": True, "options": {"defaultType": "swap"},
        })
        if s["TESTNET"]:
            ex.set_sandbox_mode(True)
        if s["BYBIT_API_KEY"]:
            bal = ex.fetch_balance()
            usdt = bal.get("USDT", {}).get("total", 0)
            return jsonify({"ok": True, "msg": f"เชื่อมต่อสำเร็จ ยอด USDT: {usdt}"})
        else:
            ex.fetch_ticker(config.symbols_list(s)[0])
            return jsonify({"ok": True, "msg": "เชื่อมต่อราคาได้ (ยังไม่ได้ใส่ API key)"})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/api/test-telegram", methods=["POST"])
def api_test_telegram():
    s = config.load()
    ok, detail = notifier.test_connection(s["TELEGRAM_TOKEN"], s["TELEGRAM_CHAT_ID"])
    return jsonify({"ok": ok, "msg": detail})


@app.route("/api/close-position", methods=["POST"])
def api_close_position():
    data = request.get_json(silent=True) or {}
    symbol = data.get("symbol", "")
    if not symbol:
        return jsonify({"ok": False, "msg": "ไม่ได้ระบุเหรียญ"})
    ok, msg = engine.close_position(symbol)
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/status")
def api_status():
    return jsonify(engine.status())


@app.route("/api/trades")
def api_trades():
    return jsonify(trade_logger.get_trades(limit=200))


@app.route("/api/summary")
def api_summary():
    return jsonify(trade_logger.daily_summary())


@app.route("/api/equity")
def api_equity():
    return jsonify(trade_logger.equity_curve())


@app.route("/export.csv")
def export_csv():
    path = trade_logger.export_csv()
    return send_file(path, as_attachment=True, download_name="trades_export.csv")


if __name__ == "__main__":
    import os
    import socket
    import threading
    import webbrowser

    def find_free_port(preferred):
        """ลองพอร์ตที่ตั้งไว้ก่อน ถ้าไม่ว่างไล่หาตัวถัดไป สุดท้ายให้ OS เลือกให้"""
        candidates = [preferred] + [preferred + i for i in range(1, 21)]
        for p in candidates:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind(("127.0.0.1", p))
                    return p
                except OSError:
                    continue
        # หาไม่เจอในลิสต์ -> ให้ระบบเลือกพอร์ตว่างเอง
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    # พอร์ต 5000 บน macOS ชนกับ AirPlay Receiver -> เริ่มที่ 8000 (ปรับได้ด้วย env PORT)
    preferred = int(os.getenv("PORT", "8000"))
    port = find_free_port(preferred)
    url = f"http://127.0.0.1:{port}"

    trade_logger.init_db()
    if port != preferred:
        print(f"(พอร์ต {preferred} ไม่ว่าง -> ใช้ {port} แทน)")
    print(f"เปิดเบราว์เซอร์ที่ {url}")
    # เปิดเบราว์เซอร์ให้อัตโนมัติหลังเซิร์ฟเวอร์เริ่ม
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
