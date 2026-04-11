import os
from fastapi import Header, HTTPException


EDGE_SHARED_AUTH = os.getenv("EDGE_SHARED_AUTH")


def validate_auth(x_auth: str = Header(default="")) -> None:
    if not x_auth:
        raise HTTPException(status_code=401, detail="missing X-Auth")

    if x_auth != EDGE_SHARED_AUTH:
        raise HTTPException(status_code=401, detail="invalid X-Auth")