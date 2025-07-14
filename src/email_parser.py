# FILE: email_parser.py
# ==============================================================================
# Contains all logic for connecting to an IMAP email server, fetching unread
# messages, and using AI to parse their content with dynamic categories.
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
                    # Try to decode with utf-8, fall back to latin-1 if it fails
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
    """Uses AI to parse email content and extract booking details with a dynamic category."""
    prompt = f"""
    You are an expert data extraction system for a property management company. Analyze the following email content from Airbnb or Booking.com.

    **Instructions:**
    1.  Read the email and determine a short, descriptive `category` for its main purpose. Pay close attention to keywords in the subject like "Booking disruption", "Service issue", "Important update", "can't accommodate", "New booking", "Cancellation".
    2.  Extract the following details if they are present:
        - `guest_name`
        - `property_code`
        - `platform` ("Airbnb" or "Booking.com")
        - `checkin_date` (in YYYY-MM-DD format)
        - `checkout_date` (in YYYY-MM-DD format)
        - `payout_amount` (as a float, numbers only)
    3.  If a field is not present, use the value `null`.
    4.  You MUST return a single, valid JSON object. Do not include any other text.

    ---
    **Email content to parse now:**
    {email_body[:4000]}
    ---
    """
    try:
        response = await model.generate_content_async(prompt)
        # Use regex to find the JSON object, robust against extra text
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if not match:
            print(f"AI Email Parsing Error: No valid JSON object found in response.")
            print(f"Raw AI Response: {response.text}")
            return {"category": "Parsing Failed", "guest_name": None}
        
        cleaned_response = match.group(0)
        return json.loads(cleaned_response)
    except Exception as e:
        print(f"AI Email Parsing Exception: {e}")
        return {"category": "Parsing Exception", "guest_name": None}

def fetch_unread_emails() -> List[Dict]:
    """Connects to the IMAP server and fetches all unread emails."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
        mail.select("inbox")

        # Search for all unread emails
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            mail.logout()
            return []

        email_details = []
        for num in messages[0].split():
            status, msg_data = mail.fetch(num, "(RFC822)")
            if status != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            body = get_email_body(msg)

            if body:
                email_details.append({"body": body})

            # Mark the email as read so it's not processed again
            mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()
        return email_details
    except Exception as e:
        print(f"Failed to fetch emails: {e}")
        return []
