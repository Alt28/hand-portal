"""Optional browser smoke check. Start web_app.py first; uses a fake camera."""
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUTPUT = ROOT / "preview"

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=True, args=[
        "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
    context = browser.new_context(viewport={"width": 1440, "height": 1100})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(URL)
    expect(page.get_by_role("button", name="Start camera", exact=True)).to_be_enabled()
    expect(page.locator(".effect-button")).to_have_count(13)
    page.screenshot(path=str(OUTPUT / "web-studio.png"), full_page=True)
    page.get_by_role("button", name="Try demo", exact=True).click()
    expect(page.locator("#status")).to_have_text("Demo running", timeout=20000)
    expect(page.locator("#output")).to_be_visible()
    page.get_by_role("button", name="Rainbow Disco", exact=True).click()
    expect(page.locator("#overlay-name")).to_have_text("Rainbow Disco")
    page.get_by_role("button", name="5-second timer", exact=True).click()
    expect(page.locator("#mode-readout")).to_have_text("Timer")
    expect(page.locator("#overlay-name")).to_have_text("Fisheye", timeout=15000)
    page.get_by_role("button", name="Hand gesture", exact=True).click()
    expect(page.locator("#output")).to_have_attribute("data-mode", "gesture")
    page.get_by_role("button", name="RGB Glitch", exact=True).click()
    expect(page.locator("#overlay-name")).to_have_text("RGB Glitch")
    expect(page.locator("#output")).to_have_attribute("data-effect", "6")
    page.screenshot(path=str(OUTPUT / "web-demo.png"), full_page=True)
    with page.expect_download() as downloaded:
        page.get_by_role("button", name="Save snapshot", exact=True).click()
    assert downloaded.value.suggested_filename.endswith('.jpg')
    page.get_by_role("button", name="Stop", exact=True).click()
    expect(page.locator("#status")).to_have_text("Camera off")
    expect(page.get_by_role("button", name="Save snapshot", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Start camera", exact=True).click()
    expect(page.locator("#live-label")).to_have_text("LIVE CAMERA", timeout=30000)
    expect(page.locator("#hands")).to_have_text("0 / 2")
    page.get_by_role("button", name="Stop", exact=True).click()
    assert page.locator('#camera').evaluate('(video) => video.srcObject === null')
    expect(page.locator("#status")).to_have_text("Camera off")
    # Verify a second start after cleanup, then shut down the fake camera.
    page.get_by_role("button", name="Start camera", exact=True).click()
    expect(page.locator("#live-label")).to_have_text("LIVE CAMERA", timeout=30000)
    page.get_by_role("button", name="Stop", exact=True).click()
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(OUTPUT / "web-mobile.png"), full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert not errors, errors
    browser.close()
    print("PASS: demo, 13 effects, timer, selection, snapshot, synthetic camera, restart, stop, mobile layout")
