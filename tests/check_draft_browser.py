"""Optional browser smoke check: python tests/check_draft_browser.py [HTML path].
Requires local Chrome/Edge and the installed websockets package. No server or API key needed.
"""
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from websockets.sync.client import connect


def main():
    root = Path(__file__).resolve().parent.parent
    html = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / "output/draft_1040sr.html"
    candidates = [os.getenv("SILVERFILE_BROWSER", ""),
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
    browser = next((p for p in candidates if p and Path(p).is_file()), None)
    if not browser or not html.is_file():
        raise SystemExit("Provide a local browser and generate the HTML draft first.")
    profile = root / "output" / f"browser-check-{os.getpid()}"
    profile.mkdir(parents=True)
    process = subprocess.Popen([browser, "--headless=new", "--disable-gpu", "--no-first-run",
                                "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for _ in range(100):
            if (profile / "DevToolsActivePort").exists():
                break
            time.sleep(.1)
        port = (profile / "DevToolsActivePort").read_text().splitlines()[0]
        with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
            page = next(p for p in json.load(response) if p["type"] == "page")
        with connect(page["webSocketDebuggerUrl"], max_size=20_000_000) as socket:
            sequence = 0
            def call(method, params=None):
                nonlocal sequence
                sequence += 1
                socket.send(json.dumps({"id": sequence, "method": method, "params": params or {}}))
                while True:
                    result = json.loads(socket.recv(timeout=10))
                    if result.get("id") == sequence:
                        if "error" in result:
                            raise RuntimeError(result["error"])
                        return result.get("result", {})
            def evaluate(expression):
                return call("Runtime.evaluate", {"expression": expression, "returnByValue": True})["result"].get("value")
            call("Page.enable")
            call("Page.navigate", {"url": html.as_uri()})
            for _ in range(100):
                if evaluate("document.readyState === 'complete' && !!document.querySelector('summary')"):
                    break
                time.sleep(.1)
            assert evaluate("!!document.querySelector('summary')"), "No monetary disclosure control"
            assert evaluate("!document.querySelector('details').open")
            call("Page.bringToFront")
            evaluate("document.querySelector('summary').focus()")
            assert evaluate("document.activeElement.tagName === 'SUMMARY'"), "Summary did not receive focus"
            call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"})
            call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            assert evaluate("document.querySelector('details').open"), "Keyboard did not open provenance"
            assert evaluate("document.querySelector('details li p').getBoundingClientRect().height > 0")
            assert evaluate("document.querySelector('details pre').textContent.includes('record_source')")
            assert evaluate("document.querySelector('summary').title.includes('W-2')")
            call("Input.dispatchKeyEvent", {"type": "keyDown", "key": " ", "code": "Space", "windowsVirtualKeyCode": 32, "text": " "})
            call("Input.dispatchKeyEvent", {"type": "keyUp", "key": " ", "code": "Space", "windowsVirtualKeyCode": 32})
            assert evaluate("!document.querySelector('details').open"), "Space did not close provenance"
            box = evaluate("JSON.stringify(document.querySelector('summary').getBoundingClientRect().toJSON())")
            bounds = json.loads(box)
            point = {"x": bounds["x"] + 20, "y": bounds["y"] + bounds["height"] / 2, "button": "left", "clickCount": 1}
            call("Input.dispatchMouseEvent", {"type": "mousePressed", **point})
            call("Input.dispatchMouseEvent", {"type": "mouseReleased", **point})
            assert evaluate("document.querySelector('details').open"), "Click did not open provenance"
            shot = call("Page.captureScreenshot", {"format": "png"})["data"]
            (root / "output" / "draft-browser.png").write_bytes(base64.b64decode(shot))
            call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
            assert evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Mobile horizontal overflow"
            print("Browser checks passed: keyboard disclosure, visible provenance, 390px layout. Screenshot: output/draft-browser.png")
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()
