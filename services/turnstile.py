import requests
from flask import current_app


_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile(response_token, remote_ip=None):
    """Verify a Cloudflare Turnstile response token server-side.

    Returns True when TURNSTILE_SECRET_KEY is unset, so local development
    keeps working without a real Turnstile account. Never logs the token
    or the secret key -- only Cloudflare's error codes, on failure.
    """
    secret_key = current_app.config.get("TURNSTILE_SECRET_KEY")
    if not secret_key:
        return True

    if not response_token:
        return False

    payload = {"secret": secret_key, "response": response_token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        response = requests.post(_VERIFY_URL, data=payload, timeout=5)
        result = response.json()
    except (requests.RequestException, ValueError):
        current_app.logger.exception("Turnstile verification request failed")
        return False

    if not result.get("success"):
        # Covers missing/invalid/expired/already-used tokens: Cloudflare
        # reports all of these through "error-codes" rather than distinct
        # HTTP statuses (e.g. "timeout-or-duplicate" for expired/replayed).
        current_app.logger.warning(
            "Turnstile verification rejected: %s",
            ", ".join(result.get("error-codes", [])) or "unknown",
        )

    return bool(result.get("success"))
