import os
import sys
import json
import pyzipper
import shutil
import asyncio
import importlib.util
import threading
import time
try:
    import requests
except ImportError:
    requests = None
from playwright.async_api import async_playwright
import proxy_manager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, 'profile')
EXT_PATH = os.path.join(BASE_DIR, 'extension')
COOKIES_FILE = os.path.join(PROFILE_DIR, 'portable_cookies.json')
SESSION_FILE = "session.crsession"
MACROS_DIR = os.path.join(BASE_DIR, 'macros')

async def save_cookies_loop(context, cookies_file):
    while True:
        try:
            await asyncio.sleep(10)
            cookies = await context.cookies()
            with open(cookies_file, 'w') as f:
                json.dump(cookies, f)
        except Exception:
            break

async def save_pages_loop(context, pages_file):
    """Continuously save the list of open URLs so we can restore them next time."""
    while True:
        try:
            await asyncio.sleep(5)
            urls = [pg.url for pg in context.pages
                    if pg.url and pg.url not in ("about:blank", "chrome://newtab/", "")]
            if urls:
                with open(pages_file, 'w') as f:
                    json.dump(urls, f)
        except Exception:
            break


async def start_browser():
    # Auto-import session on first run (Useful for Hugging Face Docker deploy)
    if not os.path.exists(os.path.join(PROFILE_DIR, 'Default')) and os.path.exists(SESSION_FILE):
        print(f"Auto-importing {SESSION_FILE} into the fresh profile...")
        import_session(SESSION_FILE)

    os.makedirs(PROFILE_DIR, exist_ok=True)
    os.makedirs(EXT_PATH, exist_ok=True)
    
    LAST_PAGES_FILE = os.path.join(PROFILE_DIR, 'last_pages.json')
    
    print("Launching Portable Chromium...")
    
    # Start V2Ray/VLESS proxy if VLESS_LINK is configured
    xray_proc = proxy_manager.start_xray()
    
    async with async_playwright() as p:
        args = [
            f"--load-extension={EXT_PATH}",
            "--disable-blink-features=AutomationControlled",
            # No --restore-last-session: we handle page restore ourselves
        ]
        
        # Route all browser traffic through local SOCKS5 if xray is running
        if xray_proc and xray_proc.poll() is None:
            args.append("--proxy-server=socks5://127.0.0.1:1080")
            print("[Browser] Traffic routed through VLESS proxy.")

        # ignore_default_args must include --disable-extensions so our --load-extension works
        IGNORE_ARGS = ["--enable-automation", "--disable-extensions"]

        try:
            # First try using native Google Chrome (allows Chrome Web Store extensions)
            context = await p.chromium.launch_persistent_context(
                PROFILE_DIR,
                channel="chrome",
                headless=False,
                args=args,
                ignore_default_args=IGNORE_ARGS,
                viewport=None,
            )
        except Exception:
            # Fallback to standard Chromium (e.g. inside Docker)
            context = await p.chromium.launch_persistent_context(
                PROFILE_DIR,
                headless=False,
                args=args,
                ignore_default_args=IGNORE_ARGS,
                viewport=None,
            )
        
        # Load portable cookies if they exist
        if os.path.exists(COOKIES_FILE):
            print("Loading extracted portable cookies...")
            try:
                with open(COOKIES_FILE, 'r') as f:
                    cookies = json.load(f)
                    await context.add_cookies(cookies)
            except Exception as e:
                print(f"Warning: Failed to load cookies: {e}")
        
        # Background tasks to continuously save cookies and open pages
        asyncio.create_task(save_cookies_loop(context, COOKIES_FILE))
        asyncio.create_task(save_pages_loop(context, LAST_PAGES_FILE))

        # Restore last open pages from our own saved file
        if os.path.exists(LAST_PAGES_FILE):
            try:
                with open(LAST_PAGES_FILE, 'r') as f:
                    last_urls = json.load(f)
                if last_urls:
                    print(f"Restoring {len(last_urls)} page(s) from last session...")
                    # Use the first URL in the existing blank tab (avoids closing last tab)
                    existing_pages = list(context.pages)
                    first_url = last_urls[0]
                    remaining_urls = last_urls[1:]
                    # Navigate the first existing page instead of closing it
                    if existing_pages:
                        try:
                            await existing_pages[0].goto(first_url, wait_until="domcontentloaded", timeout=15000)
                        except Exception as e:
                            print(f"Warning: Could not restore {first_url}: {e}")
                    # Open remaining URLs in new tabs
                    for url in remaining_urls:
                        try:
                            pg = await context.new_page()
                            await pg.goto(url, wait_until="domcontentloaded", timeout=15000)
                        except Exception as e:
                            print(f"Warning: Could not restore {url}: {e}")
            except Exception as e:
                print(f"Warning: Could not restore pages: {e}")
        # else: no saved pages, just leave the about:blank tab as is (Chrome is happy)
                
        print("Browser started successfully!")
        print("Close all browser windows to stop the session.")

            
        # Wait for all pages to close
        try:
            while len(context.pages) > 0:
                await asyncio.sleep(1)
        except Exception:
            pass
            
        print("Browser windows closed. Saving final data...")
        try:
            cookies = await context.cookies()
            with open(COOKIES_FILE, 'w') as f:
                json.dump(cookies, f)
        except Exception:
            pass
        print("Session finalized.")

        
        # Stop xray proxy
        if xray_proc and xray_proc.poll() is None:
            xray_proc.terminate()
            print("[Proxy] xray stopped.")


