"""
bot.py
------
Bot engine ควบคุมด้วย GUI (start/stop ผ่าน thread)
- ดึงราคาจาก Bybit -> หาสัญญาณ (strategy) -> เปิด/ปิดออเดอร์
- บันทึกทุกไม้ลง trade_logger (SQLite) + จำไม้ที่เปิดอยู่ลงดิสก์
- กู้สถานะเมื่อเปิดใหม่ (reconcile กับ Bybit) รันต่อไม่สะดุด
- แจ้งเตือน Telegram เรียลไทม์ + สรุปรายวัน
- stop loss (ปิดได้) + เบรกฉุกเฉิน + กันเปิดโปรแกรมซ้อน (lock)
"""

import os
import time
import threading
import datetime as dt

import ccxt

import config
import trade_logger
import notifier
from strategy import generate_signal, atr

FEE_RATE = 0.00055   # ค่าธรรมเนียม taker โดยประมาณของ Bybit (ต่อข้าง)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_PATH = os.path.join(BASE_DIR, "bot.lock")


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return True


class BotEngine:
    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self.running = False
        self.log_lines = []            # ข้อความ log ล่าสุด (ไว้โชว์ใน GUI)
        self.open_positions = {}       # symbol -> dict
        self.session_pnl = 0.0
        self.last_error = ""
        self._last_summary_date = None
        self._skip_until = {}          # symbol -> เวลาที่พักไม่เข้าไม้ (เงินไม่พอ ฯลฯ)
        self.ex = None
        self.s = {}

    # ---------------------------------------------------------------
    def log(self, msg):
        line = time.strftime("[%H:%M:%S] ") + msg
        print(line, flush=True)
        self.log_lines.append(line)
        self.log_lines = self.log_lines[-300:]

    def status(self):
        poss, total_upnl = [], 0.0
        for sym, v in self.open_positions.items():
            upnl = v.get("upnl") or 0.0
            total_upnl += upnl
            poss.append({
                "symbol": sym, "side": v.get("side"), "entry": v.get("entry"),
                "mark": v.get("mark"), "amount": v.get("amount"),
                "notional": v.get("notional"), "tp": v.get("tp"), "sl": v.get("sl"),
                "upnl": round(upnl, 4), "ts_open": v.get("ts_open"),
                "entries": v.get("entries", 1),
            })
        return {
            "running": self.running,
            "session_pnl": round(self.session_pnl, 2),
            "unrealized": round(total_upnl, 2),
            "open_positions": poss,
            "last_error": self.last_error,
            "log": self.log_lines[-60:],
        }

    # ---------------------------------------------------------------
    def _mode(self):
        s = self.s
        return "DRY" if s["DRY_RUN"] else ("TESTNET" if s["TESTNET"] else "LIVE")

    def _is_live(self):
        return (not self.s["DRY_RUN"]) and bool(self.s["BYBIT_API_KEY"])

    def _build_exchange(self):
        ex = ccxt.bybit({
            "apiKey": self.s["BYBIT_API_KEY"],
            "secret": self.s["BYBIT_API_SECRET"],
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })
        if self.s["TESTNET"]:
            ex.set_sandbox_mode(True)
        return ex

    def _fetch_candles(self, symbol, limit=100):
        raw = self.ex.fetch_ohlcv(symbol, timeframe=self.s["TIMEFRAME"], limit=limit)
        return [{"time": r[0], "open": r[1], "high": r[2],
                 "low": r[3], "close": r[4], "volume": r[5]} for r in raw]

    def _tg(self):
        return self.s.get("TELEGRAM_TOKEN", ""), self.s.get("TELEGRAM_CHAT_ID", "")

    def _available_usdt(self):
        """ยอด USDT ที่ใช้เปิดออเดอร์ได้ (free). คืน None ถ้าดึงไม่ได้"""
        try:
            bal = self.ex.fetch_balance()
            u = bal.get("USDT", {}) or {}
            val = u.get("free")
            if val is None:
                val = u.get("total")
            return float(val) if val is not None else None
        except Exception:
            return None

    def _ts_to_ms(self, ts):
        try:
            return int(dt.datetime.fromisoformat(ts).timestamp() * 1000)
        except Exception:
            return 0

    # ---------------------------------------------------------------
    def _adjust_amount(self, symbol, raw_amount, price):
        """ปรับจำนวนให้ตรง precision และไม่ต่ำกว่าขั้นต่ำของ Bybit"""
        try:
            market = self.ex.market(symbol)
            amt = float(self.ex.amount_to_precision(symbol, raw_amount))
            limits = market.get("limits", {}) or {}
            min_amt = (limits.get("amount", {}) or {}).get("min")
            if min_amt and amt < min_amt:
                amt = float(self.ex.amount_to_precision(symbol, min_amt))
                self.log(f"  ปรับขนาด {symbol} ขึ้นเป็นขั้นต่ำ {amt}")
            min_cost = (limits.get("cost", {}) or {}).get("min")
            if min_cost and amt * price < min_cost:
                amt = float(self.ex.amount_to_precision(symbol, min_cost / price))
                self.log(f"  ปรับขนาด {symbol} ให้ถึงมูลค่าขั้นต่ำ {min_cost} USDT")
            return amt
        except Exception:
            return round(raw_amount, 6)

    def _extract_fill(self, order, symbol):
        """อ่านราคาฟิลล์จริง/จำนวน/ค่าธรรมเนียมจากผลตอบกลับของออเดอร์"""
        try:
            fp = order.get("average") or order.get("price")
            fa = order.get("filled") or order.get("amount")
            fee = None
            if order.get("fee") and order["fee"].get("cost") is not None:
                fee = float(order["fee"]["cost"])
            elif order.get("fees"):
                fee = sum(float(f.get("cost", 0) or 0) for f in order["fees"])
            if not fp:
                o2 = self.ex.fetch_order(order["id"], symbol)
                fp = o2.get("average") or o2.get("price")
                fa = o2.get("filled") or fa
            return (float(fp) if fp else None, float(fa) if fa else None, fee)
        except Exception:
            return None, None, None

    def _fetch_realized(self, symbol, since_ms):
        """ดึงกำไร/ขาดทุนจริง (closed PnL) จาก Bybit สำหรับไม้ที่ปิดไป"""
        try:
            mid = self.ex.market(symbol)["id"]
            resp = self.ex.private_get_v5_position_closed_pnl(
                {"category": "linear", "symbol": mid, "limit": 50})
            lst = (resp.get("result", {}) or {}).get("list", []) or []
            rel = [x for x in lst if int(x.get("updatedTime", 0) or 0) >= since_ms - 2000]
            if not rel:
                rel = lst[:1]
            if not rel:
                return None, None
            pnl = sum(float(x.get("closedPnl", 0) or 0) for x in rel)
            exitp = float(rel[0].get("avgExitPrice") or 0)
            return pnl, exitp
        except Exception:
            return None, None

    def _set_position_tpsl(self, symbol, tp, sl):
        """ตั้ง TP/SL ระดับโพซิชันบน Bybit (ใช้หลังถัวเฉลี่ย ราคาเฉลี่ยเปลี่ยน)"""
        try:
            mid = self.ex.market(symbol)["id"]
            p = {"category": "linear", "symbol": mid, "positionIdx": 0,
                 "takeProfit": str(self.ex.price_to_precision(symbol, tp))}
            p["stopLoss"] = str(self.ex.price_to_precision(symbol, sl)) if sl else "0"
            self.ex.private_post_v5_position_trading_stop(p)
        except Exception as e:
            self.log(f"  ! ตั้ง TP/SL {symbol} ไม่สำเร็จ: {e}")

    # ---------------------------------------------------------------
    def _open_trade(self, symbol, side, price):
        s = self.s
        add_notional = s["ORDER_USDT"] * s["LEVERAGE"]   # ขนาดต่อไม้ = มาร์จิ้น × leverage
        amount = self._adjust_amount(symbol, add_notional / price, price)
        tp_pct = s["TAKE_PROFIT_PCT"] / 100.0
        sl_pct = s["STOP_LOSS_PCT"] / 100.0
        entry = price
        open_fee = add_notional * FEE_RATE
        mode = self._mode()
        existing = self.open_positions.get(symbol)
        is_add = bool(existing and existing.get("side") == side)

        if self._is_live():
            # เช็คเงินคงเหลือก่อนยิง กันยิงซ้ำเวลามาร์จิ้นไม่พอ
            margin_need = add_notional / max(s["LEVERAGE"], 1)
            avail = self._available_usdt()
            if avail is not None and avail < margin_need * 1.02:
                self.log(f"เงินไม่พอเปิด {symbol} (ต้องใช้ ~{margin_need:.2f} มี {avail:.2f} USDT) -> พัก 5 นาที")
                self._skip_until[symbol] = time.time() + 300
                return
            try:
                # ส่งออเดอร์ตลาดก่อน แล้วค่อยตั้ง TP/SL จากราคาเฉลี่ยทีหลัง
                order = self.ex.create_order(symbol, "market", side, amount)
                fp, fa, fee = self._extract_fill(order, symbol)
                if fp:
                    entry = fp
                if fa:
                    amount = fa
                if fee is not None:
                    open_fee = fee
            except Exception as e:
                msg = str(e)
                if "110007" in msg or "not enough" in msg:
                    self.log(f"เงินไม่พอเปิด {symbol} -> พัก 5 นาที")
                    self._skip_until[symbol] = time.time() + 300
                else:
                    self.log(f"! ส่งคำสั่งไม่สำเร็จ {symbol}: {e} (ไม่บันทึกไม้)")
                return

        # ---- รวมกับไม้เดิม (ถัวเฉลี่ย) ถ้าทิศเดียวกัน ----
        if is_add:
            tot_amount = existing["amount"] + amount
            avg_entry = (existing["entry"] * existing["amount"] + entry * amount) / tot_amount
            entries = existing.get("entries", 1) + 1
            open_fee_tot = existing.get("open_fee", 0) + open_fee
            ts_open = existing.get("ts_open")
        else:
            tot_amount, avg_entry, entries = amount, entry, 1
            open_fee_tot = open_fee
            ts_open = dt.datetime.now().isoformat(timespec="seconds")

        if side == "buy":
            tp = avg_entry * (1 + tp_pct)
            sl = avg_entry * (1 - sl_pct) if s["USE_STOP_LOSS"] else None
        else:
            tp = avg_entry * (1 - tp_pct)
            sl = avg_entry * (1 + sl_pct) if s["USE_STOP_LOSS"] else None

        pos = {
            "side": side, "entry": avg_entry, "tp": tp, "sl": sl,
            "amount": tot_amount, "notional": tot_amount * avg_entry,
            "open_fee": open_fee_tot, "mark": price, "upnl": 0.0,
            "ts_open": ts_open, "mode": mode, "entries": entries,
            "last_add_price": entry,   # ราคาที่ถัวล่าสุด (ใช้วัดระยะห่าง ATR)
        }
        self.open_positions[symbol] = pos
        trade_logger.save_position(symbol, pos)

        if self._is_live():
            self._set_position_tpsl(symbol, tp, sl)

        verb = f"ถัวเพิ่ม (ไม้ที่ {entries})" if is_add else "เปิด"
        self.log(f"{verb} {side.upper()} {symbol} @ {entry:.4f} | เฉลี่ย {avg_entry:.4f} "
                 f"TP={tp:.4f} SL={('%.4f' % sl) if sl else 'ไม่มี'} [{mode}]")
        if s.get("TG_ALERT_TRADES"):
            tok, cid = self._tg()
            notifier.notify_trade_open(tok, cid, symbol, side, entry, tp, sl, mode)

    def _record_close(self, symbol, pos, exit_price, pnl, reason):
        """บันทึกไม้ที่ปิดแล้วลง log + แจ้งเตือน + ลบออกจากดิสก์"""
        s = self.s
        notional = pos.get("notional", pos["amount"] * pos["entry"])
        margin = notional / s["LEVERAGE"] if s["LEVERAGE"] else notional
        self.session_pnl += pnl
        rec = trade_logger.record_trade({
            "ts_open": pos.get("ts_open"),
            "ts_close": dt.datetime.now().isoformat(timespec="seconds"),
            "symbol": symbol, "side": pos["side"], "entry": pos["entry"],
            "exit": exit_price, "amount": pos["amount"], "leverage": s["LEVERAGE"],
            "tp": pos.get("tp"), "sl": pos.get("sl"), "reason": reason,
            "pnl_usdt": pnl, "pnl_pct": (pnl / margin * 100) if margin else 0.0,
            "fee": pos.get("open_fee", 0) + notional * FEE_RATE, "mode": pos.get("mode", self._mode()),
        })
        trade_logger.remove_position(symbol)
        self.log(f"ปิด {symbol} @ {exit_price:.4f} ({reason}) "
                 f"PnL={pnl:+.2f} | สะสม={rec['cum_pnl']:+.2f}")
        if s.get("TG_ALERT_TRADES"):
            tok, cid = self._tg()
            notifier.notify_trade_close(tok, cid, symbol, exit_price, pnl, reason, rec["cum_pnl"])

    def _close_trade_sim(self, symbol, exit_price, reason):
        """ปิดไม้ในโหมด DRY (จำลอง)"""
        pos = self.open_positions.pop(symbol, None)
        if not pos:
            return
        if pos["side"] == "buy":
            pct = (exit_price - pos["entry"]) / pos["entry"]
        else:
            pct = (pos["entry"] - exit_price) / pos["entry"]
        notional = pos.get("notional", pos["amount"] * pos["entry"])
        pnl = pct * notional - notional * FEE_RATE * 2
        self._record_close(symbol, pos, exit_price, pnl, reason)

    def _log_offline_close(self, symbol, pos, manual=False):
        """บันทึกไม้ที่ปิดไป (โดน TP/SL/ผู้ใช้ปิดเองนอกจอ หรือกดปุ่มปิดในแดชบอร์ด)"""
        since_ms = self._ts_to_ms(pos.get("ts_open"))
        pnl, exitp = (None, None)
        if self._is_live():
            pnl, exitp = self._fetch_realized(symbol, since_ms)
        if not exitp:
            exitp = pos.get("mark") or pos.get("entry")
        if pnl is None:
            # ประมาณการถ้าดึงค่าจริงไม่ได้
            if pos["side"] == "buy":
                pct = (exitp - pos["entry"]) / pos["entry"]
            else:
                pct = (pos["entry"] - exitp) / pos["entry"]
            notional = pos.get("notional", pos["amount"] * pos["entry"])
            pnl = pct * notional - notional * FEE_RATE * 2
            reason = "ปิดเอง(ปุ่ม)" if manual else "ปิดนอกระบบ(ประมาณ)"
        else:
            reason = "ปิดเอง(ปุ่ม)" if manual else "ปิดนอกระบบ"
        if not manual:
            self.log(f"พบไม้ {symbol} ปิดไปตอนบอทไม่ได้ดู -> บันทึกย้อนหลัง ({reason})")
        self._record_close(symbol, pos, exitp, pnl, reason)

    def close_position(self, symbol):
        """ปิดไม้ทันทีจากปุ่มบนแดชบอร์ด. คืน (ok, ข้อความ)"""
        pos = self.open_positions.get(symbol)
        if not pos:
            return False, "ไม่พบไม้นี้"
        # โหมดจริง: ส่งคำสั่งตลาดปิด (reduce-only)
        if self._is_live():
            try:
                close_side = "sell" if pos["side"] == "buy" else "buy"
                self.ex.create_order(symbol, "market", close_side, pos["amount"],
                                     params={"reduceOnly": True})
            except Exception as e:
                return False, f"ส่งคำสั่งปิดไม่สำเร็จ: {e}"
        # ลบออกแล้วบันทึกผล (ใช้ราคา/กำไรจริงจาก Bybit ถ้าได้)
        self.open_positions.pop(symbol, None)
        self._log_offline_close(symbol, pos, manual=True)
        self.log(f"ปิดไม้ {symbol} ด้วยปุ่มบนแดชบอร์ด")
        return True, f"ปิด {symbol} แล้ว"

    def _manage_open_sim(self, symbol, price):
        """โหมด DRY: เช็ค TP/SL เอง + อัปเดตกำไรที่ยังไม่ปิด"""
        pos = self.open_positions.get(symbol)
        if not pos:
            return
        if pos["side"] == "buy":
            if price >= pos["tp"]:
                return self._close_trade_sim(symbol, pos["tp"], "TP")
            if pos["sl"] and price <= pos["sl"]:
                return self._close_trade_sim(symbol, pos["sl"], "SL")
            pct = (price - pos["entry"]) / pos["entry"]
        else:
            if price <= pos["tp"]:
                return self._close_trade_sim(symbol, pos["tp"], "TP")
            if pos["sl"] and price >= pos["sl"]:
                return self._close_trade_sim(symbol, pos["sl"], "SL")
            pct = (pos["entry"] - price) / pos["entry"]
        notional = pos.get("notional", pos["amount"] * pos["entry"])
        pos["mark"] = price
        pos["upnl"] = pct * notional

    def _sync_live_positions(self):
        """โหมด LIVE/TESTNET: ยึด Bybit เป็นความจริง อัปเดต/ตรวจไม้ที่ปิดไป"""
        # Bybit: fetch_positions รับทีละเหรียญ ต้องวนลูป
        poss = []
        checked = set()          # เหรียญที่ดึงสำเร็จ (ใช้ตัดสินว่าไม้ถูกปิดได้เฉพาะอันนี้)
        for sym in config.symbols_list(self.s):
            try:
                poss.extend(self.ex.fetch_positions([sym]))
                checked.add(sym)
            except Exception as e:
                self.log(f"! ดึงโพซิชัน {sym} ไม่สำเร็จ: {e}")
        livemap = {}
        for p in poss:
            try:
                contracts = float(p.get("contracts") or 0)
            except Exception:
                contracts = 0
            if not contracts:
                continue
            sym = p["symbol"]
            entry = float(p.get("entryPrice") or 0)
            mark = float(p.get("markPrice") or entry)
            upnl = float(p.get("unrealizedPnl") or 0)
            notional = abs(float(p.get("notional") or entry * contracts))
            livemap[sym] = {
                "side": "buy" if p.get("side") == "long" else "sell",
                "entry": entry, "amount": abs(contracts),
                "notional": notional, "mark": mark, "upnl": upnl,
            }

        # ไม้ที่เราถืออยู่ แต่หายไปจาก Bybit = ถูกปิดไปแล้ว
        # (เฉพาะเหรียญที่ดึงสำเร็จ กันเข้าใจผิดตอนดึงไม่ได้)
        for sym in list(self.open_positions.keys()):
            if sym in checked and sym not in livemap:
                self._log_offline_close(sym, self.open_positions.pop(sym))

        # อัปเดตไม้ที่ยังเปิด / รับไม้ที่ค้างบน Bybit แต่เราไม่มีบันทึก
        saved = None
        for sym, live in livemap.items():
            if sym in self.open_positions:
                self.open_positions[sym].update({
                    "entry": live["entry"], "amount": live["amount"],
                    "notional": live["notional"], "mark": live["mark"], "upnl": live["upnl"],
                })
            else:
                if saved is None:
                    saved = trade_logger.get_positions()
                base = saved.get(sym, {})
                self.open_positions[sym] = {
                    "side": live["side"], "entry": live["entry"], "amount": live["amount"],
                    "notional": live["notional"], "mark": live["mark"], "upnl": live["upnl"],
                    "tp": base.get("tp"), "sl": base.get("sl"), "open_fee": base.get("open_fee", 0),
                    "ts_open": base.get("ts_open") or dt.datetime.now().isoformat(timespec="seconds"),
                    "mode": self._mode(), "entries": base.get("entries", 1),
                }
                self.log(f"พบไม้ค้างบน Bybit: {sym} {live['side']} -> รับมาดูแลต่อ")

        trade_logger.replace_positions(self.open_positions)

    # ---------------------------------------------------------------
    def _reconcile_start(self):
        """กู้สถานะตอนเริ่มโปรแกรม"""
        saved = trade_logger.get_positions()
        if self.s["DRY_RUN"]:
            self.open_positions = {k: dict(v) for k, v in saved.items()}
            if saved:
                self.log(f"โหลดไม้จำลองกลับ {len(saved)} ไม้ (รันต่อ)")
            return
        if not self.s["BYBIT_API_KEY"]:
            return
        # ตั้งต้นด้วยไม้ที่จำไว้ แล้ว sync กับ Bybit (จะจับไม้ที่ปิดไปตอนดับด้วย)
        self.open_positions = {k: dict(v) for k, v in saved.items()}
        if saved:
            self.log(f"ตรวจสอบไม้ที่จำไว้ {len(saved)} ไม้ กับ Bybit...")
        self._sync_live_positions()

    # ---------------------------------------------------------------
    def _maybe_daily_summary(self):
        target = self.s.get("DAILY_SUMMARY_TIME", "21:00")
        now = dt.datetime.now()
        today = now.strftime("%Y-%m-%d")
        try:
            hh, mm = [int(x) for x in target.split(":")]
        except Exception:
            return
        if now.hour == hh and now.minute >= mm and self._last_summary_date != today:
            summary = trade_logger.daily_summary(today)
            tok, cid = self._tg()
            notifier.send_daily_summary(tok, cid, summary)
            self.log(f"ส่งสรุปรายวันแล้ว: {summary['trades']} ไม้, สุทธิ {summary['net']:+.2f}")
            self._last_summary_date = today

    def _check_breaker(self):
        if self.session_pnl <= -abs(self.s["MAX_DAILY_LOSS_USDT"]):
            self.log(f"!!! เบรกฉุกเฉิน: ขาดทุนสะสม {self.session_pnl:.2f} -> หยุดบอท")
            tok, cid = self._tg()
            notifier.notify_circuit_breaker(tok, cid, self.session_pnl)
            self._stop.set()

    def _can_dca(self, pos, candles, price):
        """เช็คว่าได้จังหวะถัวไหม: ราคาต้องห่างจากไม้ล่าสุด ≥ ATR×มัลติ และไม้ต้องติดลบถึงเกณฑ์"""
        s = self.s
        # 1) ต้องติดลบถึงเกณฑ์ (เทียบราคาเฉลี่ย)
        if pos["side"] == "buy":
            loss_pct = (pos["entry"] - price) / pos["entry"] * 100
        else:
            loss_pct = (price - pos["entry"]) / pos["entry"] * 100
        if loss_pct < float(s.get("DCA_MIN_LOSS_PCT", 1.5)):
            return False
        # 2) ราคาต้องห่างจากไม้ที่ถัวล่าสุด ≥ ATR × ตัวคูณ
        a = atr(candles, int(s.get("DCA_ATR_PERIOD", 14)))
        if a:
            last = pos.get("last_add_price", pos["entry"])
            moved = (last - price) if pos["side"] == "buy" else (price - last)
            if moved < float(s.get("DCA_ATR_MULT", 1.0)) * a:
                return False
        return True

    # ---------------------------------------------------------------
    def _step(self):
        s = self.s
        # โหมดจริง: ซิงก์สถานะจาก Bybit ก่อน (จับปิดเอง/TP/SL ฝั่งเซิร์ฟเวอร์)
        if self._is_live():
            self._sync_live_positions()

        for symbol in config.symbols_list(s):
            try:
                candles = self._fetch_candles(symbol)
                price = candles[-1]["close"]

                if s["DRY_RUN"]:
                    self._manage_open_sim(symbol, price)

                if time.time() < self._skip_until.get(symbol, 0):
                    continue   # พักเหรียญนี้ชั่วคราว (เช่น เงินไม่พอ)

                sig = generate_signal(candles, s["RSI_PERIOD"],
                                      s["RSI_BUY_BELOW"], s["RSI_SELL_ABOVE"])
                if not sig["side"]:
                    continue

                existing = self.open_positions.get(symbol)
                max_entries = int(s.get("MAX_ENTRIES_PER_SYMBOL", 1) or 1)
                if existing:
                    # มีไม้อยู่แล้ว: ถัวเพิ่มได้เฉพาะทิศเดียวกัน และยังไม่เกินจำนวนสูงสุด
                    if sig["side"] != existing["side"]:
                        continue   # สัญญาณสวนทาง -> ข้าม (กันปิดไม้เดิมใน One-Way)
                    if existing.get("entries", 1) >= max_entries:
                        continue   # ถัวครบจำนวนแล้ว
                    if not self._can_dca(existing, candles, price):
                        continue   # ยังไม่ได้จังหวะถัว (ราคายังไม่ห่างพอ/ยังไม่ติดลบพอ)
                    self.log(f"{symbol}: ถัวเพิ่ม {sig['side'].upper()} — {sig['reason']}")
                    self._open_trade(symbol, sig["side"], price)
                else:
                    # ไม้ใหม่: จำกัดจำนวนเหรียญที่เปิดพร้อมกัน
                    if len(self.open_positions) >= s["MAX_OPEN_POSITIONS"]:
                        continue
                    self.log(f"{symbol}: สัญญาณ {sig['side'].upper()} — {sig['reason']}")
                    self._open_trade(symbol, sig["side"], price)
            except Exception as e:
                self.last_error = f"{symbol}: {e}"
                self.log(f"! ผิดพลาด {symbol}: {e}")

        self._maybe_daily_summary()
        self._check_breaker()

    def _run(self):
        try:
            self.s = config.load()
            trade_logger.init_db()
            self.ex = self._build_exchange()
            try:
                self.ex.load_markets()
            except Exception as e:
                self.log(f"! โหลดข้อมูลตลาดไม่สำเร็จ: {e}")

            self.log(f"เริ่มบอท | {'TESTNET' if self.s['TESTNET'] else 'LIVE เงินจริง'} | "
                     f"{'DRY_RUN' if self.s['DRY_RUN'] else 'ส่งคำสั่งจริง'} | "
                     f"{'มี SL' if self.s['USE_STOP_LOSS'] else 'ไม่มี SL(ตามข่าว)'}")

            # ตั้ง leverage
            if self._is_live():
                for symbol in config.symbols_list(self.s):
                    try:
                        self.ex.set_leverage(self.s["LEVERAGE"], symbol)
                    except Exception as e:
                        if "110043" in str(e) or "not modified" in str(e):
                            self.log(f"  leverage {symbol} = {self.s['LEVERAGE']}x อยู่แล้ว (ข้าม)")
                        else:
                            self.log(f"! ตั้ง leverage {symbol}: {e}")

            # กู้สถานะ + คิดยอดสะสมของวันนี้ต่อเนื่อง (เบรกไม่รีเซ็ต)
            self.session_pnl = 0.0
            try:
                seed = trade_logger.daily_summary(dt.datetime.now().strftime("%Y-%m-%d"))["net"]
            except Exception:
                seed = 0.0
            self._reconcile_start()
            self.session_pnl += seed
            if seed:
                self.log(f"ยอดสะสมวันนี้จากบันทึกเดิม {seed:+.2f} USDT (เบรกทำงานต่อเนื่อง)")

            while not self._stop.is_set():
                self._step()
                self._stop.wait(self.s["POLL_SECONDS"])
        except Exception as e:
            self.last_error = str(e)
            self.log(f"!! บอทหยุดเพราะ error: {e}")
        finally:
            self.running = False
            self._release_lock()
            self.log("บอทหยุดทำงานแล้ว")

    # ---------------------------------------------------------------
    def _acquire_lock(self):
        try:
            if os.path.exists(LOCK_PATH):
                with open(LOCK_PATH) as f:
                    pid = int((f.read().strip() or "0"))
                if pid and pid != os.getpid() and _pid_alive(pid):
                    return False
            with open(LOCK_PATH, "w") as f:
                f.write(str(os.getpid()))
            return True
        except Exception:
            return True

    def _release_lock(self):
        try:
            if os.path.exists(LOCK_PATH):
                os.remove(LOCK_PATH)
        except Exception:
            pass

    def start(self):
        if self.running:
            return False
        if not self._acquire_lock():
            self.log("! มีบอทกำลังรันอยู่แล้วอีกที่หนึ่ง (lock) — ไม่เริ่มซ้ำ")
            return False
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        return True


# singleton ให้ GUI ใช้
engine = BotEngine()


if __name__ == "__main__":
    engine.start()
    try:
        while engine.running:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()
        print("\nหยุดโดยผู้ใช้")
