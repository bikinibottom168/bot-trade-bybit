"""
notifier.py
-----------
แจ้งเตือนผ่าน Telegram
- ส่งข้อความเปิด/ปิดออเดอร์ (เรียลไทม์)
- ส่งสรุปยอดรายวัน
- ฟังก์ชันทดสอบการเชื่อมต่อ (ใช้กับปุ่มใน GUI)

ต้องมี Bot Token (จาก @BotFather) และ Chat ID
"""

import json
import urllib.request
import urllib.parse

API = "https://api.telegram.org/bot{token}/{method}"


def _call(token, method, params, timeout=10):
    url = API.format(token=token, method=method)
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def send(token, chat_id, text):
    """ส่งข้อความ. คืน (ok: bool, detail: str)"""
    if not token or not chat_id:
        return False, "ยังไม่ได้ตั้ง Telegram token / chat id"
    try:
        res = _call(token, "sendMessage", {
            "chat_id": chat_id, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        })
        if res.get("ok"):
            return True, "ส่งสำเร็จ"
        return False, res.get("description", "unknown error")
    except Exception as e:
        return False, str(e)


def test_connection(token, chat_id):
    """ใช้กับปุ่มทดสอบใน GUI"""
    return send(token, chat_id, "✅ ทดสอบการเชื่อมต่อ Telegram สำเร็จ — บอทเทรดพร้อมส่งแจ้งเตือนแล้ว")


def notify_trade_open(token, chat_id, symbol, side, price, tp, sl, mode):
    arrow = "🟢 LONG" if side == "buy" else "🔴 SHORT"
    sl_txt = f"{sl:.4f}" if sl else "— (ไม่มี)"
    text = (f"<b>เปิดออเดอร์</b> [{mode}]\n"
            f"{arrow}  <b>{symbol}</b>\n"
            f"เข้า: <code>{price:.4f}</code>\n"
            f"TP: <code>{tp:.4f}</code>  |  SL: <code>{sl_txt}</code>")
    return send(token, chat_id, text)


def notify_trade_close(token, chat_id, symbol, exit_price, pnl_usdt, reason, cum_pnl):
    emoji = "✅" if pnl_usdt > 0 else "❌"
    text = (f"<b>ปิดออเดอร์</b> {emoji}\n"
            f"<b>{symbol}</b> @ <code>{exit_price:.4f}</code> ({reason})\n"
            f"PnL: <b>{pnl_usdt:+.2f}</b> USDT\n"
            f"สะสม: <b>{cum_pnl:+.2f}</b> USDT")
    return send(token, chat_id, text)


def notify_circuit_breaker(token, chat_id, loss):
    text = (f"🛑 <b>เบรกฉุกเฉินทำงาน</b>\n"
            f"ขาดทุนสะสมถึงเพดาน ({loss:.2f} USDT)\n"
            f"บอทหยุดเทรดอัตโนมัติแล้ว")
    return send(token, chat_id, text)


def format_daily_summary(s):
    """s = dict จาก trade_logger.daily_summary()"""
    head = "📊 <b>สรุปยอดรายวัน</b> " + s["date"]
    if s["trades"] == 0:
        return head + "\n\nวันนี้ยังไม่มีการปิดออเดอร์"
    return (
        f"{head}\n\n"
        f"จำนวนไม้: <b>{s['trades']}</b>  (ชนะ {s['wins']} / แพ้ {s['losses']})\n"
        f"Win rate: <b>{s['winrate']:.1f}%</b>\n"
        f"กำไรสุทธิวันนี้: <b>{s['net']:+.2f}</b> USDT\n"
        f"ค่าธรรมเนียมรวม: {s['fees']:.2f} USDT\n"
        f"ไม้กำไรสุด: {s['best']:+.2f}  |  ขาดทุนสุด: {s['worst']:+.2f}\n"
        f"กำไรสะสมทั้งหมด: <b>{s['cum_pnl']:+.2f}</b> USDT"
    )


def send_daily_summary(token, chat_id, summary):
    return send(token, chat_id, format_daily_summary(summary))
