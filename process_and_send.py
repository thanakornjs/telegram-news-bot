import asyncio
import os
import sys
import urllib.request
import urllib.parse
from pathlib import Path
from notebooklm import NotebookLMClient

# Load configurations from Environment Variables (provided by GitHub Secrets)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def setup_notebooklm_auth():
    """Restores the Google authentication cookie from GitHub Secrets so NotebookLM works headlessly."""
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
    
    urls = sys.argv[1:]
    if not urls:
        print("No URLs provided.")
        return

    print(f"Processing {len(urls)} URLs...")
    async with NotebookLMClient.from_storage() as client:
        print("Creating NotebookLM...")
        nb = await client.notebooks.create("Daily Economic News")
        
        for url in urls:
            try:
                print(f"Adding source: {url}")
                await client.sources.add_url(nb.id, url, wait=True)
            except Exception as e:
                print(f"Failed to add {url}: {e}")
        
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
            final_message = f"📰 *สรุปข่าวเศรษฐกิจประจำวัน*\n\n{report_content}"
            send_telegram_message(final_message)
            
        except Exception as e:
            print(f"Error during generation: {e}")
            send_telegram_message(f"⚠️ เกิดข้อผิดพลาดในการสรุปข่าวเศรษฐกิจวันนี้: {e}")

if __name__ == "__main__":
    asyncio.run(main())
