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

IMPACT_STARS = {
    "High":   "⭐⭐⭐",
    "Medium": "⭐⭐",
    "Low":    "⭐",
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
            "actual": (event.findtext("actual") or "").strip(),
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

def get_released_events(events: list[dict]) -> list[dict]:
    """กรองเหตุการณ์ที่เพิ่งประกาศผลจริงออกมาแล้ว (ภายใน 15 นาทีที่ผ่านมา)"""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=ALERT_BEFORE_MINUTES)

    released = []
    for ev in events:
        if ev["impact"] not in WATCH_IMPACTS:
            continue
        if WATCH_COUNTRIES and ev["country"] not in WATCH_COUNTRIES:
            continue
        # เหตุการณ์ผ่านมาแล้ว และมีตัวเลข actual
        if window_start <= ev["datetime"] <= now and ev["actual"]:
            released.append(ev)

    return released

def parse_number(s: str) -> float | None:
    """แปลงตัวเลขเช่น '0.3%', '204K' เป็น float"""
    try:
        s = s.replace("%", "").replace("K", "000").replace("M", "000000").replace(",", "").strip()
        return float(s)
    except Exception:
        return None

def format_result(events: list[dict]) -> str:
    """สร้างข้อความสรุปผลตัวเลขจริงหลังประกาศ พร้อมวิเคราะห์ผลกระทบ"""
    if not events:
        return ""

    lines = ["📢 *ผลประกาศตัวเลขเศรษฐกิจ*\n"]
    for ev in events:
        flag = COUNTRY_FLAG.get(ev["country"], "🌍")
        thai_time = ev["datetime"].astimezone(THAI_TZ).strftime("%H:%M น.")

        actual_val   = parse_number(ev["actual"])
        forecast_val = parse_number(ev["forecast"])

        # เปรียบเทียบ Actual vs Forecast
        if actual_val is not None and forecast_val is not None:
            diff = actual_val - forecast_val
            if diff > 0:
                verdict = f"🔴 สูงกว่าคาด! ({ev['actual']} vs คาด {ev['forecast']})"
            elif diff < 0:
                verdict = f"🟢 ต่ำกว่าคาด! ({ev['actual']} vs คาด {ev['forecast']})"
            else:
                verdict = f"⚪ ตรงตามคาด ({ev['actual']})"
        else:
            verdict = f"📊 ผลจริง: {ev['actual']}"

        # คำนวณระดับดาวจากความแตกต่าง Actual vs Forecast
        if actual_val is not None and forecast_val is not None and forecast_val != 0:
            pct_diff = abs((actual_val - forecast_val) / abs(forecast_val)) * 100
            if pct_diff >= 20:
                stars = "⭐⭐⭐"  # แตกต่างมากกว่า 20% = รุนแรงมาก
            elif pct_diff >= 5:
                stars = "⭐⭐"   # แตกต่าง 5-20% = ปานกลาง
            else:
                stars = "⭐"    # แตกต่างน้อยกว่า 5% = เบา
        elif actual_val is not None and forecast_val is not None:
            stars = "⭐⭐⭐" if abs(actual_val - forecast_val) > 0 else "⭐"
        else:
            stars = "⭐⭐"

        lines.append(f"{flag} {stars} [{ev['country']}] {ev['title']}")
        lines.append(f"   🕐 เวลา: {thai_time}")
        lines.append(f"   {verdict}")
        lines.append(f"   📉 ครั้งก่อน: {ev['previous']}")

        # เพิ่มคำวิเคราะห์ผลกระทบต่อตลาด
        info = get_indicator_info(ev["title"])
        if info and actual_val is not None and forecast_val is not None:
            lines.append("")
            if actual_val > forecast_val:
                lines.append(f"   {info['high_impact']}")
            else:
                lines.append(f"   {info['low_impact']}")

        lines.append("")

    return "\n".join(lines).strip()

