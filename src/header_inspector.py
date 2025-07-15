# FILE: header_inspector.py
# ==============================================================================
# A self-contained diagnostic tool to fetch and print email headers.
# This version does NOT import from config.py to avoid validation errors.
# ==============================================================================
import imaplib
import email
from email.header import decode_header
import os
from dotenv import load_dotenv

# --- Load environment variables directly ---
load_dotenv()
IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.gmail.com')
IMAP_USERNAME = os.getenv('IMAP_USERNAME')
IMAP_PASSWORD = os.getenv('IMAP_PASSWORD')

def inspect_latest_email_headers():
    """Connects to the IMAP server and prints the headers of the latest unread email."""
    if not all([IMAP_SERVER, IMAP_USERNAME, IMAP_PASSWORD]):
        print("❌ ERROR: Please ensure IMAP_SERVER, IMAP_USERNAME, and IMAP_PASSWORD are set in your .env file.")
        return

    try:
        print("Connecting to email server...")
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
        mail.select("inbox")
        print("✅ Connection successful.")

        # Search for all unread emails
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            print("\nNo unread emails found. Please have an email forwarded now and then re-run this script.")
            mail.logout()
            return

        # Get the latest email ID from the list
        latest_email_id = messages[0].split()[-1]
        print(f"Found latest unread email with ID: {latest_email_id.decode()}")

        # Fetch the full message (RFC822)
        status, msg_data = mail.fetch(latest_email_id, "(RFC822)")
        if status != "OK":
            print("Failed to fetch email content.")
            mail.logout()
            return

        msg = email.message_from_bytes(msg_data[0][1])

        print("\n--- HEADERS FOR LATEST UNREAD EMAIL ---")
        for header, value in msg.items():
            # Decode the header value to handle different character sets
            decoded_value = ""
            try:
                decoded_parts = decode_header(value)
                for part, charset in decoded_parts:
                    if isinstance(part, bytes):
                        # If a charset is specified, use it; otherwise, guess
                        decoded_value += part.decode(charset or 'utf-8', 'ignore')
                    else:
                        decoded_value += str(part)
            except Exception:
                decoded_value = value # Fallback to raw value if decoding fails

            print(f"{header}: {decoded_value}")
        print("---------------------------------------\n")

        print("✅ Inspection complete.")
        print("IMPORTANT: This email has NOT been marked as read.")

        mail.logout()

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
    inspect_latest_email_headers()
