from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Standard modern mobile screen (iPhone 12/13/14 viewport: 390 x 844)
        context = browser.new_context(viewport={'width': 390, 'height': 844})
        page = context.new_page()

        print("1. Logging in as student...")
        page.goto('http://127.0.0.1:5000/login', wait_until='domcontentloaded')
        page.fill('input[name="email"]', 'qatest223-35-999@diu.edu.bd')
        page.fill('input[name="password"]', 'StudentPass123!')
        page.click('button[type="submit"]')
        page.wait_for_url('**/customer/**', timeout=10000)

        print("2. Navigating to leaderboard...")
        page.goto('http://127.0.0.1:5000/customer/leaderboard', wait_until='networkidle')
        page.wait_for_timeout(1000)

        # Verify cards exist
        cards = page.locator('.dashboard-card')
        print(f"Total dashboard-cards found: {cards.count()}")
        assert cards.count() >= 3, "Expected at least 3 cards (High Risk, Safest, Risk Distribution)"

        # Scroll to High Risk & Safest cards section
        high_risk_card = page.locator('.dashboard-card.board-high')
        high_risk_card.scroll_into_view_if_needed()
        page.wait_for_timeout(500)

        # Capture screenshot of lower cards in mobile view
        screenshot_path = r"C:\Users\soura\.gemini\antigravity\brain\4402173e-4c53-4843-ac83-92101b40d4b3\customer_leaderboard_compact_mobile.png"
        page.screenshot(path=screenshot_path, full_page=False)
        print(f"[OK] Saved compact view screenshot to {screenshot_path}")

        # Check scroll width vs client width on table-responsive containers to ensure NO horizontal overflow
        table_responsives = page.locator('.table-responsive')
        for i in range(table_responsives.count()):
            tr_el = table_responsives.nth(i)
            scroll_width = tr_el.evaluate("el => el.scrollWidth")
            client_width = tr_el.evaluate("el => el.clientWidth")
            print(f"Table {i}: scrollWidth={scroll_width}, clientWidth={client_width}")
            # scrollWidth should equal or be practically equal to clientWidth (<= clientWidth + 2 for fractional rounding)
            assert scroll_width <= client_width + 2, f"Table {i} has horizontal scrollbar: scrollWidth {scroll_width} > clientWidth {client_width}"

        # Scroll down to capture the cards and the chart nicely
        page.evaluate("window.scrollTo(0, 420)")
        page.wait_for_timeout(500)
        scroll_screenshot = r"C:\Users\soura\.gemini\antigravity\brain\4402173e-4c53-4843-ac83-92101b40d4b3\customer_leaderboard_cards_scroll.png"
        page.screenshot(path=scroll_screenshot, full_page=False)
        print(f"[OK] Saved scrolled cards view screenshot to {scroll_screenshot}")

        browser.close()
        print("=== MOBILE LEADERBOARD COMPACT CARDS VERIFIED SUCCESSFULLY! ===")

if __name__ == "__main__":
    run()
