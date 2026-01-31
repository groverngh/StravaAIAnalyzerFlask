"""
WhatsApp Web automation using Playwright
"""
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from whatsapp_bot.config import (
    WHATSAPP_CONTACT_NAME,
    BROWSER_CONTEXT_PATH,
    HEADLESS_MODE,
    WHATSAPP_LOAD_TIMEOUT,
    ELEMENT_TIMEOUT
)


def send_whatsapp_message(message, contact_name=None, headless=None):
    """Send a message to a WhatsApp contact via WhatsApp Web

    Args:
        message (str): The message to send
        contact_name (str, optional): Contact name to search for. Defaults to config value.
        headless (bool, optional): Run browser in headless mode. Defaults to config value.

    Returns:
        tuple: (success (bool), error_message (str or None))
    """
    # Use config values if not provided
    contact = contact_name or WHATSAPP_CONTACT_NAME
    run_headless = headless if headless is not None else HEADLESS_MODE

    if not contact:
        return False, "Contact name not configured. Set WHATSAPP_CONTACT_NAME in .env file."

    print(f"Starting WhatsApp automation...")
    print(f"Contact: {contact}")
    print(f"Headless mode: {run_headless}")

    with sync_playwright() as p:
        try:
            # Launch browser with persistent context (saves session)
            print(f"Launching browser (context: {BROWSER_CONTEXT_PATH})...")
            context = p.chromium.launch_persistent_context(
                user_data_dir=BROWSER_CONTEXT_PATH,
                headless=run_headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage'
                ]
            )

            # Get the first page (or create one)
            if context.pages:
                page = context.pages[0]
            else:
                page = context.new_page()

            # Navigate to WhatsApp Web
            print("Navigating to WhatsApp Web...")
            page.goto('https://web.whatsapp.com', timeout=WHATSAPP_LOAD_TIMEOUT)

            # Wait for WhatsApp to load (either QR code or main interface)
            print("Waiting for WhatsApp Web to load...")
            try:
                # Try to wait for the main chat interface (logged in)
                page.wait_for_selector('div[contenteditable="true"][data-tab="3"]', timeout=WHATSAPP_LOAD_TIMEOUT)
                print("✓ Already logged in!")
            except PlaywrightTimeout:
                # If not logged in, wait for QR code and manual login
                print("\n" + "="*60)
                print("⚠️  QR CODE REQUIRED")
                print("="*60)
                print("Please scan the QR code in the browser window to log in.")
                print("After scanning, the script will continue automatically...")
                print("="*60 + "\n")

                # Wait for login (search box appears when logged in)
                page.wait_for_selector('div[contenteditable="true"][data-tab="3"]', timeout=120000)  # 2 minutes
                print("✓ Login successful!")

            # Give WhatsApp a moment to fully load
            time.sleep(2)

            # Search for contact
            print(f"Searching for contact: {contact}...")
            search_box = page.wait_for_selector('div[contenteditable="true"][data-tab="3"]', timeout=ELEMENT_TIMEOUT)
            search_box.click()
            search_box.fill(contact)
            time.sleep(1)  # Wait for search results

            # Click on the contact from search results
            print("Selecting contact...")
            try:
                # Try to find contact by title attribute
                contact_selector = f'span[title="{contact}"]'
                page.wait_for_selector(contact_selector, timeout=ELEMENT_TIMEOUT)
                page.click(contact_selector)
                print(f"✓ Found contact: {contact}")
            except PlaywrightTimeout:
                return False, f"Contact '{contact}' not found in WhatsApp. Please check the contact name."

            time.sleep(1)

            # Find message input box and type message
            print("Typing message...")
            message_box = page.wait_for_selector('div[contenteditable="true"][data-tab="10"]', timeout=ELEMENT_TIMEOUT)
            message_box.click()

            # Type message line by line (WhatsApp Web needs this for newlines)
            lines = message.split('\n')
            for i, line in enumerate(lines):
                message_box.type(line)
                if i < len(lines) - 1:
                    # Add newline using Shift+Enter
                    page.keyboard.press('Shift+Enter')

            time.sleep(0.5)

            # Send message (press Enter)
            print("Sending message...")
            page.keyboard.press('Enter')

            # Wait a moment to ensure message is sent
            time.sleep(2)

            print("✓ Message sent successfully!")

            # Close browser
            context.close()

            return True, None

        except PlaywrightTimeout as e:
            error_msg = f"Timeout error: {str(e)}"
            print(f"✗ {error_msg}")
            try:
                context.close()
            except:
                pass
            return False, error_msg

        except Exception as e:
            error_msg = f"Error sending WhatsApp message: {str(e)}"
            print(f"✗ {error_msg}")
            try:
                context.close()
            except:
                pass
            return False, error_msg


if __name__ == "__main__":
    # Test message
    test_message = """🏃‍♂️💨 WEEKLY RUNNING LEADERBOARD 💨🏃‍♀️

🏆 PODIUM FINISHERS 🏆
🥇 Test User: 10.00 mi - Beast Mode! 🔥

Total group miles: 10.00 mi 🎯
Keep those legs moving! 🦵✨

#RunningCrew #Week5"""

    print("=== TESTING WHATSAPP SENDER ===")
    success, error = send_whatsapp_message(test_message, headless=False)

    if success:
        print("\n✓ TEST PASSED: Message sent successfully!")
    else:
        print(f"\n✗ TEST FAILED: {error}")
