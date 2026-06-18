import asyncio
import os
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from notebooklm import NotebookLMClient

# Load configurations from Environment Variables (provided by GitHub Secrets)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# ==================== CONFIG ====================
# คำค้นหาข่าว (ปรับเพิ่มหรือลดได้ตามต้องการ)
SEARCH_KEYWORDS = [
    "ข่าวเศรษฐกิจ",
    "หุ้นไทย",
    "ตลาดหุ้น",
    "เศรษฐกิจโลก",
    "forex",
]
MAX_URLS_PER_KEYWORD = 5   # ดึงข่าวสูงสุดกี่ URL ต่อ keyword
MAX_TOTAL_URLS = 20        # รวมทั้งหมดไม่เกินกี่ URL
# ================================================

def setup_notebooklm_auth():
    """Restores the Google authentication cookie from GitHub Secrets."""
    storage_state = os.environ.get("NOTEBOOKLM_STORAGE_STATE")
    if storage_state:
        profile_dir = Path.home() / ".notebooklm" / "profiles" / "default"
        profile_dir.mkdir(parents=True, exist_ok=True)
        storage_path = profile_dir / "storage_state.json"
        with open(storage_path, "w", encoding="utf-8") as f:
            f.write(storage_state)
        print("NotebookLM authentication state restored from secrets.")
    else:
        print("Warning: NOTEBOOKLM_STORAGE_STATE not found in environment. Login may fail.")

def fetch_google_news_urls(keyword: str, max_results: int = 5) -> list[str]:
    """ดึง URL ข่าวล่าสุดจาก Google News RSS Feed ด้วย keyword ที่กำหนด"""
    encoded_keyword = urllib.parse.quote(keyword)
    rss_url = f"https://news.google.com/rss/search?q={encoded_keyword}&hl=th&gl=TH&ceid=TH:th"
    
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            rss_data = response.read()
        
        root = ET.fromstring(rss_data)
        urls = []
        
        for item in root.findall(".//item"):
            link_el = item.find("link")
            if link_el is not None and link_el.text:
                urls.append(link_el.text.strip())
            if len(urls) >= max_results:
                break
        
        print(f"  [{keyword}]: พบ {len(urls)} URL")
        return urls
        
    except Exception as e:
        print(f"  [{keyword}]: ดึง RSS ไม่สำเร็จ - {e}")
        return []

def collect_all_news_urls() -> list[str]:
    """รวบรวม URL จากทุก keyword แล้วลบ URL ซ้ำออก"""
    print(f"\n🔍 กำลังค้นหาข่าวจาก Google News ({len(SEARCH_KEYWORDS)} keywords)...")
    all_urls = []
    seen = set()
    
    for keyword in SEARCH_KEYWORDS:
        urls = fetch_google_news_urls(keyword, MAX_URLS_PER_KEYWORD)
        for url in urls:
            if url not in seen:
                seen.add(url)
                all_urls.append(url)
            if len(all_urls) >= MAX_TOTAL_URLS:
                break
        if len(all_urls) >= MAX_TOTAL_URLS:
            break
    
    print(f"\n✅ รวบรวมได้ทั้งหมด {len(all_urls)} URL จากหลายแหล่งข่าว\n")
    return all_urls

def send_telegram_chunk(chunk):
    """Sends a single chunk of text to Telegram."""
    if not BOT_TOKEN or not CHAT_ID:
        print("Error: BOT_TOKEN or CHAT_ID is missing!")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": chunk
    }).encode('utf-8')
    
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req)
        print("Telegram message chunk sent successfully!")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")
        if hasattr(e, 'read'):
            print(f"Error Details: {e.read().decode()}")

def send_telegram_message(text):
    """Splits text if it exceeds Telegram's 4096 character limit."""
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        send_telegram_chunk(chunk)

async def main():
    setup_notebooklm_auth()
    
    # ดึง URL ข่าวแบบ Dynamic จาก Google News
    urls = collect_all_news_urls()
    
    if not urls:
        print("No URLs found.")
        send_telegram_message("⚠️ ไม่พบลิงก์ข่าวเศรษฐกิจวันนี้ครับ")
        return

    print(f"Processing {len(urls)} URLs into NotebookLM...")
    async with NotebookLMClient.from_storage() as client:
        # หา Notebook เดิม หรือสร้างใหม่
        print("Looking for existing NotebookLM...")
        notebooks = await client.notebooks.list()
        existing_nb = next((n for n in notebooks if n.title == "Daily Economic News"), None)
        
        if existing_nb:
            nb = existing_nb
            print(f"Using existing NotebookLM: {nb.id}")
            sources = await client.sources.list(nb.id)
            for s in sources:
                await client.sources.delete(nb.id, s.id)
            print("Cleared old sources from notebook.")
        else:
            print("Creating new NotebookLM...")
            nb = await client.notebooks.create("Daily Economic News")
        
        # เพิ่ม URL ทั้งหมดเข้า NotebookLM
        for url in urls:
            try:
                print(f"Adding: {url[:80]}...")
                await client.sources.add_url(nb.id, url, wait=True)
            except Exception as e:
                print(f"Skipped: {e}")
        
        print("Generating news summary...")
        instructions = "ช่วยเขียนสรุปข่าวเศรษฐกิจประจำวันจากข้อมูลทั้งหมดให้หน่อยครับ ขอเป็นภาษาไทยแบบกระชับ อ่านง่าย แบ่งเป็นข้อๆ (bullet points) ความยาวไม่เกิน 2000 ตัวอักษร เพื่อส่งเข้า Telegram"
        
        try:
            status = await client.artifacts.generate_report(
                nb.id,
                custom_prompt=instructions,
                language="th"
            )
            print("Waiting for generation...")
            await client.artifacts.wait_for_completion(nb.id, status.task_id, timeout=300.0)
            
            output_path = "temp_report.md"
            await client.artifacts.download_report(nb.id, output_path)
            
            with open(output_path, "r", encoding="utf-8") as f:
                report_content = f.read()
                
            print("Summary generated successfully!")
            final_message = f"📰 สรุปข่าวเศรษฐกิจประจำวัน\n\n{report_content}"
            send_telegram_message(final_message)
            
        except Exception as e:
            print(f"Error during generation: {e}")
            send_telegram_message(f"⚠️ เกิดข้อผิดพลาดในการสรุปข่าวเศรษฐกิจวันนี้: {e}")

if __name__ == "__main__":
    asyncio.run(main())
