# FILE: email_parser.py
# ==============================================================================
# VERSION: 7.0 (Production - Definitive Filter)
# UPDATED: Implemented the most robust filtering logic by inspecting the
# standard 'Received' headers for proof that the email was processed for
# the forwarding account. This is the definitive fix.
# ==============================================================================
import imaplib
import email
from email.header import decode_header
from typing import List, Dict
import re
import json
import google.generativeai as genai
from config import GEMINI_API_KEY, IMAP_SERVER, IMAP_USERNAME, IMAP_PASSWORD

# --- AI Configuration ---
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def get_email_body(msg):
    """Extracts the text content from an email message object."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                try:
                    return part.get_payload(decode=True).decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        return part.get_payload(decode=True).decode('latin-1')
                    except:
                         return None
    else:
        try:
            return msg.get_payload(decode=True).decode('utf-8')
        except UnicodeDecodeError:
            try:
                return msg.get_payload(decode=True).decode('latin-1')
            except:
                return None
    return None

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
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if not match:
            return {"category": "Parsing Failed", "summary": "AI response did not contain a valid JSON object."}
        
        cleaned_response = match.group(0)
        return json.loads(cleaned_response)
    except Exception as e:
        return {"category": "Parsing Exception", "summary": f"An exception occurred: {e}"}

def fetch_unread_emails() -> List[Dict]:
    """
    Connects to the IMAP server, fetches ALL unread emails, and filters them
    by inspecting the 'Received' headers for the forwarding address.
    """
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
        mail.select("inbox")

        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            mail.logout()
            return []

        relevant_emails = []
        for num in messages[0].split():
            is_relevant = False
            try:
                status, msg_data = mail.fetch(num, "(RFC822)")
                if status != "OK":
                    continue
                
                msg = email.message_from_bytes(msg_data[0][1])
                
                # --- THE DEFINITIVE FILTER ---
                # Check all 'Received' headers for proof the email was for the forwarding account.
                received_headers = msg.get_all('Received', [])
                for header in received_headers:
                    if "for <sagideviso@gmail.com>" in header:
                        is_relevant = True
                        break # Found what we need, no need to check more headers for this email
                
                if is_relevant:
                    body = get_email_body(msg)
                    if body:
                        relevant_emails.append({"body": body})

            finally:
                # Always mark the email as read to prevent infinite loops on malformed emails.
                mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()
        return relevant_emails
    except Exception as e:
        print(f"Failed to fetch emails: {e}")
        return []