# ==================== คำอธิบายตัวชี้วัดเศรษฐกิจ ====================
INDICATOR_INFO = {
    "cpi": {
        "name": "ดัชนีราคาผู้บริโภค (CPI)",
        "what": "วัดอัตราเงินเฟ้อ — ราคาสินค้าและบริการแพงขึ้นแค่ไหน",
        "high_impact": "🔴 ตัวเลขสูงกว่าคาด → เงินเฟ้อสูง → เฟดอาจขึ้นดอกเบี้ย → หุ้นลง, ดอลลาร์แข็ง",
        "low_impact":  "🟢 ตัวเลขต่ำกว่าคาด → เงินเฟ้อชะลอ → เฟดอาจหยุด/ลดดอกเบี้ย → หุ้นขึ้น, ทองขึ้น",
    },
    "core cpi": {
        "name": "ดัชนีราคาผู้บริโภคพื้นฐาน (Core CPI)",
        "what": "CPI ที่ตัดพลังงานและอาหารออก — สะท้อนเงินเฟ้อแท้จริง (Fed จับตาตัวนี้มากที่สุด)",
        "high_impact": "🔴 สูงกว่าคาด → เงินเฟ้อหนักกว่าที่คิด → โอกาสขึ้นดอกเบี้ย → หุ้นร่วง",
        "low_impact":  "🟢 ต่ำกว่าคาด → เงินเฟ้อชะลอตัว → หุ้นบวก, Bond Rally",
    },
    "non-farm payrolls": {
        "name": "การจ้างงานนอกภาคเกษตร (NFP)",
        "what": "จำนวนตำแหน่งงานใหม่ในสหรัฐฯ — ตัวเลขสูง = เศรษฐกิจแข็งแกร่ง",
        "high_impact": "⚡ สูงกว่าคาด → ตลาดแรงงานร้อนแรง → อาจกดดันให้เฟดคงดอกเบี้ย → ดอลลาร์แข็ง",
        "low_impact":  "📉 ต่ำกว่าคาด → ตลาดแรงงานอ่อนแอ → เฟดอาจลดดอกเบี้ย → หุ้นอาจบวก",
    },
    "gdp": {
        "name": "ผลิตภัณฑ์มวลรวมในประเทศ (GDP)",
        "what": "อัตราการเติบโตของเศรษฐกิจ — ยิ่งสูง ยิ่งดี",
        "high_impact": "🟢 สูงกว่าคาด → เศรษฐกิจดีกว่าคาด → หุ้นบวก, ดอลลาร์แข็ง",
        "low_impact":  "🔴 ต่ำกว่าคาด → เศรษฐกิจชะลอ → หุ้นลบ, อาจกระตุ้นนโยบายผ่อนคลาย",
    },
    "interest rate": {
        "name": "อัตราดอกเบี้ย (Interest Rate Decision)",
        "what": "การตัดสินใจของธนาคารกลางในการปรับอัตราดอกเบี้ย",
        "high_impact": "🔴 ขึ้นดอกเบี้ย → กู้แพงขึ้น → หุ้นลง, ค่าเงินแข็ง",
        "low_impact":  "🟢 ลดดอกเบี้ย → กระตุ้นเศรษฐกิจ → หุ้นขึ้น, ค่าเงินอ่อน",
    },
    "pmi": {
        "name": "ดัชนีผู้จัดการฝ่ายจัดซื้อ (PMI)",
        "what": "วัดสุขภาพภาคการผลิต/บริการ — เกิน 50 = ขยายตัว, ต่ำกว่า 50 = หดตัว",
        "high_impact": "🟢 สูงกว่า 50 และเกินคาด → ภาคการผลิตดี → หุ้นบวก",
        "low_impact":  "🔴 ต่ำกว่า 50 → ภาคการผลิตหดตัว → หุ้นลบ",
    },
    "retail sales": {
        "name": "ยอดค้าปลีก (Retail Sales)",
        "what": "วัดการใช้จ่ายของผู้บริโภค — ตัวชี้วัดสำคัญของเศรษฐกิจ",
        "high_impact": "🟢 สูงกว่าคาด → ผู้บริโภคจับจ่าย → เศรษฐกิจดี → หุ้นบวก",
        "low_impact":  "🔴 ต่ำกว่าคาด → ผู้บริโภคระวัง → เศรษฐกิจชะลอ",
    },
    "unemployment": {
        "name": "อัตราการว่างงาน (Unemployment Rate)",
        "what": "สัดส่วนคนที่ไม่มีงานทำ — ยิ่งต่ำยิ่งดี",
        "high_impact": "🔴 สูงกว่าคาด → คนตกงานมาก → เศรษฐกิจแย่ → หุ้นลง",
        "low_impact":  "🟢 ต่ำกว่าคาด → การจ้างงานดี → หุ้นบวก",
    },
}

def get_indicator_info(title: str) -> dict | None:
    """จับคู่ชื่อเหตุการณ์กับข้อมูลตัวชี้วัด"""
    title_lower = title.lower()
    for key, info in INDICATOR_INFO.items():
        if key in title_lower:
            return info
    return None

def format_alert(events: list[dict]) -> str:
    """สร้างข้อความแจ้งเตือนพร้อมคำอธิบายผลกระทบ"""
    if not events:
        return ""

    lines = [f"⚠️ *แจ้งเตือนปฏิทินเศรษฐกิจ* — ใน {ALERT_BEFORE_MINUTES} นาทีข้างหน้า!\n"]
    for ev in events:
        impact_emoji = IMPACT_EMOJI.get(ev["impact"], "⚪")
        stars = IMPACT_STARS.get(ev["impact"], "⭐")
        flag = COUNTRY_FLAG.get(ev["country"], "🌍")
        thai_time = ev["datetime"].astimezone(THAI_TZ).strftime("%H:%M น.")

        lines.append(f"{impact_emoji} {stars} {flag} [{ev['country']}] {ev['title']}")
        lines.append(f"   🕐 เวลา: {thai_time}")
        lines.append(f"   📊 คาดการณ์: {ev['forecast']}  |  ครั้งก่อน: {ev['previous']}")

        # เพิ่มคำอธิบายถ้าเจอตัวชี้วัดที่รู้จัก
        info = get_indicator_info(ev["title"])
        if info:
            lines.append(f"")
            lines.append(f"   📌 {info['name']}")
            lines.append(f"   💡 {info['what']}")
            lines.append(f"   {info['high_impact']}")
            lines.append(f"   {info['low_impact']}")

        lines.append("")

    return "\n".join(lines).strip()

def main():
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

    released = get_released_events(events)
    print(f"Recently released High-Impact events: {len(released)}")
    if released:
        result_message = format_result(released)
        send_telegram(result_message)
    else:
        print("No recently released events. No result alert sent.")


if __name__ == "__main__":
    main()
