# FILE: slack_parser.py
# ==============================================================================
from typing import List, Dict
import datetime
import json
import re
import google.generativeai as genai
from config import GEMINI_API_KEY

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

async def parse_checkin_list_with_ai(message_text: str, checkin_date: str) -> List[Dict]:
    """
    Uses a robust, few-shot prompt to parse check-in data with high accuracy,
    handling messy and varied inputs.
    """
    # This advanced prompt includes examples to guide the AI on handling edge cases.
    prompt = f"""
    You are a high-precision data extraction bot. Your task is to analyze user text and convert it into a structured JSON format without fail.

    **Instructions:**
    1.  Extract check-in details for the date: **{checkin_date}**.
    2.  The fields are "property_code", "guest_name", "platform", and "due_payment".
    3.  The property code is ALWAYS the first word on the line.
    4.  The guest name is the text after the first separator until the next separator. If you cannot read the name (e.g., it's in a different alphabet), use the placeholder text provided (e.g., "Chinese").
    5.  If any other field is missing, use the value "N/A".
    6.  You MUST return the data as a valid JSON array of objects, even if there is only one check-in.
    7.  Do NOT include any explanatory text, markdown formatting, or anything other than the raw JSON data in your response.

    **Examples:**

    **Input 1 (Standard):**
    A1 - John Smith - Arb - none
    K4 - Maria Garcia - Bdc - 50 eur

    **Your Output for Input 1:**
    [
        {{"property_code": "A1", "guest_name": "John Smith", "platform": "Arb", "due_payment": "none"}},
        {{"property_code": "K4", "guest_name": "Maria Garcia", "platform": "Bdc", "due_payment": "50 eur"}}
    ]

    **Input 2 (Messy, with placeholder name and missing fields):**
    C5 - Chinese - paid - asap
    D2 - Peter Pan

    **Your Output for Input 2:**
    [
        {{"property_code": "C5", "guest_name": "Chinese", "platform": "paid", "due_payment": "asap"}},
        {{"property_code": "D2", "guest_name": "Peter Pan", "platform": "N/A", "due_payment": "N/A"}}
    ]
    
    **Input 3 (Single line):**
    F2 - Last Minute Guest - paid

    **Your Output for Input 3:**
    [
        {{"property_code": "F2", "guest_name": "Last Minute Guest", "platform": "paid", "due_payment": "N/A"}}
    ]
    
    ---
    **Text to parse now:**
    {message_text}
    ---
    """
    
    validated_bookings = []
    try:
        response = await model.generate_content_async(prompt)
        
        # More robust cleaning: find the first '[' and the last ']' to extract the JSON array
        match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if not match:
            print(f"AI Check-in Parsing Error: No valid JSON array found in response.")
            print(f"Raw AI Response: {response.text}")
            return []

        cleaned_response = match.group(0)
        parsed_data = json.loads(cleaned_response)

        if not isinstance(parsed_data, list):
            raise TypeError("AI did not return a list of objects.")

        for item in parsed_data:
            if not isinstance(item, dict): continue
            validated_bookings.append({
                "property_code": str(item.get("property_code", "UNKNOWN")).upper(),
                "guest_name": item.get("guest_name", "Unknown Guest"),
                "platform": item.get("platform", "N/A"),
                "due_payment": item.get("due_payment", "N/A"),
                "checkin_date": datetime.date.fromisoformat(checkin_date),
                "checkout_date": None,
                "status": "Active"
            })
        return validated_bookings
    except Exception as e:
        print(f"AI Check-in Parsing Exception: {e}")
        print(f"Failed to parse response: {response.text if 'response' in locals() else 'No response'}")
        return []

async def parse_cleaning_list_with_ai(message_text: str) -> List[str]:
    """
    Uses a robust prompt to extract only property codes from a bulk text message.
    """
    prompt = f"""
    You are a high-precision data extraction bot. Your task is to extract property codes from the user's text.

    **Instructions:**
    1.  Identify and extract ONLY the property codes (e.g., A1, K4, Nador2).
    2.  Ignore all other words, numbers, dates, and formatting (e.g., "Cleaning", "list", "for", "guests", "-").
    3.  You MUST return the data as a valid JSON array of strings.
    4.  Do NOT include any explanatory text, markdown formatting, or anything other than the raw JSON data in your response.

    **Example:**

    **Input:**
    Cleaning list for 13 July
    Nador1 - 4 guests
    A57
    G1 and G2

    **Your Output:**
    ["Nador1", "A57", "G1", "G2"]

    ---
    **Text to parse now:**
    {message_text}
    ---
    """
    try:
        response = await model.generate_content_async(prompt)
        
        # More robust cleaning: find the first '[' and the last ']' to extract the JSON array
        match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if not match:
            print(f"AI Cleaning Parsing Error: No valid JSON array found in response.")
            print(f"Raw AI Response: {response.text}")
            return []
            
        cleaned_response = match.group(0)
        parsed_data = json.loads(cleaned_response)
        return [str(item).upper() for item in parsed_data if isinstance(item, (str, int))]
    except Exception as e:
        print(f"AI Cleaning Parsing Exception: {e}")
        print(f"Failed to parse response: {response.text if 'response' in locals() else 'No response'}")
        return []