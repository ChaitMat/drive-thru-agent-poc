"""Money formatting helpers — kept central so spoken/TTS output stays clean.

TTS reads "₹338.00" as "rupees three hundred thirty eight point zero zero",
which sounds robotic at the kiosk. We strip the trailing `.00` for whole
rupees (the common case — menu prices are all whole) and only show paise
when the value genuinely has fractional rupees (e.g. percent discounts).
"""

from __future__ import annotations


def format_rupees(paise: int) -> str:
    """Format paise as "₹338" or "₹338.65" — never "₹338.00"."""
    rupees, remainder = divmod(int(paise), 100)
    if remainder == 0:
        return f"₹{rupees}"
    return f"₹{rupees}.{remainder:02d}"
