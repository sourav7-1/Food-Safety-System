from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Mobile view (390 x 844)
        context = browser.new_context(viewport={'width': 390, 'height': 844})
        page = context.new_page()

        print("1. Logging in as student...")
        page.goto('http://127.0.0.1:5000/login', wait_until='domcontentloaded')
        page.fill('input[name="email"]', 'qatest223-35-999@diu.edu.bd')
        page.fill('input[name="password"]', 'StudentPass123!')
        page.click('button[type="submit"]')
        page.wait_for_url('**/customer/**', timeout=10000)

        print("2. Opening mobile sidebar drawer...")
        page.wait_for_selector('button[data-bs-target="#portalSidebar"]', timeout=5000)
        page.click('button[data-bs-target="#portalSidebar"]')
        page.wait_for_selector('#portalSidebar.show', timeout=5000)
        page.wait_for_timeout(600)

        # Check navigation links
        nav = page.locator('#portalSidebar .dashboard-nav')
        home_links = nav.locator('a:has-text("Home")')
        print(f"Home links count in sidebar nav: {home_links.count()}")
        assert home_links.count() == 0, "Home link should be completely removed from sidebar"

        # Check other links are present
        assert nav.locator('a:has-text("Dashboard")').count() > 0
        assert nav.locator('a:has-text("Find Stalls")').count() > 0
        assert nav.locator('a:has-text("Leaderboard")').count() > 0

        # Capture mobile sidebar screenshot
        screenshot_path = r"C:\Users\soura\.gemini\antigravity\brain\4402173e-4c53-4843-ac83-92101b40d4b3\customer_sidebar_mobile.png"
        page.screenshot(path=screenshot_path, full_page=False)
        print(f"[OK] Saved screenshot to {screenshot_path}")

        browser.close()
        print("=== SIDEBAR HOME REMOVAL VERIFIED SUCCESSFULLY! ===")

if __name__ == "__main__":
    run()
