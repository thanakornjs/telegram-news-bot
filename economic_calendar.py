import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# ==================== CONFIG ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# ประเทศที่ต้องการรับแจ้งเตือน (ใส่ None เพื่อรับทุกประเทศ)
WATCH_COUNTRIES = None  # None = ทุกประเทศ High-Impact
# ตัวอย่างถ้าอยากเลือกเฉพาะ: WATCH_COUNTRIES = ["USD", "THB", "EUR", "JPY"]

# ระดับความสำคัญขั้นต่ำที่จะแจ้งเตือน
WATCH_IMPACTS = ["High"]  # "High", "Medium", "Low"

# แจ้งเตือนล่วงหน้ากี่นาที
ALERT_BEFORE_MINUTES = 15

# โซนเวลาไทย (UTC+7)
THAI_TZ = timezone(timedelta(hours=7))
# ================================================

IMPACT_EMOJI = {
    "High":   "🔴",
    "Medium": "🟡",
    "Low":    "⚪",
}

COUNTRY_FLAG = {
    "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧",
    "JPY": "🇯🇵", "AUD": "🇦🇺", "CAD": "🇨🇦",
    "CHF": "🇨🇭", "NZD": "🇳🇿", "CNY": "🇨🇳",
    "THB": "🇹🇭",
}

def fetch_calendar() -> list[dict]:
    """ดึงข้อมูลปฏิทินเศรษฐกิจสัปดาห์นี้จาก Forex Factory"""
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        root = ET.fromstring(data)
    except Exception as e:
        print(f"Error fetching calendar: {e}")
        return []

    events = []
    for event in root.findall("event"):
        title   = (event.findtext("title") or "").strip()
        country = (event.findtext("country") or "").strip()
        impact  = (event.findtext("impact") or "").strip()
        date_str = (event.findtext("date") or "").strip()
        time_str = (event.findtext("time") or "").strip()
        forecast = (event.findtext("forecast") or "-").strip()
        previous = (event.findtext("previous") or "-").strip()

        if not date_str or not time_str:
            continue

        try:
            # Forex Factory ใช้ Eastern Time (ET = UTC-4 หรือ UTC-5)
            # ค่าที่ได้มาเป็น "01:00pm" format
            dt_str = f"{date_str} {time_str}"
            # parse แบบ Eastern Time
            naive_dt = datetime.strptime(dt_str, "%m-%d-%Y %I:%M%p")
            # Forex Factory time is US Eastern (UTC-4 in summer)
            et_tz = timezone(timedelta(hours=-4))
            event_dt = naive_dt.replace(tzinfo=et_tz)
        except Exception:
            continue

        events.append({
            "title": title,
            "country": country,
            "impact": impact,
            "datetime": event_dt,
            "forecast": forecast,
            "previous": previous,
        })

    return events

def get_upcoming_events(events: list[dict]) -> list[dict]:
    """กรองเหตุการณ์ที่จะเกิดขึ้นใน ALERT_BEFORE_MINUTES นาทีข้างหน้า"""
    now = datetime.now(timezone.utc)
    alert_window_start = now
    alert_window_end = now + timedelta(minutes=ALERT_BEFORE_MINUTES)

    upcoming = []
    for ev in events:
        # กรองตาม Impact
        if ev["impact"] not in WATCH_IMPACTS:
            continue
        # กรองตาม Country (ถ้ากำหนดไว้)
        if WATCH_COUNTRIES and ev["country"] not in WATCH_COUNTRIES:
            continue
        # เช็คเวลา
        if alert_window_start <= ev["datetime"] <= alert_window_end:
            upcoming.append(ev)

    return upcoming

def format_alert(events: list[dict]) -> str:
    """สร้างข้อความแจ้งเตือนสวยๆ สำหรับ Telegram"""
    if not events:
        return ""

    lines = [f"⚠️ *แจ้งเตือนปฏิทินเศรษฐกิจ* — ใน {ALERT_BEFORE_MINUTES} นาทีข้างหน้า!\n"]
    for ev in events:
        impact_emoji = IMPACT_EMOJI.get(ev["impact"], "⚪")
        flag = COUNTRY_FLAG.get(ev["country"], "🌍")
        thai_time = ev["datetime"].astimezone(THAI_TZ).strftime("%H:%M น.")

        lines.append(f"{impact_emoji} {flag} [{ev['country']}] {ev['title']}")
        lines.append(f"   🕐 เวลา: {thai_time}")
        lines.append(f"   📊 คาดการณ์: {ev['forecast']}  |  ครั้งก่อน: {ev['previous']}")
        lines.append("")

    return "\n".join(lines).strip()

def send_telegram(text: str):
    """ส่งข้อความเข้า Telegram"""
    if not BOT_TOKEN or not CHAT_ID:
        print("Missing BOT_TOKEN or CHAT_ID")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode("utf-8")
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data))
        print("Alert sent to Telegram!")
    except Exception as e:
        print(f"Failed to send: {e}")

def main():
    from datetime import datetime
    now_thai = datetime.now(THAI_TZ).strftime("%d/%m/%Y %H:%M:%S น.")

    # ==================== TEST MODE ====================
    # ส่งข้อความทดสอบทุกครั้งที่รัน (เพื่อยืนยันว่าระบบทำงานได้)
    test_message = f"👋 สวัสดีครับ!\n\n🤖 ระบบทดสอบ Economic Calendar Alert\n🕐 เวลา: {now_thai}\n✅ ระบบทำงานปกติครับ"
    send_telegram(test_message)
    # ===================================================

    print("Fetching economic calendar...")
    events = fetch_calendar()
    print(f"Total events this week: {len(events)}")

    upcoming = get_upcoming_events(events)
    print(f"Upcoming High-Impact events in {ALERT_BEFORE_MINUTES} min: {len(upcoming)}")

    if upcoming:
        message = format_alert(upcoming)
        send_telegram(message)
    else:
        print("No high-impact events upcoming. No alert sent.")

if __name__ == "__main__":
    main()
