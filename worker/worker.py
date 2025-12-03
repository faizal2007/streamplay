import os
import asyncio
import base64
import json
from playwright.async_api import async_playwright
import socketio
from dotenv import load_dotenv

load_dotenv()

SOCKETIO_SERVER = os.getenv("SOCKETIO_SERVER", "http://localhost:5000")

sio = socketio.AsyncClient()

# Keep per-session state
SESSIONS = {}

@sio.event
async def connect():
    print("Worker connected to server")
    # register as a worker (room 'workers' on server)
    await sio.emit("register_worker", {"name": "worker-1"})

@sio.event
async def disconnect():
    print("Disconnected from server")

# Server tells workers to start a session
@sio.on("start_session")
async def on_start_session(data):
    session_id = data.get("id")
    url = data.get("url")
    viewport = data.get("viewport", {"width": 1280, "height": 720})
    print(f"Received start_session {session_id} -> {url}")
    # Spawn a task to run Playwright for this session
    if session_id in SESSIONS:
        print("Session already running:", session_id)
        return
    task = asyncio.create_task(run_session(session_id, url, viewport))
    SESSIONS[session_id] = {"task": task}

# Receive forwarded client events to act upon (click/type)
@sio.on("event")
async def on_event(data):
    session_id = data.get("session_id")
    action = data.get("action")
    if not session_id or session_id not in SESSIONS:
        return
    page = SESSIONS[session_id].get("page")
    if not page:
        return
    # Basic actions
    try:
        if action.get("type") == "click":
            selector = action.get("selector")
            if selector:
                await page.click(selector)
        elif action.get("type") == "type":
            selector = action.get("selector")
            value = action.get("value", "")
            if selector:
                await page.fill(selector, value)
        elif action.get("type") == "eval":
            js = action.get("script", "")
            await page.evaluate(js)
    except Exception as e:
        print("Error performing action:", e)
        # capture screenshot on action error
        try:
            data = await page.screenshot(type='png')
            b64 = base64.b64encode(data).decode()
            await sio.emit("frame", {"session_id": session_id, "data": b64, "error": str(e)})
        except Exception:
            pass

async def run_session(session_id, url, viewport):
    print(f"Starting session {session_id} -> {url}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport=viewport)
            page = await context.new_page()
            SESSIONS[session_id]["page"] = page

            # Hook console errors
            page.on("console", lambda msg: print(f"[console][{session_id}]", msg.type, msg.text))
            page.on("pageerror", lambda exc: asyncio.create_task(handle_page_error(session_id, exc, page)))

            await page.goto(url, timeout=45000)
            # Periodically screenshot and send frames
            while True:
                try:
                    data = await page.screenshot(type="png")
                    b64 = base64.b64encode(data).decode()
                    await sio.emit("frame", {"session_id": session_id, "data": b64})
                except Exception as e:
                    print("screenshot error:", e)
                    # send an error payload with screenshot if possible
                    try:
                        data = await page.screenshot(type="png")
                        b64 = base64.b64encode(data).decode()
                        await sio.emit("frame", {"session_id": session_id, "data": b64, "error": str(e)})
                    except Exception:
                        pass
                await asyncio.sleep(1)  # 1 fps default; adjust as needed
    except Exception as e:
        print("Session failed:", e)
    finally:
        SESSIONS.pop(session_id, None)
        print("Session ended", session_id)

async def handle_page_error(session_id, exc, page):
    print("Page error:", exc)
    try:
        data = await page.screenshot(type='png')
        b64 = base64.b64encode(data).decode()
        await sio.emit("frame", {"session_id": session_id, "data": b64, "error": str(exc)})
    except Exception as e:
        print("failed screenshot on page error:", e)

async def main():
    await sio.connect(SOCKETIO_SERVER, transports=["websocket"], socketio_path="/socket.io", query={"role":"worker"})
    await sio.wait()

if __name__ == "__main__":
    asyncio.run(main())