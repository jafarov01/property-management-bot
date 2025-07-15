# FILE: email_parser.py
# ==============================================================================
# VERSION: 2.0
# UPDATED: The AI prompt has been enhanced to extract a 'deadline' from the
# email body, adding critical, time-sensitive information to alerts.
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
        # Use a more robust regex to find the JSON object
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if not match:
            print(f"AI Email Parsing Error: No valid JSON object found in response.")
            print(f"Raw AI Response: {response.text}")
            return {"category": "Parsing Failed", "summary": "AI response did not contain a valid JSON object."}
        
        cleaned_response = match.group(0)
        return json.loads(cleaned_response)
    except Exception as e:
        print(f"AI Email Parsing Exception: {e}")
        return {"category": "Parsing Exception", "summary": f"An exception occurred: {e}"}

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
            # Only process the email if it was forwarded from the specified user's address.
            if "sagideviso@gmail.com" in forwarded_for_header:
                body = get_email_body(msg)
                if body:
                    relevant_emails.append({"body": body})
            else:
                # This is not an error, just filtering, so we can skip logging it unless debugging.
                # print(f"Ignoring irrelevant email (From: {msg.get('From')})")
                pass

            # Step 4: Mark the email as read regardless, to keep the inbox clean.
            # This is a key part of the workflow.
            mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()
        return relevant_emails
    except Exception as e:
        print(f"Failed to fetch emails: {e}")
        return []
