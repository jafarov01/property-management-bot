# FILE: app/email_parser.py
# VERSION: 9.1 (Corrected Email Logic)
# ==============================================================================
# UPDATED: Reverted the email fetching logic to align with the new requirements.
#
# 1. The IMAP search now fetches ALL unread emails, removing the sender filter.
# 2. A new list of `IGNORED_SUBJECTS` is used to filter out common promotional
#    and security emails after they are fetched but before they are processed.
# ==============================================================================
import imaplib
import email
from email.header import decode_header
from typing import List, Dict, Optional
import re
import json
import google.generativeai as genai
from .config import GEMINI_API_KEY, IMAP_SERVER, IMAP_USERNAME, IMAP_PASSWORD

# --- AI Configuration ---
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# NEW: List of subject keywords to ignore. Case-insensitive.
IGNORED_SUBJECTS = [
    "security alert",
    "new sign-in",
    "promotional",
    "weekly report",
    "your invoice",
]


def get_email_body(msg: email.message.Message) -> Optional[str]:
    """Extracts the text content from an email message object."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                try:
                    return part.get_payload(decode=True).decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        return part.get_payload(decode=True).decode("latin-1")
                    except Exception:
                        return None
    else:
        try:
            return msg.get_payload(decode=True).decode("utf-8")
        except UnicodeDecodeError:
            try:
                return msg.get_payload(decode=True).decode("latin-1")
            except Exception:
                return None
    return None


def fetch_unread_email_metadata() -> List[Dict]:
    """
    Connects to the IMAP server and fetches metadata for ALL unread emails,
    skipping those with ignored subjects.
    """
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
        mail.select("inbox")

        # CORRECTED: Search for all unseen emails, without a FROM filter.
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            mail.logout()
            return []

        email_metadata = []
        uids_to_mark_seen = []
        for num in messages[0].split():
            # Fetch both UID and ENVELOPE
            status, msg_data = mail.fetch(num, "(UID ENVELOPE)")
            if status != "OK":
                continue

            # Extract subject from envelope
            raw_subject = b""
            try:
                # This parsing is brittle but avoids fetching the whole body
                raw_subject = msg_data[0].split(b'"subject"')[1].split(b'"')[1]
                decoded_parts = decode_header(raw_subject.decode('utf-8', 'ignore'))
                subject = ""
                for part, charset in decoded_parts:
                    if isinstance(part, bytes):
                        subject += part.decode(charset or 'utf-8', 'ignore')
                    else:
                        subject += str(part)
            except Exception:
                subject = raw_subject.decode('utf-8', 'ignore')


            # NEW: Filter out ignored subjects
            if any(ignored in subject.lower() for ignored in IGNORED_SUBJECTS):
                # We should mark these as read so we don't process them again.
                uids_to_mark_seen.append(num)
                continue

            # Extract UID
            uid_match = re.search(r'UID\s+(\d+)', msg_data[0].decode('utf-8', 'ignore'))
            if not uid_match:
                continue
            uid = uid_match.group(1)

            email_metadata.append({
                "uid": uid,
                "subject": subject,
            })

        # Mark ignored emails as read in a batch
        if uids_to_mark_seen:
            for uid_to_mark in uids_to_mark_seen:
                 mail.store(uid_to_mark, "+FLAGS", "\\Seen")

        mail.logout()
        return email_metadata
    except Exception as e:
        print(f"Failed to fetch email metadata: {e}")
        # Ensure logout on failure
        if 'mail' in locals() and mail.state == 'SELECTED':
            mail.logout()
        return []


def fetch_email_body_by_uid(uid: str) -> Optional[str]:
    """Fetches the full body of a single email given its UID."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
        mail.select("inbox")
        # Use UID for fetching, which is more reliable than sequence numbers
        status, msg_data = mail.uid('fetch', uid, "(RFC822)")
        mail.logout()

        if status == "OK":
            msg = email.message_from_bytes(msg_data[0][1])
            return get_email_body(msg)
        return None
    except Exception as e:
        print(f"Failed to fetch email body for UID {uid}: {e}")
        return None


def mark_email_as_read_by_uid(uid: str) -> bool:
    """Marks a single email as read ('Seen') given its UID."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
        mail.select("inbox")
        # Use UID for storing flags
        result, _ = mail.uid('store', uid, "+FLAGS", "\\Seen")
        mail.logout()
        return result == "OK"
    except Exception as e:
        print(f"Failed to mark email as read for UID {uid}: {e}")
        return False


async def parse_booking_email_with_ai(email_body: str) -> Dict:
    """Uses AI to parse email content, including a summary, reservation number, and deadline."""
    prompt = f"""
    You are an expert data extraction system for a property management company.

    **Instructions:**
    1.  Read the email and determine a short, descriptive `category` for its main purpose (e.g., "Guest Complaint", "New Booking", "Cancellation", "Service Issue").
    2.  Create a concise, one-sentence `summary` of the core issue or message in the email.
    3.  Extract the following details if they are present:
        - `guest_name`
        - `property_code`
        - `platform` ("Airbnb" or "Booking.com")
        - `reservation_number`
        - `deadline` (e.g., "respond before", "within 48 hours", or a specific date).
    4.  If a field is not present, use the value `null`.
    5.  You MUST return a single, valid JSON object.

    ---
    **Email content to parse now:**
    {email_body[:4000]}
    ---
    """
    try:
        response = await model.generate_content_async(prompt)
        match = re.search(r"\{.*\}", response.text, re.DOTALL)
        if not match:
            return {
                "category": "Parsing Failed",
                "summary": "AI response did not contain a valid JSON object.",
            }

        cleaned_response = match.group(0)
        return json.loads(cleaned_response)
    except Exception as e:
        return {
            "category": "Parsing Exception",
            "summary": f"An exception occurred: {e}",
        }