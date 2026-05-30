"""SF Bay Area pharmacy directory for PharmaFetch AI.

These are SIMULATED pharmacies. Outbound calls don't go to these phone numbers —
they all route to MOCK_PHARMACY_NUMBER in .env, which connects to mock_pharmacies.py.
The pharmacy name/address are passed as metadata so the mock bot and caller bot
can role-play the scenario.
"""

import random

SF_PHARMACIES = [
    {"name": "CVS Pharmacy", "address": "199 Main St, San Francisco, CA", "area": "sf"},
    {"name": "Walgreens", "address": "730 5th Ave, San Francisco, CA", "area": "sf"},
    {"name": "Rite Aid", "address": "2450 Mission St, San Francisco, CA", "area": "sf"},
    {"name": "Costco Pharmacy", "address": "450 10th St, San Francisco, CA", "area": "sf"},
    {"name": "Safeway Pharmacy", "address": "1335 Webster St, San Francisco, CA", "area": "sf"},
    {"name": "Target Pharmacy", "address": "789 Mission St, San Francisco, CA", "area": "sf"},
    {"name": "Walmart Pharmacy", "address": "1600 Folsom St, San Francisco, CA", "area": "sf"},
    {"name": "Kaiser Pharmacy", "address": "2425 Geary Blvd, San Francisco, CA", "area": "sf"},
    {"name": "Walgreens", "address": "3601 California St, San Francisco, CA", "area": "sf"},
    {"name": "CVS Pharmacy", "address": "2099 Chestnut St, San Francisco, CA", "area": "sf"},
    # East Bay
    {"name": "CVS Pharmacy", "address": "5100 Broadway, Oakland, CA", "area": "east bay"},
    {"name": "Walgreens", "address": "1320 University Ave, Berkeley, CA", "area": "east bay"},
    {"name": "Rite Aid", "address": "2700 Shattuck Ave, Berkeley, CA", "area": "east bay"},
    # South Bay
    {"name": "CVS Pharmacy", "address": "301 University Ave, Palo Alto, CA", "area": "south bay"},
    {"name": "Walgreens", "address": "100 El Camino Real, Mountain View, CA", "area": "south bay"},
    {"name": "Costco Pharmacy", "address": "1001 Metro Dr, San Jose, CA", "area": "south bay"},
]


def get_pharmacies_for_area(area: str, limit: int = 3) -> list[dict]:
    """Return `limit` pharmacies matching the area, randomly sampled from the pool."""
    area_lower = area.strip().lower()

    # Match on area tag or city name substring
    matches = [
        p for p in SF_PHARMACIES
        if area_lower in p["area"] or area_lower in p["address"].lower()
    ]

    # Broad matches: "sf", "bay area", "san francisco" all hit the SF pool
    if not matches:
        for keyword in ("sf", "san francisco", "bay area", "bay"):
            if keyword in area_lower:
                matches = [p for p in SF_PHARMACIES if p["area"] == "sf"]
                break

    # Final fallback
    if not matches:
        matches = SF_PHARMACIES

    # Sample randomly from pool so demos aren't always the same 3
    if len(matches) > limit:
        matches = random.sample(matches, limit)

    return matches[:limit]
