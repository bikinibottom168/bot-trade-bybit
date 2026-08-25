# บอทเทรด Bybit + Web Dashboard

บอทเทรดฟิวเจอร์ส Bybit ตามกลยุทธ์ในข่าว (candlestick ~10 แบบ + RSI + TP 0.2%)
พร้อม **หน้าเว็บตั้งค่า/ควบคุม**, **log เทรดเป็นไม้ ๆ**, **แจ้งเตือน Telegram**,
และตัวกันเจ๊งที่ข่าวไม่มี (stop loss + เบรกฉุกเฉิน)

> ⚠️ กลยุทธ์ในข่าวได้ win rate 100% เพราะ "ไม่มี stop loss" — ออเดอร์ติดลบไม่ถูกนับเป็นแพ้
> แค่ถือค้าง ถ้าตลาดวิ่งทางเดียว + leverage 10x = โดนล้างพอร์ตได้ในไม้เดียว **เริ่มด้วย Testnet เสมอ**

## เริ่มใช้งาน

```bash
cd bot-trade
./setup.sh
```

แค่นี้จบ — สคริปต์จะทำให้ครบทุกอย่าง:

1. สร้าง `.venv` + ติดตั้งไลบรารี (ติดตั้ง `python3-venv` ให้เองถ้าขาด)
2. ถ้ายังไม่มี `.env` → ขึ้นฟอร์มให้กรอก **Bybit API key/secret**, รหัสเข้าหน้าเว็บ, พอร์ต
   (ถ้ามี `.env` อยู่แล้วจะข้ามไปเลย)
3. **รันเบื้องหลังให้** — ปิด SSH แล้วยังทำงานต่อ

### คำสั่งทั้งหมด

| คำสั่ง | ทำอะไร |
|--------|--------|
| `./setup.sh` | ติดตั้ง + ตั้งค่า + รันเบื้องหลัง |
| `./setup.sh stop` | หยุดทำงาน |
| `./setup.sh restart` | รีสตาร์ท (ใช้หลังแก้โค้ดหรือ `.env`) |
| `./setup.sh status` | ดูสถานะ + URL หน้าเว็บ |
| `./setup.sh logs` | ดู log สด (Ctrl+C ออก) |

### รันเบื้องหลังยังไง

- **บน Linux ที่เป็น root** (VPS ทั่วไป) → ใช้ **systemd** อัตโนมัติ
  ปิด SSH ก็อยู่ **reboot เครื่องก็ขึ้นเอง** และถ้า crash จะ restart ให้
- **กรณีอื่น** (macOS, ไม่ใช่ root) → ใช้ `nohup` + ไฟล์ PID
  ปิด terminal ก็อยู่ แต่ **ไม่รอด reboot** ต้องสั่ง `./setup.sh` ใหม่

