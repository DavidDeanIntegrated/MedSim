"""LTI 1.3 integration endpoints for Canvas/Blackboard.

Implements:
  POST /lti/launch   — OIDC login initiation + launch handler
  POST /lti/grade     — Assignment and Grade Services (AGS) passback
  GET  /lti/jwks      — Platform JWKS endpoint for key exchange
  GET  /lti/config    — LTI tool configuration JSON

This is a minimal LTI 1.3 implementation suitable for auto-grading
integration with Canvas and Blackboard LMS platforms.

Configuration via environment variables:
  LTI_ISSUER          — Platform issuer URL (e.g., https://canvas.instructure.com)
  LTI_CLIENT_ID       — OAuth2 client ID registered with the LMS
  LTI_DEPLOYMENT_ID   — Deployment ID from LMS
  LTI_AUTH_ENDPOINT    — Platform authorization endpoint
  LTI_TOKEN_ENDPOINT   — Platform token endpoint
  LTI_JWKS_URL        — Platform JWKS URL for signature verification
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.core.config import get_settings

router = APIRouter(prefix="/lti", tags=["lti"])

# In-memory nonce store (replace with Redis in production)
_nonce_store: dict[str, float] = {}


@router.get("/config")
def lti_tool_config(request: Request) -> dict:
    """Return LTI 1.3 tool configuration for registration with an LMS.

    Educators copy this JSON into their LMS's external tool configuration.
    """
    base_url = str(request.base_url).rstrip("/")
    return {
        "title": "MedSim Clinical Simulation",
        "description": "Emergency Medicine clinical simulation for board preparation",
        "oidc_initiation_url": f"{base_url}/lti/login",
        "target_link_uri": f"{base_url}/lti/launch",
        "scopes": [
            "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem",
            "https://purl.imsglobal.org/spec/lti-ags/scope/result.readonly",
            "https://purl.imsglobal.org/spec/lti-ags/scope/score",
        ],
        "extensions": [
            {
                "platform": "canvas.instructure.com",
                "settings": {
                    "placements": [
                        {
                            "placement": "assignment_selection",
                            "message_type": "LtiDeepLinkingRequest",
                            "target_link_uri": f"{base_url}/lti/launch",
                        },
                        {
                            "placement": "link_selection",
                            "message_type": "LtiDeepLinkingRequest",
                            "target_link_uri": f"{base_url}/lti/launch",
                        },
                    ],
                },
            }
        ],
        "public_jwk_url": f"{base_url}/lti/jwks",
        "custom_fields": {
            "case_id": "$Canvas.assignment.title",
        },
    }


@router.get("/login")
async def oidc_login(request: Request) -> RedirectResponse:
    """OIDC login initiation — step 1 of LTI 1.3 launch.

    The LMS redirects the user here. We validate the request and
    redirect back to the platform's authorization endpoint.
    """
    params = dict(request.query_params)
    iss = params.get("iss", "")
    login_hint = params.get("login_hint", "")
    target_link_uri = params.get("target_link_uri", "")
    lti_message_hint = params.get("lti_message_hint", "")

    if not iss or not login_hint:
        raise HTTPException(status_code=400, detail="Missing iss or login_hint")

    # Generate nonce and state
    nonce = str(uuid.uuid4())
    state = str(uuid.uuid4())
    _nonce_store[nonce] = time.time()

    # Build authorization redirect
    settings = get_settings()
    auth_endpoint = getattr(settings, "lti_auth_endpoint", "") or f"{iss}/api/lti/authorize_redirect"
    redirect_params = {
        "scope": "openid",
        "response_type": "id_token",
        "client_id": getattr(settings, "lti_client_id", ""),
        "redirect_uri": target_link_uri or f"{request.base_url}lti/launch",
        "login_hint": login_hint,
        "state": state,
        "response_mode": "form_post",
        "nonce": nonce,
        "prompt": "none",
    }
    if lti_message_hint:
        redirect_params["lti_message_hint"] = lti_message_hint

    return RedirectResponse(url=f"{auth_endpoint}?{urlencode(redirect_params)}", status_code=302)


@router.post("/launch")
async def lti_launch(request: Request) -> HTMLResponse:
    """Handle LTI 1.3 launch — step 2.

    The platform POSTs an id_token (JWT) containing the launch claims.
    We validate it and redirect the learner into the simulation with
    their identity and assignment context.
    """
    form = await request.form()
    id_token = form.get("id_token", "")
    state = form.get("state", "")

    if not id_token:
        raise HTTPException(status_code=400, detail="Missing id_token in launch")

    # In production, validate JWT signature against platform JWKS.
    # For MVP, we decode the payload without full verification and
    # extract the launch claims.
    try:
        claims = _decode_jwt_payload(str(id_token))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid id_token: {exc}") from exc

    # Extract LTI claims
    user_name = claims.get("name", "LTI Learner")
    user_email = claims.get("email", "")
    user_id = claims.get("sub", str(uuid.uuid4()))
    custom = claims.get("https://purl.imsglobal.org/spec/lti/claim/custom", {})
    case_id = custom.get("case_id", "")

    # Store grade passback endpoint if available
    ags_claim = claims.get("https://purl.imsglobal.org/spec/lti-ags/claim/endpoint", {})
    lineitem_url = ags_claim.get("lineitem", "")

    # Redirect to the simulation frontend with LTI context
    base_url = str(request.base_url).rstrip("/")
    params = urlencode({
        "lti": "1",
        "user": user_name,
        "userId": user_id,
        "caseId": case_id,
        "lineitem": lineitem_url,
    })

    return HTMLResponse(
        content=f"""<!DOCTYPE html>
