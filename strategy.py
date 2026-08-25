"""
strategy.py
-----------
ตรรกะสัญญาณเทรด: RSI filter + Candlestick patterns (~10 แบบ)
เลียนแบบแนวทางจากข่าว (siamblockchain) แต่เขียนแบบอ่านง่ายและปรับค่าได้

ไม่ต้องใช้ TA-Lib — คำนวณ RSI และรูปแบบแท่งเทียนด้วย Python ล้วน
แต่ละ candle เป็น dict: {"open","high","low","close","volume"}
"""

from typing import List, Dict, Optional


# --------------------------------------------------------------------------
# ตัวชี้วัด (Indicators)
# --------------------------------------------------------------------------
def rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """คำนวณค่า RSI ล่าสุด (Wilder's smoothing). คืน None ถ้าข้อมูลไม่พอ"""
    if len(closes) < period + 1:
        return None

    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    # ค่าเฉลี่ยเริ่มต้น
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # smoothing ต่อ
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles: List[Dict], period: int = 14) -> Optional[float]:
    """Average True Range (หน่วยเป็นราคา) ของแท่งล่าสุด. คืน None ถ้าข้อมูลไม่พอ"""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l = candles[i]["high"], candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
    # ค่าเฉลี่ยเคลื่อนที่แบบ Wilder
    a = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        a = (a * (period - 1) + trs[i]) / period
    return a


def _body(c: Dict) -> float:
    return abs(c["close"] - c["open"])


def _range(c: Dict) -> float:
    return c["high"] - c["low"]


def _upper_wick(c: Dict) -> float:
    return c["high"] - max(c["close"], c["open"])


def _lower_wick(c: Dict) -> float:
    return min(c["close"], c["open"]) - c["low"]


def _is_bull(c: Dict) -> bool:
    return c["close"] > c["open"]


def _is_bear(c: Dict) -> bool:
    return c["close"] < c["open"]


# --------------------------------------------------------------------------
# รูปแบบแท่งเทียน ~10 แบบ  (คืน "bull" / "bear" / None)
# ใช้แท่งล่าสุด (prev, last) ในการตัดสิน
# --------------------------------------------------------------------------
def bullish_engulfing(prev, last):
    if _is_bear(prev) and _is_bull(last) \
       and last["close"] >= prev["open"] and last["open"] <= prev["close"]:
        return "bull"
    return None


def bearish_engulfing(prev, last):
    if _is_bull(prev) and _is_bear(last) \
       and last["open"] >= prev["close"] and last["close"] <= prev["open"]:
        return "bear"
    return None


def hammer(prev, last):
    rng = _range(last)
    if rng == 0:
        return None
    if _lower_wick(last) >= 2 * _body(last) and _upper_wick(last) <= _body(last):
        return "bull"
    return None


def shooting_star(prev, last):
    rng = _range(last)
    if rng == 0:
        return None
    if _upper_wick(last) >= 2 * _body(last) and _lower_wick(last) <= _body(last):
        return "bear"
    return None


def doji(prev, last):
    rng = _range(last)
    if rng == 0:
        return None
    # ตัวเทียนเล็กมากเมื่อเทียบกับช่วงราคา -> สัญญาณกลับตัว (ตามทิศแท่งก่อนหน้า)
    if _body(last) <= 0.1 * rng:
        return "bull" if _is_bear(prev) else "bear"
    return None


def bullish_marubozu(prev, last):
    rng = _range(last)
    if rng == 0:
        return None
    if _is_bull(last) and _body(last) >= 0.9 * rng:
        return "bull"
    return None


def bearish_marubozu(prev, last):
    rng = _range(last)
    if rng == 0:
        return None
    if _is_bear(last) and _body(last) >= 0.9 * rng:
        return "bear"
    return None


def piercing_line(prev, last):
    mid_prev = (prev["open"] + prev["close"]) / 2
    if _is_bear(prev) and _is_bull(last) \
       and last["open"] < prev["low"] and last["close"] > mid_prev \
       and last["close"] < prev["open"]:
        return "bull"
    return None


def dark_cloud_cover(prev, last):
    mid_prev = (prev["open"] + prev["close"]) / 2
    if _is_bull(prev) and _is_bear(last) \
       and last["open"] > prev["high"] and last["close"] < mid_prev \
       and last["close"] > prev["open"]:
        return "bear"
    return None


def inverted_hammer(prev, last):
    rng = _range(last)
    if rng == 0:
        return None
    if _upper_wick(last) >= 2 * _body(last) and _lower_wick(last) <= _body(last) \
       and _is_bear(prev):
        return "bull"
    return None


PATTERNS = [
    ("bullish_engulfing", bullish_engulfing),
    ("bearish_engulfing", bearish_engulfing),
    ("hammer", hammer),
    ("shooting_star", shooting_star),
    ("doji", doji),
    ("bullish_marubozu", bullish_marubozu),
    ("bearish_marubozu", bearish_marubozu),
    ("piercing_line", piercing_line),
    ("dark_cloud_cover", dark_cloud_cover),
    ("inverted_hammer", inverted_hammer),
]


def detect_patterns(candles: List[Dict]):
    """คืน list ของ (ชื่อ pattern, ทิศทาง) ที่พบจากแท่งล่าสุด"""
    if len(candles) < 2:
        return []
    prev, last = candles[-2], candles[-1]
    hits = []
    for name, fn in PATTERNS:
        direction = fn(prev, last)
        if direction:
            hits.append((name, direction))
    return hits


# --------------------------------------------------------------------------
# รวมสัญญาณ:  candlestick + RSI filter
# --------------------------------------------------------------------------
def generate_signal(candles: List[Dict],
                    rsi_period: int = 14,
                    rsi_buy_below: float = 40.0,
                    rsi_sell_above: float = 60.0):
    """
    คืน dict อธิบายสัญญาณ:
      {"side": "buy"/"sell"/None, "rsi": float, "patterns": [...], "reason": str}

    ตามข่าว: ลดเกณฑ์ RSI เพื่อให้เข้าออเดอร์บ่อยขึ้น
      - เจอ pattern ฝั่ง bull + RSI ต่ำกว่า rsi_buy_below  -> buy (long)
      - เจอ pattern ฝั่ง bear + RSI สูงกว่า rsi_sell_above -> sell (short)
    """
    closes = [c["close"] for c in candles]
    r = rsi(closes, rsi_period)
    hits = detect_patterns(candles)

    if r is None or not hits:
        return {"side": None, "rsi": r, "patterns": hits, "reason": "no signal"}

    bull = [h for h in hits if h[1] == "bull"]
    bear = [h for h in hits if h[1] == "bear"]

    if bull and r <= rsi_buy_below:
        names = ", ".join(h[0] for h in bull)
        return {"side": "buy", "rsi": r, "patterns": bull,
                "reason": f"bull pattern ({names}) + RSI {r:.1f} <= {rsi_buy_below}"}

    if bear and r >= rsi_sell_above:
        names = ", ".join(h[0] for h in bear)
        return {"side": "sell", "rsi": r, "patterns": bear,
                "reason": f"bear pattern ({names}) + RSI {r:.1f} >= {rsi_sell_above}"}

    return {"side": None, "rsi": r, "patterns": hits,
            "reason": f"pattern found but RSI {r:.1f} not in zone"}
