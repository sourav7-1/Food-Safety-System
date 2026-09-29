from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 960})
        page = context.new_page()

        print("1. Logging in...")
        page.goto('http://127.0.0.1:5000/login', wait_until='domcontentloaded')
        page.fill('input[name="email"]', 'qa-admin@diu.edu.bd')
        page.fill('input[name="password"]', 'AdminPass123!')
        page.click('button[type="submit"]')
        page.wait_for_url('**/admin**', timeout=10000)

        print("2. Navigating to /admin/inspections...")
        page.goto('http://127.0.0.1:5000/admin/inspections', wait_until='domcontentloaded')
        page.wait_for_selector('.stall-stats-grid', timeout=10000)
        page.wait_for_timeout(1000)

        # 1. Verify clickable cards exist
        cards = page.locator(".stall-stat-card.clickable-stat-card")
        assert cards.count() == 4, f"Expected 4 clickable cards, found {cards.count()}"
        print("[OK] Verified 4 clickable stat cards exist")

        # 2. Test Card 1: Total Audits modal
        print("3. Clicking Card 1 (Total Audits)...")
        cards.nth(0).click()
        page.wait_for_selector("#inspectionMetricModal.show", timeout=5000)
        page.wait_for_timeout(800)
        title = page.locator("#inspectionMetricModalLabel").inner_text()
        badge = page.locator("#inspectionMetricBadge").inner_text()
        items = page.locator("#inspectionMetricList .metric-inspection-item")
        print(f"[OK] Total Audits Modal opened: Title='{title}', Badge='{badge}', Items Count={items.count()}")
        assert "All Safety Audits" in title
        assert "TOTAL AUDITS" in badge
        assert items.count() > 0

        # Capture screenshot of Total Audits modal
        page.screenshot(path=r"C:\Users\soura\.gemini\antigravity\brain\4402173e-4c53-4843-ac83-92101b40d4b3\inspections_metric_modal.png", full_page=False)
        print("[OK] Saved screenshot inspections_metric_modal.png")

        # 3. Test In-Modal Real-Time Search
        print("4. Testing real-time search inside modal...")
        page.fill("#inspectionMetricSearch", "cafe")
        page.wait_for_timeout(300)
        filtered_count = page.locator("#inspectionMetricList .metric-inspection-item").count()
        print(f"[OK] In-modal search for 'cafe' yielded {filtered_count} items")
        page.fill("#inspectionMetricSearch", "")
        page.wait_for_timeout(300)

        # 4. Test clicking an item to open Deep Inspection Details and navigating Back
        print("5. Clicking inspection item inside modal to open deep audit detail...")
        items.first.click()
        page.wait_for_selector("#adminItemDetailModal.show .floating-window-content", timeout=8000)
        page.wait_for_timeout(800)
        print("[OK] Deep audit detail modal opened!")

        # Verify Back button exists and is visible
        back_btn = page.locator("#adminItemBackBtn")
        assert back_btn.is_visible(), "Back button must be visible"
        print("[OK] Back button is visible. Clicking Back button...")
        back_btn.click()
        page.wait_for_selector("#inspectionMetricModal.show", timeout=5000)
        page.wait_for_timeout(600)
        print("[OK] Returned back to inspectionMetricModal smoothly!")

        # Close modal
        page.locator("#inspectionMetricModal .btn-close").click()
        page.wait_for_timeout(500)

        # 5. Test Card 2: Pending Review
        print("6. Clicking Card 2 (Pending Review)...")
        cards.nth(1).click()
        page.wait_for_selector("#inspectionMetricModal.show", timeout=5000)
        page.wait_for_timeout(500)
        p_title = page.locator("#inspectionMetricModalLabel").inner_text()
        p_badge = page.locator("#inspectionMetricBadge").inner_text()
        print(f"[OK] Pending Review Modal: Title='{p_title}', Badge='{p_badge}'")
        assert "Pending" in p_title
        page.locator("#inspectionMetricModal .btn-close").click()
        page.wait_for_timeout(500)

        # 6. Test Card 3: Approved Audits
        print("7. Clicking Card 3 (Approved Audits)...")
        cards.nth(2).click()
        page.wait_for_selector("#inspectionMetricModal.show", timeout=5000)
        page.wait_for_timeout(500)
        a_title = page.locator("#inspectionMetricModalLabel").inner_text()
        a_badge = page.locator("#inspectionMetricBadge").inner_text()
        print(f"[OK] Approved Audits Modal: Title='{a_title}', Badge='{a_badge}'")
        assert "Approved" in a_title
        page.locator("#inspectionMetricModal .btn-close").click()
        page.wait_for_timeout(500)

        # 7. Test Card 4: High Risk Flags
        print("8. Clicking Card 4 (High Risk Flags)...")
        cards.nth(3).click()
        page.wait_for_selector("#inspectionMetricModal.show", timeout=5000)
        page.wait_for_timeout(500)
        h_title = page.locator("#inspectionMetricModalLabel").inner_text()
        h_badge = page.locator("#inspectionMetricBadge").inner_text()
        print(f"[OK] High Risk Flags Modal: Title='{h_title}', Badge='{h_badge}'")
        assert "High" in h_title
        page.locator("#inspectionMetricModal .btn-close").click()
        page.wait_for_timeout(500)

        print("\n=== ALL INSPECTION METRIC MODAL TESTS PASSED SUCCESSFULLY! ===")
        browser.close()

if __name__ == "__main__":
    run()