async def execute_macro(context, macro_name):
    """Load and execute a macro script from the macros/ directory."""
    macro_path = os.path.join(MACROS_DIR, f'{macro_name}.py')
    
    if not os.path.exists(macro_path):
        print(f"❌ Macro not found: {macro_path}")
        print(f"Available macros:")
        if os.path.exists(MACROS_DIR):
            for f in os.listdir(MACROS_DIR):
                if f.endswith('.py') and f != '__init__.py':
                    print(f"  - {f[:-3]}")
        return False
    
    print(f"🔧 Loading macro: {macro_name}")
    try:
        spec = importlib.util.spec_from_file_location(macro_name, macro_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        if not hasattr(module, 'run'):
            print(f"❌ Macro '{macro_name}' is missing the required 'async def run(context, page)' function!")
            return False
        
        # Get or create a page for the macro
        page = context.pages[0] if context.pages else await context.new_page()
        
        print(f"▶️ Running macro: {macro_name}")
        await module.run(context, page)
        print(f"✅ Macro '{macro_name}' completed successfully.")
        return True
        
    except Exception as e:
        print(f"❌ Macro '{macro_name}' failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


# ==========================================
# Telegram Screenshot Bot
# ==========================================
def telegram_screenshot_bot(context_pages_getter, stop_event, main_loop):
    """
    Background thread: polls Telegram for messages.
    When a message is received, takes a screenshot of the active page and sends it back.
    main_loop: the asyncio event loop from the main thread.
    """
    if not requests:
        print("[Telegram] requests library not installed, skipping bot.")
        return
    
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not bot_token:
        print("[Telegram] No TELEGRAM_BOT_TOKEN set, skipping bot.")
        return
    
    api = f"https://api.telegram.org/bot{bot_token}"
    last_update_id = 0
    
    print("[Telegram] Screenshot bot started! Send any message to get a screenshot.")
    
    while not stop_event.is_set():
        try:
            resp = requests.get(f"{api}/getUpdates", params={
                "offset": last_update_id + 1,
                "timeout": 5
            }, timeout=10)
            
            if resp.status_code != 200:
                time.sleep(3)
                continue
            
            updates = resp.json().get('result', [])
            
            for update in updates:
                last_update_id = update['update_id']
                msg = update.get('message', {})
                chat_id = msg.get('chat', {}).get('id')
                
                if not chat_id:
                    continue
                
                # Take screenshot
                try:
                    screenshot_path = os.path.join(BASE_DIR, '_telegram_screenshot.png')
                    pages = context_pages_getter()
                    
                    if pages:
                        # Use the main thread's event loop to take screenshot
                        future = asyncio.run_coroutine_threadsafe(
                            pages[0].screenshot(path=screenshot_path, full_page=False),
                            main_loop
                        )
                        future.result(timeout=10)
                        
                        # Send screenshot
                        with open(screenshot_path, 'rb') as photo:
                            requests.post(f"{api}/sendPhoto", data={
                                "chat_id": chat_id,
                                "caption": f"📸 Browser Screenshot\n🕐 {time.strftime('%H:%M:%S')}"
                            }, files={"photo": photo}, timeout=15)
                        
                        print(f"[Telegram] Screenshot sent to chat {chat_id}")
                    else:
                        requests.post(f"{api}/sendMessage", data={
                            "chat_id": chat_id,
                            "text": "⚠️ No browser pages open right now."
                        }, timeout=10)
                        
                except Exception as e:
                    print(f"[Telegram] Screenshot error: {e}")
                    try:
                        requests.post(f"{api}/sendMessage", data={
                            "chat_id": chat_id,
                            "text": f"❌ Failed to take screenshot: {e}"
                        }, timeout=10)
                    except:
                        pass
        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            print(f"[Telegram] Bot error: {e}")
            time.sleep(5)
    
    print("[Telegram] Bot stopped.")


def send_telegram_screenshot_sync(page, caption=""):
    """Send a one-off screenshot to all recent chat IDs (used for initial notification)."""
    if not requests:
        return
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not bot_token or not chat_id:
        return
    
    try:
        api = f"https://api.telegram.org/bot{bot_token}"
        screenshot_path = os.path.join(BASE_DIR, '_telegram_screenshot.png')
        
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                page.screenshot(path=screenshot_path, full_page=False),
                loop
            )
            future.result(timeout=10)
        
        with open(screenshot_path, 'rb') as photo:
            requests.post(f"{api}/sendPhoto", data={
                "chat_id": chat_id,
                "caption": caption or f"📸 Browser Screenshot\n🕐 {time.strftime('%H:%M:%S')}"
            }, files={"photo": photo}, timeout=15)
        print(f"[Telegram] Initial screenshot sent.")
    except Exception as e:
        print(f"[Telegram] Failed to send initial screenshot: {e}")


async def run_action():
    """
    GitHub Actions mode: runs browser in headed mode (xvfb provides display),
    executes a macro if specified, then exports the session.
    """
    # Auto-import session if exists and profile is fresh
    if os.path.exists(SESSION_FILE) and not os.path.exists(os.path.join(PROFILE_DIR, 'Default')):
        print(f"📦 Importing session from {SESSION_FILE}...")
        import_session(SESSION_FILE)
    
    os.makedirs(PROFILE_DIR, exist_ok=True)
    os.makedirs(EXT_PATH, exist_ok=True)
    
    duration_mins = int(os.environ.get('SESSION_DURATION', '10'))
    macro_name = os.environ.get('MACRO_NAME', '').strip()
    
    print(f"🚀 Starting GitHub Actions browser session...")
    print(f"   Duration: {duration_mins} minutes")
    print(f"   Macro: {macro_name if macro_name else 'None (session only)'}")
    
    # Start V2Ray/VLESS proxy if configured
    xray_proc = proxy_manager.start_xray()
    
    async with async_playwright() as p:
        args = [
            f"--load-extension={EXT_PATH}",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        
        # Route through proxy if xray is running
        if xray_proc and xray_proc.poll() is None:
            args.append("--proxy-server=socks5://127.0.0.1:1080")
            print("[Browser] Traffic routed through VLESS proxy.")
        
        IGNORE_ARGS = ["--enable-automation", "--disable-extensions"]
        
        context = await p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,  # Headed mode - xvfb provides virtual display
            args=args,
            ignore_default_args=IGNORE_ARGS,
            viewport={"width": 1280, "height": 800},
        )
        
        # Load portable cookies if they exist
        if os.path.exists(COOKIES_FILE):
            print("🍪 Loading portable cookies...")
            try:
                with open(COOKIES_FILE, 'r') as f:
                    cookies = json.load(f)
                    await context.add_cookies(cookies)
            except Exception as e:
                print(f"Warning: Failed to load cookies: {e}")
        
        # Start Telegram screenshot bot in background
        telegram_stop = threading.Event()
        main_loop = asyncio.get_event_loop()
        telegram_thread = threading.Thread(
            target=telegram_screenshot_bot,
            args=(lambda: list(context.pages), telegram_stop, main_loop),
            daemon=True
        )
        telegram_thread.start()
        
        # Execute macro if specified
        if macro_name:
            await execute_macro(context, macro_name)
        else:
            # No macro - keep browser alive for the specified duration
            print(f"⏳ No macro specified. Keeping session alive for {duration_mins} minutes...")
            # Restore last pages
            LAST_PAGES_FILE = os.path.join(PROFILE_DIR, 'last_pages.json')
            if os.path.exists(LAST_PAGES_FILE):
                try:
                    with open(LAST_PAGES_FILE, 'r') as f:
                        last_urls = json.load(f)
                    if last_urls:
                        print(f"Restoring {len(last_urls)} page(s)...")
                        existing_pages = list(context.pages)
                        if existing_pages and last_urls:
                            try:
                                await existing_pages[0].goto(last_urls[0], wait_until="domcontentloaded", timeout=30000)
                            except Exception:
                                pass
                        for url in last_urls[1:]:
                            try:
                                pg = await context.new_page()
                                await pg.goto(url, wait_until="domcontentloaded", timeout=30000)
                            except Exception:
                                pass
                except Exception:
                    pass
            
            # Send initial screenshot after pages are restored
            await asyncio.sleep(5)  # Wait for pages to load
            if context.pages:
                try:
                    await context.pages[0].screenshot(path=os.path.join(BASE_DIR, '_telegram_screenshot.png'), full_page=False)
                    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
                    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
                    if bot_token and chat_id and requests:
                        api = f"https://api.telegram.org/bot{bot_token}"
                        with open(os.path.join(BASE_DIR, '_telegram_screenshot.png'), 'rb') as photo:
                            requests.post(f"{api}/sendPhoto", data={
                                "chat_id": chat_id,
                                "caption": f"🚀 Browser started on GitHub Actions!\n🕐 {time.strftime('%H:%M:%S')}\n📄 Pages: {len(context.pages)}"
                            }, files={"photo": photo}, timeout=15)
                        print("[Telegram] Initial screenshot sent!")
                except Exception as e:
                    print(f"[Telegram] Initial screenshot failed: {e}")
            
            # Stay alive for the requested duration
            await asyncio.sleep(duration_mins * 60)
        
        # Stop telegram bot
        telegram_stop.set()
        
        # Save cookies before closing
        print("💾 Saving session data...")
        try:
            cookies = await context.cookies()
            with open(COOKIES_FILE, 'w') as f:
                json.dump(cookies, f)
            print("Cookies saved.")
        except Exception:
            pass
        
        # Save open pages
        try:
            LAST_PAGES_FILE = os.path.join(PROFILE_DIR, 'last_pages.json')
            urls = [pg.url for pg in context.pages
                    if pg.url and pg.url not in ("about:blank", "chrome://newtab/", "")]
            if urls:
                with open(LAST_PAGES_FILE, 'w') as f:
                    json.dump(urls, f)
                print(f"Saved {len(urls)} open page(s).")
        except Exception:
            pass
        
        await context.close()
    
    # Stop proxy
    if xray_proc and xray_proc.poll() is None:
        xray_proc.terminate()
        print("[Proxy] xray stopped.")
    
    # Export session for next run
    print("📤 Exporting session for next run...")
    export_session()
    print("🎉 GitHub Actions session completed successfully!")



def export_session():
    import getpass
    print(f"Exporting session to {SESSION_FILE}...")
    if not os.path.exists(PROFILE_DIR):
        print("Error: No profile found. Please start the browser first.")
        return
        
    # Clean up unnecessary cache files to save space
    cache_dirs = [
        os.path.join(PROFILE_DIR, 'Default', 'Cache'),
        os.path.join(PROFILE_DIR, 'Default', 'Code Cache'),
        os.path.join(PROFILE_DIR, 'Default', 'GPUCache')
    ]
    for d in cache_dirs:
        if os.path.exists(d):
            try:
                shutil.rmtree(d)
                print(f"Cleaned cache: {d}")
            except Exception:
                pass

    try:
        password = os.environ.get("SESSION_PASSWORD", "")
        if not password and sys.stdin.isatty():
            password = getpass.getpass("Enter a strong password to encrypt the session (or press Enter to skip encryption): ")
            
        use_encryption = bool(password.strip())
        
        with pyzipper.AESZipFile(SESSION_FILE, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES if use_encryption else None) as zipf:
            if use_encryption:
                zipf.setpassword(password.encode('utf-8'))
            for root, dirs, files in os.walk(PROFILE_DIR):
                for file in files:
                    # Ignore active lock files
                    if file in ["lockfile", "SingletonLock"] or file.endswith(".lock"):
                        continue
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, PROFILE_DIR)
                    try:
                        zipf.write(file_path, arcname)
                    except Exception:
                        pass # Ignore locked files
        if use_encryption:
            print(f"Success! Session safely ENCRYPTED and exported to: {os.path.abspath(SESSION_FILE)}")
            print("IMPORTANT: Add an Environment Secret named SESSION_PASSWORD in Hugging Face with your password!")
        else:
            print(f"Success! Session exported (Unencrypted) to: {os.path.abspath(SESSION_FILE)}")
    except Exception as e:
        print(f"Error during export: {e}")

