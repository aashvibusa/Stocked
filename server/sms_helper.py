"""Twilio SMS helper for PharmaFetch AI.

Sends an aggregated text summary to the caller once all pharmacy calls complete.
"""

import os

from loguru import logger
from twilio.rest import Client as TwilioClient


def send_summary_sms(caller_phone: str, caller_name: str, medication: str,
                     dosage: str, pharmacy_results: list[dict]) -> None:
    """Send aggregated pharmacy results via SMS.

    Args:
        caller_phone: E.164 phone number of the original caller.
        caller_name: Name of the caller (or "there" if unknown).
        medication: Medication name.
        dosage: Dosage string.
        pharmacy_results: List of dicts with keys: pharmacy_name, in_stock, price.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")

    # WhatsApp uses the sandbox number, not your regular Twilio number
    whatsapp_from = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

    if not all([account_sid, auth_token, from_number]):
        logger.error("Missing Twilio credentials for SMS — skipping")
        return

    lines = [f"Hi {caller_name}, we checked {len(pharmacy_results)} pharmacies for {medication} {dosage}.\n"]
    for r in pharmacy_results:
        name = r["pharmacy_name"]
        if r.get("in_stock"):
            price_str = f" (${r['price']})" if r.get("price") else ""
            lines.append(f"  {name}: IN STOCK{price_str}")
        elif r.get("status") == "failed":
            lines.append(f"  {name}: COULD NOT REACH")
        else:
            lines.append(f"  {name}: OUT OF STOCK")

    lines.append("\n- Stocked")
    body = "\n".join(lines)

    try:
        client = TwilioClient(account_sid, auth_token)
        # Use WhatsApp sandbox
        msg = client.messages.create(
            body=body,
            from_=whatsapp_from,
            to=f"whatsapp:{caller_phone}"
        )
        logger.info(f"WhatsApp message sent to {caller_phone}: {msg.sid}")
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
