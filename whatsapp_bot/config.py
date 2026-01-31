"""
Configuration for WhatsApp Weekly Summary Bot
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Google Sheets Configuration
GOOGLE_SHEETS_CREDENTIALS_FILE = 'njmaniacs-485422-8e16104bb447.json'
GOOGLE_SHEET_ID = '1POa75jrHHYwyfBAC0aObgc01HEFPnjl7ongLAJhqfa0'
GOOGLE_SHEET_NAME = 'Sheet1'

# WhatsApp Configuration
WHATSAPP_CONTACT_NAME = os.getenv('WHATSAPP_CONTACT_NAME', '')
BROWSER_CONTEXT_PATH = './whatsapp_bot/browser_data'
HEADLESS_MODE = os.getenv('HEADLESS_MODE', 'false').lower() == 'true'

# Message Template Settings
SHOW_WEEK_NUMBER = True
SHOW_TOTAL_MILEAGE = True

# Timeouts (in milliseconds)
WHATSAPP_LOAD_TIMEOUT = 60000  # 60 seconds for WhatsApp Web to load
ELEMENT_TIMEOUT = 30000  # 30 seconds for elements to appear
