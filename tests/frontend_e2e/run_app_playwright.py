import time
from pathlib import Path
from playwright.sync_api import sync_playwright

HTML_PATH = Path(__file__).parent / "harness_app.html"

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    page = browser.new_page()
    console_msgs = []
    page.on("console", lambda msg: console_msgs.append((msg.type, msg.text)))
    page.on("pageerror", lambda exc: console_msgs.append(("pageerror", str(exc))))

    page.goto(f"file://{HTML_PATH}")

    deadline = time.time() + 20
    while time.time() < deadline:
        if page.evaluate("window.__HARNESS_DONE__ === true"):
            break
        time.sleep(0.2)

    results = page.evaluate("window.__HARNESS_RESULTS__")
    browser.close()

print("=== 控制台消息（error/pageerror 应为空）===")
bad = [m for m in console_msgs if m[0] in ("error", "pageerror")]
if bad:
    for t, text in bad:
        print(f"  [{t}]", text)
else:
    print("  （无 error/pageerror）")

print()
print("=== 完整交互流程用例结果 ===")
if results is None:
    print("  未拿到结果：可能超时未完成")
else:
    all_pass = True
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        if not r["pass"]:
            all_pass = False
        print(f"  [{status}] {r['label']}")
    print()
    print("全部通过" if all_pass else "存在失败用例")
