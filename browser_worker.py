"""Run a local static focus walkthrough without inherited application credentials."""
import json
import sys
from playwright.sync_api import sync_playwright


def walk(data):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=data['browser_path'], headless=True, args=['--disable-gpu'])
        try:
            context = browser.new_context(java_script_enabled=False, service_workers='block')
            context.route('**/*', lambda route: route.abort())
            page = context.new_page()
            page.set_content(data['content'], wait_until='load', timeout=10000)
            results = []
            for index, selector in enumerate(data['expected_selectors'], 1):
                page.keyboard.press('Tab')
                observed = page.evaluate("""selector => {
                    const el = document.activeElement;
                    let matches = false;
                    try { matches = !!el && el.matches(selector); } catch (_) { throw new Error('Invalid expected CSS selector'); }
                    return {tag: (el?.tagName?.toLowerCase() || '').slice(0, 100), id: (el?.id || '').slice(0, 200),
                        role: (el?.getAttribute('role') || '').slice(0, 200), aria_label: (el?.getAttribute('aria-label') || '').slice(0, 200),
                        text: (el?.textContent || '').trim().slice(0, 160), matches_expected: matches};
                }""", selector)
                results.append({'step': index, 'expected_selector': selector, **observed})
            context.close()
            return results
        finally:
            browser.close()


def main():
    try:
        data = json.load(sys.stdin)
        print(json.dumps({'steps': walk(data)}))
    except Exception:
        print(json.dumps({'error': 'Headless browser walkthrough failed; verify browser and selectors'}))
        sys.exit(1)

if __name__ == '__main__': main()
