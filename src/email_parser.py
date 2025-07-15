# FILE: email_parser.py
# ==============================================================================
# FINAL VERSION: Implemented the definitive filter. It now inspects the
# 'X-Forwarded-For' header to only process emails forwarded by Eli.
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
    """Uses AI to parse email content, including a summary and reservation number."""
    prompt = f"""
    You are an expert data extraction system for a property management company.

    **Instructions:**
    1.  Read the email and determine a short, descriptive `category` for its main purpose (e.g., "Guest Complaint", "New Booking", "Cancellation").
    2.  Create a one-sentence `summary` of the core issue or message in the email.
    3.  Extract the following details if they are present:
        - `guest_name`
        - `property_code`
        - `platform` ("Airbnb" or "Booking.com")
        - `reservation_number` (This is very important. Look for "reservation" or "booking number").
    4.  If a field is not present, use the value `null`.
    5.  You MUST return a single, valid JSON object.

    **Example Input:**
    "Dear partner, Marta Miola (reservation 4488269885) reached out to us about the blood stains in the sheets."

    **Example Output:**
    {{
        "category": "Guest Complaint",
        "summary": "Guest is complaining about blood stains in the sheets.",
        "guest_name": "Marta Miola",
        "property_code": null,
        "platform": "Booking.com",
        "reservation_number": "4488269885"
    }}

    ---
    **Email content to parse now:**
    {email_body[:4000]}
    ---
    """
    try:
        response = await model.generate_content_async(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if not match:
            return {"category": "Parsing Failed"}
        
        cleaned_response = match.group(0)
        return json.loads(cleaned_response)
    except Exception as e:
        print(f"AI Email Parsing Exception: {e}")
        return {"category": "Parsing Exception"}

def fetch_unread_emails() -> List[Dict]:
    """
    Connects to the IMAP server, fetches all unread emails, and filters them
    locally based on the 'X-Forwarded-For' header.
    """
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
        mail.select("inbox")

        # Step 1: Fetch ALL unread emails. We will filter them in our code.
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            mail.logout()
            return []

        relevant_emails = []
        for num in messages[0].split():
            status, msg_data = mail.fetch(num, "(RFC822)")
            if status != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            # Step 2: Inspect the headers locally.
            forwarded_for_header = msg.get('X-Forwarded-For', '')
            
            # Step 3: The Smart Filter.
            # Only process the email if it was forwarded from Eli's address.
            if "sagideviso@gmail.com" in forwarded_for_header:
                body = get_email_body(msg)
                if body:
                    relevant_emails.append({"body": body})
            else:
                print(f"Ignoring irrelevant email (From: {msg.get('From')})")

            # Step 4: Mark the email as read regardless, to keep the inbox clean.
            mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()
        return relevant_emails
    except Exception as e:
        print(f"Failed to fetch emails: {e}")
        return []
