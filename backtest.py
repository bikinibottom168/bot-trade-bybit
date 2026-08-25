"""
backtest.py
-----------
ทดสอบกลยุทธ์ย้อนหลังด้วยข้อมูลจริงจาก Bybit (public data ไม่ต้องใช้ API key)
เพื่อดูว่ากลยุทธ์ "ตามข่าว" (ไม่มี stop loss) จะเป็นยังไงจริง ๆ

รัน:  python backtest.py
เทียบผลระหว่าง "ไม่มี SL (ตามข่าว)" กับ "มี SL"
"""

import ccxt
import config
from strategy import generate_signal

SYMBOL = "BTC/USDT:USDT"
TIMEFRAME = "5m"
LIMIT = 1000          # จำนวนแท่งย้อนหลัง


def run_backtest(use_stop_loss: bool):
    ex = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    raw = ex.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=LIMIT)
    candles = [{"time": r[0], "open": r[1], "high": r[2],
                "low": r[3], "close": r[4], "volume": r[5]} for r in raw]

    tp_pct = config.TAKE_PROFIT_PCT
    sl_pct = config.STOP_LOSS_PCT

    trades, wins, losses = 0, 0, 0
    pnl_pct = 0.0
    worst_open = 0.0        # การลอยขาดทุนหนักสุดระหว่างถือ (max adverse)
    pos = None

    for i in range(20, len(candles) - 1):
        window = candles[:i + 1]
        price = window[-1]["close"]

        if pos:
            # เช็คแท่งถัดไปว่าโดน TP หรือ SL
            hi = candles[i + 1]["high"]
            lo = candles[i + 1]["low"]
            if pos["side"] == "buy":
                adverse = (lo - pos["entry"]) / pos["entry"]
                worst_open = min(worst_open, adverse)
                if use_stop_loss and lo <= pos["sl"]:
                    pnl_pct -= sl_pct; losses += 1; trades += 1; pos = None
                elif hi >= pos["tp"]:
                    pnl_pct += tp_pct; wins += 1; trades += 1; pos = None
            else:
                adverse = (pos["entry"] - hi) / pos["entry"]
                worst_open = min(worst_open, adverse)
                if use_stop_loss and hi >= pos["sl"]:
                    pnl_pct -= sl_pct; losses += 1; trades += 1; pos = None
                elif lo <= pos["tp"]:
                    pnl_pct += tp_pct; wins += 1; trades += 1; pos = None
            continue

        sig = generate_signal(window, config.RSI_PERIOD,
                              config.RSI_BUY_BELOW, config.RSI_SELL_ABOVE)
        if sig["side"] == "buy":
            pos = {"side": "buy", "entry": price,
                   "tp": price * (1 + tp_pct), "sl": price * (1 - sl_pct)}
        elif sig["side"] == "sell":
            pos = {"side": "sell", "entry": price,
                   "tp": price * (1 - tp_pct), "sl": price * (1 + sl_pct)}

    open_txt = "ยังถือค้าง (นับเป็น 'ยังไม่แพ้')" if pos else "ปิดหมด"
    wr = (wins / trades * 100) if trades else 0
    print(f"\n=== {'มี Stop Loss' if use_stop_loss else 'ไม่มี Stop Loss (ตามข่าว)'} ===")
    print(f"เทรดที่ปิดแล้ว : {trades}  (ชนะ {wins} / แพ้ {losses})")
    print(f"Win rate       : {wr:.1f}%")
    print(f"กำไรรวม (ก่อน leverage) : {pnl_pct*100:+.2f}%  "
          f"| หลัง leverage {config.LEVERAGE}x ≈ {pnl_pct*100*config.LEVERAGE:+.2f}%")
    print(f"ขาดทุนลอยหนักสุดระหว่างถือ : {worst_open*100:.2f}%  "
          f"(× {config.LEVERAGE}x ≈ {worst_open*100*config.LEVERAGE:.2f}% ของมาร์จิ้น)")
    print(f"สถานะปลายทาง   : {open_txt}")


if __name__ == "__main__":
    print(f"Backtest {SYMBOL} TF={TIMEFRAME} ~{LIMIT} แท่ง (TP={config.TAKE_PROFIT_PCT*100}%)")
    run_backtest(use_stop_loss=False)   # แบบข่าว
    run_backtest(use_stop_loss=True)    # แบบปลอดภัย
    print("\nหมายเหตุ: 'ไม่มี SL' จะได้ win rate สูงลิ่ว แต่ดู 'ขาดทุนลอยหนักสุด' ให้ดี")
    print("นั่นคือจุดที่พอร์ตจริงอาจโดนล้าง แม้ตัวเลข win rate จะสวย")