### ติดตั้งเอง (ถ้าไม่อยากใช้สคริปต์)

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python app.py
```

> **เจอ error `externally-managed-environment` ?**
> Debian/Ubuntu, Python 3.12+ ห้าม `pip install` ลง system Python (PEP 668)
> ต้องใช้ virtual environment ตามด้านบน ถ้า `python3 -m venv` ใช้ไม่ได้ ให้ลงก่อน:
>
> ```bash
> sudo apt update && sudo apt install -y python3-venv python3-full
> ```
>
> อย่าใช้ `--break-system-packages` เพราะอาจทำให้เครื่องมือของระบบพัง

> **หมายเหตุ:** `./app.py` รันตรง ๆ ไม่ได้ (ไฟล์ไม่มี shebang เชลล์เลยอ่านเป็น shell script)
> ต้องใช้ `python app.py` หรือ `./.venv/bin/python app.py`

## รันบน VPS (Vultr / Ubuntu)

```bash
git clone <repo> bot-trade-bybit && cd bot-trade-bybit
./setup.sh          # ตอบ "y" ตรงคำถาม "เปิดให้เข้าจากภายนอก"
sudo ufw allow 8000/tcp
```

แล้วเปิด **http://IP-เซิร์ฟเวอร์:8000** ใส่ user `admin` + รหัสที่ตั้งไว้ตอนรันสคริปต์

ถ้าเปิด **Vultr Firewall** ไว้ ต้องเพิ่มกฎในหน้า portal ด้วย:
Products → เลือก instance → **Settings → Firewall** → เพิ่ม `TCP` port `8000`
Source = IP บ้านคุณ (แนะนำ) หรือ `0.0.0.0/0` ถ้าต้องการเข้าจากทุกที่

### เช็กเมื่อยังเข้าไม่ได้

```bash
./setup.sh status               # ทำงานอยู่ไหม
ss -tlnp | grep 8000            # ต้องเห็น 0.0.0.0:8000 ไม่ใช่ 127.0.0.1:8000
curl -I http://127.0.0.1:8000   # ได้ 401 = แอปปกติ ปัญหาอยู่ที่ firewall
sudo ufw status                 # พอร์ต 8000 ต้อง ALLOW
./setup.sh logs                 # ดู error
```

ถ้าเห็น `127.0.0.1:8000` แปลว่า `HOST` ใน `.env` ยังไม่ใช่ `0.0.0.0` —
แก้แล้วสั่ง `./setup.sh restart`

## ตั้งค่าครั้งแรก

1. ไปแท็บ **ตั้งค่า** → ใส่ Bybit API key (จาก https://testnet.bybit.com → API Management,
   เปิดสิทธิ์ **Trade** เท่านั้น อย่าเปิด Withdraw) → กด **บันทึก** → กด **ทดสอบเชื่อมต่อ**
2. (ถ้าต้องการ) ใส่ **Telegram Bot Token + Chat ID** แล้วกด **ส่งข้อความทดสอบ**
3. กลับแท็บ **แดชบอร์ด** → กด **▶ Start**

ค่าเริ่มต้น: `TESTNET=on`, `DRY_RUN=on` → ปลอดภัย ไม่แตะเงินจริง

## หน้าตาแดชบอร์ด

- การ์ดสรุป: กำไรสะสม, PnL เซสชัน, ไม้วันนี้, win rate, สุทธิวันนี้, โพซิชันเปิด
- กราฟกำไรสะสม (equity curve)
- ตาราง log เทรดทุกไม้ + ปุ่ม Export CSV
- Log ระบบแบบสด

## ไฟล์ในโปรเจกต์

| ไฟล์ | หน้าที่ |
|------|---------|
| `app.py` | Web Dashboard (Flask) |
| `bot.py` | Bot engine (start/stop, เทรด, แจ้งเตือน) |
| `strategy.py` | RSI + candlestick patterns |
| `trade_logger.py` | เก็บ log ลง SQLite + สรุปรายวัน + export CSV |
| `notifier.py` | แจ้งเตือน Telegram |
| `backtest.py` | ทดสอบกลยุทธ์ย้อนหลัง |
| `config.py` | โหลด/บันทึกค่าตั้งจาก `.env` |
| `setup.sh` | ติดตั้ง / รันเบื้องหลัง / stop / restart / status / logs |
| `templates/index.html` | หน้าเว็บ |

## Telegram แจ้งเตือน

- **เรียลไทม์**: ทุกครั้งที่เปิด/ปิดออเดอร์ (ปิดได้ที่ตั้งค่า `แจ้งเตือนทุกไม้`)
- **สรุปรายวัน**: ส่งเวลาที่ตั้งไว้ (ค่าเริ่มต้น 21:00) — จำนวนไม้, win rate, กำไรสุทธิ, ไม้ดี/แย่สุด, กำไรสะสม
- **ฉุกเฉิน**: เมื่อเบรกทำงาน (ขาดทุนถึงเพดานต่อวัน)

วิธีหา token/chat id: ทัก **@BotFather** สร้างบอทเอา token → ทัก **@userinfobot** เพื่อดู Chat ID

## เตือนความเสี่ยง

โค้ดเพื่อการศึกษา ไม่ใช่คำแนะนำการลงทุน การเทรด futures ด้วย leverage เสี่ยงสูงมาก
อาจสูญเงินทั้งหมด ทดสอบบน Testnet ให้มั่นใจก่อนใช้เงินจริง และเริ่มด้วยเงินก้อนเล็กที่รับความเสียหายได้