<html>
<head><meta http-equiv="refresh" content="0;url={base_url}/?{params}"></head>
<body>Launching MedSim for {user_name}...</body>
</html>""",
        status_code=200,
    )


@router.post("/grade")
async def submit_grade(request: Request) -> dict:
    """Submit a grade back to the LMS via Assignment and Grade Services.

    Body: {
        "lineitem_url": "https://canvas.example.com/api/lti/...",
        "user_id": "lti-user-id",
        "score": 85.0,
        "max_score": 100.0,
        "comment": "Completed septic shock simulation"
    }

    In production, this would obtain an OAuth2 token from the platform's
    token endpoint and POST the score. For MVP, we return what would be sent.
    """
    body = await request.json()
    lineitem_url = body.get("lineitem_url", "")
    user_id = body.get("user_id", "")
    score = body.get("score", 0)
    max_score = body.get("max_score", 100)
    comment = body.get("comment", "")

    if not lineitem_url or not user_id:
        raise HTTPException(status_code=400, detail="lineitem_url and user_id required")

    # Build AGS score payload (IMS Global spec)
    score_payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime()),
        "scoreGiven": score,
        "scoreMaximum": max_score,
        "comment": comment,
        "activityProgress": "Completed",
        "gradingProgress": "FullyGraded",
        "userId": user_id,
    }

    # In production: POST score_payload to {lineitem_url}/scores
    # with Bearer token from OAuth2 client_credentials grant.
    # For MVP, return what would be submitted.
    return {
        "status": "grade_prepared",
        "note": "In production, this would POST to the LMS AGS endpoint",
        "lineitem_url": f"{lineitem_url}/scores",
        "payload": score_payload,
    }


@router.get("/jwks")
def jwks_endpoint() -> dict:
    """Return public JSON Web Key Set for this tool.

    In production, this would return the RSA public key used to sign
    tool-originated JWTs. For MVP, returns a placeholder structure.
    """
    return {
        "keys": [
            {
                "kty": "RSA",
                "alg": "RS256",
                "use": "sig",
                "kid": "medsim-tool-key-1",
                "n": "placeholder",
                "e": "AQAB",
            }
        ]
    }


def _decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload without signature verification (MVP only)."""
    import base64

    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    # Decode payload (second part)
    payload = parts[1]
    # Add padding
    payload += "=" * (4 - len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload)
    return json.loads(decoded)
