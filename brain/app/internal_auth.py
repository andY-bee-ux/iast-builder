"""app/internal_auth.py — verifies calls come from our own gateway, not the
open internet, in case this service is ever reachable directly by mistake."""
from fastapi import Header, HTTPException
from .config import INTERNAL_SECRET


async def require_internal(x_internal_secret: str = Header(default="")):
    if INTERNAL_SECRET and x_internal_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Appel direct non autorisé — passez par la gateway.")
