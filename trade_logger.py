"""
trade_logger.py
---------------
เก็บ log การเทรดเป็นไม้ ๆ ลง SQLite และสรุปยอดรายวัน
- เก็บทุกออเดอร์ที่ปิด พร้อม PnL (USDT + %), ค่าธรรมเนียม, กำไรสะสม
- ดึงประวัติ, สรุปรายวัน, export CSV
"""

import os
import csv
import sqlite3
import datetime as dt

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_open   TEXT,
                ts_close  TEXT,
                symbol    TEXT,
                side      TEXT,
                entry     REAL,
                exit      REAL,
                amount    REAL,
                leverage  INTEGER,
                tp        REAL,
                sl        REAL,
                reason    TEXT,
                pnl_usdt  REAL,
                pnl_pct   REAL,
                fee       REAL,
                cum_pnl   REAL,
                is_win    INTEGER,
                mode      TEXT
            )
        """)


def _init_positions():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS open_positions (
                symbol   TEXT PRIMARY KEY,
                side     TEXT,
                entry    REAL,
                tp       REAL,
                sl       REAL,
                amount   REAL,
                notional REAL,
                ts_open  TEXT,
                mode     TEXT,
                entries  INTEGER DEFAULT 1
            )
        """)
        # migration: เพิ่มคอลัมน์ entries ให้ DB เก่า
        cols = [r["name"] for r in c.execute("PRAGMA table_info(open_positions)").fetchall()]
        if "entries" not in cols:
            c.execute("ALTER TABLE open_positions ADD COLUMN entries INTEGER DEFAULT 1")


def save_position(symbol, pos: dict):
    """บันทึก/อัปเดตไม้ที่เปิดอยู่ 1 ไม้ลงดิสก์"""
    _init_positions()
    with _conn() as c:
        c.execute("""
            INSERT INTO open_positions (symbol, side, entry, tp, sl, amount, notional, ts_open, mode, entries)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
                side=excluded.side, entry=excluded.entry, tp=excluded.tp, sl=excluded.sl,
                amount=excluded.amount, notional=excluded.notional,
                ts_open=excluded.ts_open, mode=excluded.mode, entries=excluded.entries
        """, (symbol, pos.get("side"), pos.get("entry"), pos.get("tp"), pos.get("sl"),
              pos.get("amount"), pos.get("notional"), pos.get("ts_open"), pos.get("mode"),
              pos.get("entries", 1)))


def remove_position(symbol):
    _init_positions()
    with _conn() as c:
        c.execute("DELETE FROM open_positions WHERE symbol=?", (symbol,))


def get_positions():
    """คืน dict: symbol -> pos ที่บันทึกไว้จากรอบก่อน"""
    _init_positions()
    with _conn() as c:
        rows = c.execute("SELECT * FROM open_positions").fetchall()
    return {r["symbol"]: dict(r) for r in rows}


def replace_positions(positions: dict):
    """เขียนทับตารางไม้ที่เปิดอยู่ทั้งหมดให้ตรงกับสถานะปัจจุบัน"""
    _init_positions()
    with _conn() as c:
        c.execute("DELETE FROM open_positions")
        for symbol, pos in positions.items():
            c.execute("""
                INSERT INTO open_positions (symbol, side, entry, tp, sl, amount, notional, ts_open, mode, entries)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (symbol, pos.get("side"), pos.get("entry"), pos.get("tp"), pos.get("sl"),
                  pos.get("amount"), pos.get("notional"), pos.get("ts_open"), pos.get("mode"),
                  pos.get("entries", 1)))


def record_trade(trade: dict):
    """
    บันทึกออเดอร์ที่ปิดแล้ว 1 ไม้
    trade ต้องมี: ts_open, ts_close, symbol, side, entry, exit, amount,
                  leverage, tp, sl, reason, pnl_usdt, pnl_pct, fee, mode
    คืนค่า row ที่บันทึก (รวม cum_pnl ที่คำนวณให้)
    """
    init_db()
    with _conn() as c:
        row = c.execute("SELECT cum_pnl FROM trades ORDER BY id DESC LIMIT 1").fetchone()
        prev_cum = row["cum_pnl"] if row and row["cum_pnl"] is not None else 0.0
        cum = prev_cum + trade["pnl_usdt"]
        is_win = 1 if trade["pnl_usdt"] > 0 else 0
        c.execute("""
            INSERT INTO trades (ts_open, ts_close, symbol, side, entry, exit, amount,
                leverage, tp, sl, reason, pnl_usdt, pnl_pct, fee, cum_pnl, is_win, mode)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            trade["ts_open"], trade["ts_close"], trade["symbol"], trade["side"],
            trade["entry"], trade["exit"], trade["amount"], trade["leverage"],
            trade.get("tp"), trade.get("sl"), trade["reason"], trade["pnl_usdt"],
            trade["pnl_pct"], trade.get("fee", 0.0), cum, is_win, trade.get("mode", ""),
        ))
    trade = dict(trade)
    trade["cum_pnl"] = cum
    trade["is_win"] = is_win
    return trade


def get_trades(limit=200):
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def daily_summary(date_str=None):
    """สรุปยอดของวัน (ตามวันที่ในเวลาเครื่อง). date_str = 'YYYY-MM-DD'"""
    init_db()
    if date_str is None:
        date_str = dt.datetime.now().strftime("%Y-%m-%d")
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM trades WHERE substr(ts_close,1,10)=? ORDER BY id", (date_str,)
        ).fetchall()

    rows = [dict(r) for r in rows]
    trades = len(rows)
    wins = sum(1 for r in rows if r["is_win"])
    losses = trades - wins
    gross = sum(r["pnl_usdt"] for r in rows)
    fees = sum(r["fee"] or 0 for r in rows)
    net = gross  # pnl_usdt เก็บแบบสุทธิหลังหักค่าธรรมเนียมอยู่แล้ว
    best = max((r["pnl_usdt"] for r in rows), default=0.0)
    worst = min((r["pnl_usdt"] for r in rows), default=0.0)
    winrate = (wins / trades * 100) if trades else 0.0
    cum = rows[-1]["cum_pnl"] if rows else _last_cum()

    return {
        "date": date_str, "trades": trades, "wins": wins, "losses": losses,
        "winrate": winrate, "gross": gross, "fees": fees, "net": net,
        "best": best, "worst": worst, "cum_pnl": cum,
    }


def _last_cum():
    with _conn() as c:
        row = c.execute("SELECT cum_pnl FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    return row["cum_pnl"] if row and row["cum_pnl"] is not None else 0.0


def equity_curve(limit=500):
    """คืนลิสต์ (ลำดับ, cum_pnl) สำหรับวาดกราฟกำไรสะสม"""
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT id, ts_close, cum_pnl FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    rows = list(reversed([dict(r) for r in rows]))
    return [{"i": i + 1, "ts": r["ts_close"], "cum": r["cum_pnl"]}
            for i, r in enumerate(rows)]


def export_csv(path=None):
    init_db()
    if path is None:
        path = os.path.join(os.path.dirname(DB_PATH), "trades_export.csv")
    rows = get_trades(limit=100000)
    rows = list(reversed(rows))
    fields = ["id", "ts_open", "ts_close", "symbol", "side", "entry", "exit",
              "amount", "leverage", "tp", "sl", "reason", "pnl_usdt", "pnl_pct",
              "fee", "cum_pnl", "is_win", "mode"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    return path
