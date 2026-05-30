"""Simple in-memory call log for PharmaFetch AI.

Stores intake requests and pharmacy call results so the dashboard
and SMS summary can read them.
"""

import asyncio
from datetime import datetime

# Global state — fine for a single-process hackathon prototype
_lock = asyncio.Lock()
_requests: dict[str, dict] = {}  # keyed by request_id


async def create_request(request_id: str, caller_phone: str, medication: str,
                         dosage: str, location: str,
                         pharmacy_names: list[dict] | None = None) -> dict:
    """Create a new search request. Optionally pre-populate pharmacy slots as 'calling'."""
    record = {
        "request_id": request_id,
        "caller_phone": caller_phone,
        "medication": medication,
        "dosage": dosage,
        "location": location,
        "status": "searching",
        "created_at": datetime.utcnow().isoformat(),
        "pharmacy_calls": [],
    }
    # Pre-populate with "calling" entries so the dashboard shows them immediately
    if pharmacy_names:
        for p in pharmacy_names:
            record["pharmacy_calls"].append({
                "pharmacy_name": p["name"],
                "pharmacy_address": p["address"],
                "status": "calling",
                "in_stock": None,
                "price": None,
                "transcript": "",
                "completed_at": None,
            })
    async with _lock:
        _requests[request_id] = record
    return record


async def update_pharmacy_call(request_id: str, pharmacy_name: str,
                               pharmacy_address: str, status: str,
                               in_stock: bool | None, price: str | None,
                               transcript: str) -> None:
    async with _lock:
        req = _requests.get(request_id)
        if not req:
            return

        # Find existing "calling" slot and update it, or append new
        updated = False
        for call in req["pharmacy_calls"]:
            if call["pharmacy_name"] == pharmacy_name and call["status"] == "calling":
                call["status"] = status
                call["in_stock"] = in_stock
                call["price"] = price
                call["transcript"] = transcript
                call["completed_at"] = datetime.utcnow().isoformat()
                updated = True
                break

        if not updated:
            req["pharmacy_calls"].append({
                "pharmacy_name": pharmacy_name,
                "pharmacy_address": pharmacy_address,
                "status": status,
                "in_stock": in_stock,
                "price": price,
                "transcript": transcript,
                "completed_at": datetime.utcnow().isoformat(),
            })

        # Mark request done when no calls are still "calling"
        statuses = [c["status"] for c in req["pharmacy_calls"]]
        if statuses and all(s in ("completed", "failed") for s in statuses):
            req["status"] = "done"


async def get_request(request_id: str) -> dict | None:
    async with _lock:
        return _requests.get(request_id)


async def get_all_requests() -> list[dict]:
    async with _lock:
        return list(_requests.values())