def import_session(filepath):
    print(f"Importing session from {filepath}...")
    if not os.path.exists(filepath):
        print("Error: File not found.")
        return
    
    # clear existing profile
    if os.path.exists(PROFILE_DIR):
        print("Clearing old profile...")
        try:
            shutil.rmtree(PROFILE_DIR)
        except Exception as e:
            print(f"Error: Could not clear existing profile. Please make sure the browser is closed. ({e})")
            return
            
    os.makedirs(PROFILE_DIR, exist_ok=True)
    
    try:
        with pyzipper.AESZipFile(filepath, 'r') as zipf:
            password = os.environ.get("SESSION_PASSWORD")
            
            if not password and sys.stdin.isatty():
                import getpass
                password = getpass.getpass("If this session is encrypted, enter password (or press Enter if none): ")
                
            if password:
                zipf.setpassword(password.encode('utf-8'))
                
            zipf.extractall(PROFILE_DIR)
        print("Success! Profile imported. You can now run 'python main.py start'.")
    except RuntimeError as e:
        if 'password' in str(e).lower() or 'encrypted' in str(e).lower() or 'bad password' in str(e).lower():
            print("Error: The session file is encrypted with a password (or the wrong password was used).")
            print("Please set the SESSION_PASSWORD environment variable or Secret in Hugging Face!")
            shutil.rmtree(PROFILE_DIR, ignore_errors=True)
        else:
            print(f"Error during import: {e}")
            shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    except Exception as e:
        print(f"Error during import: {e}")
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("================ Portable Chromium Manager ================")
        print("Usage:")
        print("  python main.py start     - Launches the browser")
        print("  python main.py export    - Exports your session to a file")
        print("  python main.py import <file.crsession> - Loads a session")
        sys.exit(1)
        
    cmd = sys.argv[1].lower()
    if cmd == "start":
        # Check if playwright was installed
        try:
            asyncio.run(start_browser())
        except Exception as e:
            print(f"Error starting browser: {e}")
            if "playwright" in str(e).lower() or "executable" in str(e).lower():
                print("Make sure you install playwright and its browsers:")
                print("pip install -r requirements.txt")
                print("playwright install chromium")
    elif cmd == "export":
        export_session()
    elif cmd == "import":
        if len(sys.argv) < 3:
            print("Error: Missing filepath. Usage: python main.py import <file.crsession>")
            sys.exit(1)
        import_session(sys.argv[2])
    elif cmd == "run-action":
        # GitHub Actions mode
        try:
            asyncio.run(run_action())
        except Exception as e:
            print(f"Error in GitHub Actions mode: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        print(f"Unknown command: {cmd}")
