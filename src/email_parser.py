# FILE: email_parser.py
# ==============================================================================
# VERSION: 4.0 (Production)
# UPDATED: Implemented the definitive, correct logic. The parser now fetches all
# unread emails and inspects the 'X-Forwarded-For' header locally to
# identify emails forwarded by the specified account. This is the final fix.
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
    2.  Create a one-sentence `summary` of the core issue or message in the email.
    3.  Extract the following details if they are present:
        - `guest_name`
        - `property_code`
        - `platform` ("Airbnb" or "Booking.com")
        - `reservation_number` (This is very important. Look for "reservation" or "booking number").
        - `deadline` (Look for phrases like "respond before", "within X hours", or a specific date and time).
    4.  If a field is not present, use the value `null`.
    5.  You MUST return a single, valid JSON object. Do not include any explanatory text or markdown.

    **Example Input:**
    "Dear partner, Delia Scorus has reported an issue experienced at Urban Getaway Lofts during their stay. Reservation details: 5149014360. Please review the customer report and respond within 48 hours (17 Jul 2025 - 10:58 Europe/Budapest)."

    **Example Output:**
    {{
        "category": "Guest Complaint",
        "summary": "Guest Delia Scorus has reported an unspecified issue at Urban Getaway Lofts.",
        "guest_name": "Delia Scorus",
        "property_code": "Urban Getaway Lofts",
        "platform": "Booking.com",
        "reservation_number": "5149014360",
        "deadline": "17 Jul 2025 - 10:58"
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
            return {"category": "Parsing Failed", "summary": "AI response did not contain a valid JSON object."}
        
        cleaned_response = match.group(0)
        return json.loads(cleaned_response)
    except Exception as e:
        return {"category": "Parsing Exception", "summary": f"An exception occurred: {e}"}

def fetch_unread_emails() -> List[Dict]:
    """
    Connects to the IMAP server, fetches ALL unread emails, and filters them
    locally based on the 'X-Forwarded-For' header to find forwarded messages.
    """
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
        mail.select("inbox")

        # Step 1: Fetch ALL unread emails.
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
            
            # Step 2: The Definitive Filter. Inspect the 'X-Forwarded-For' header.
            forwarded_for_header = msg.get('X-Forwarded-For', '')
            
            # Step 3: Check if the email was forwarded by the target account.
            if "sagideviso@gmail.com" in forwarded_for_header:
                body = get_email_body(msg)
                if body:
                    relevant_emails.append({"body": body})

            # Step 4: Mark the email as read regardless, to keep the inbox clean.
            mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()
        return relevant_emails
    except Exception as e:
        print(f"Failed to fetch emails: {e}")
        return []
