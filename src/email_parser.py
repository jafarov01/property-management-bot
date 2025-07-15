# FILE: email_parser.py
# ==============================================================================
# VERSION: 5.0 (Production)
# UPDATED: The AI prompt has been enhanced to guide the model towards generating
# more concise text to better respect database column limits.
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
    1.  Read the email and determine a short, descriptive `category` for its main purpose (e.g., "Guest Complaint", "New Booking", "Cancellation"). This should be under 100 characters.
    2.  Create a concise, one-sentence `summary` of the core issue or message in the email.
    3.  Extract the following details if they are present. Be exact.
        - `guest_name`
        - `property_code` (If it's a long name, use the most recognizable part, under 20 characters if possible).
        - `platform` ("Airbnb" or "Booking.com")
        - `reservation_number`
        - `deadline` (e.g., "respond before", "within 48 hours", or a specific date).
    4.  If a field is not present, use the value `null`.
    5.  You MUST return a single, valid JSON object. Do not include any explanatory text or markdown.

    **Example Input:**
    "Dear partner, Delia Scorus (reservation 5149014360) at Super Central 2-Storey Apartment reported an issue. Please respond before 17 Jul 2025."

    **Example Output:**
    {{
        "category": "Guest Complaint",
        "summary": "Guest Delia Scorus has reported an unspecified issue.",
        "guest_name": "Delia Scorus",
        "property_code": "Super Central 2-S",
        "platform": "Booking.com",
        "reservation_number": "5149014360",
        "deadline": "17 Jul 2025"
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
            
            forwarded_for_header = msg.get('X-Forwarded-For', '')
            
            if "sagideviso@gmail.com" in forwarded_for_header:
                body = get_email_body(msg)
                if body:
                    relevant_emails.append({"body": body})

            mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()
        return relevant_emails
    except Exception as e:
        print(f"Failed to fetch emails: {e}")
        return []
