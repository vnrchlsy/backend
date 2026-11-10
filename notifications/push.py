"""US-P2 · the push send seam, on the Expo push service (notifications review NP1, NQ1).

The app registers an Expo push token (`ExponentPushToken[...]`), so delivery goes through Expo's push
API, not FCM directly. Unset by default (`EXPO_PUSH_ENABLED` blank): the sender is a no-op and nothing
leaves the process, like `common/senders.py`. Set it in production; `EXPO_PUSH_ACCESS_TOKEN` is only
needed if "enhanced push security" is turned on in the Expo project.

`send_push` keeps its one-token shape so `notifications.service` and its tests do not change; step 6 of
the review (the outbox) batches through `send_push_batch`, which this module already provides.
"""
import logging
import re
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger("kupkop.push")

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_BATCH_LIMIT = 100          # Expo accepts at most 100 messages per request
EXPO_TIMEOUT_SECONDS = 5        # a slow provider must never hold a request thread for long
_EXPO_TOKEN = re.compile(r"^Expo(nent)?PushToken\[[^\]\s]+\]$")


@dataclass(frozen=True)
class PushResult:
    ok: bool
    unregistered: bool = False


def _configured() -> bool:
    return bool(getattr(settings, "EXPO_PUSH_ENABLED", ""))


def is_expo_token(token) -> bool:
    return isinstance(token, str) and bool(_EXPO_TOKEN.match(token))


def _expo_transport(messages):
    """POST one batch to Expo. Returns `(http_status, parsed_json_or_None)`. Raises on a network error;
    callers catch it. Tests patch this seam."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    access = getattr(settings, "EXPO_PUSH_ACCESS_TOKEN", "")
    if access:
        headers["Authorization"] = f"Bearer {access}"
    resp = requests.post(EXPO_PUSH_URL, json=messages, headers=headers, timeout=EXPO_TIMEOUT_SECONDS)
    try:
        body = resp.json()
    except ValueError:
        body = None
    return resp.status_code, body


def _message(token, title, body, data):
    return {"to": token, "title": title, "body": body, "data": data or {},
            "sound": "default", "priority": "high"}


def _ticket_result(ticket) -> PushResult:
    if not isinstance(ticket, dict):
        return PushResult(ok=False)
    if ticket.get("status") == "ok":
        return PushResult(ok=True)
    code = (ticket.get("details") or {}).get("error") if isinstance(ticket.get("details"), dict) else None
    if code == "DeviceNotRegistered":
        return PushResult(ok=False, unregistered=True)
    # MessageTooBig, MessageRateExceeded, InvalidCredentials, ...: a failure, not a dead token.
    logger.error("push refused by provider: %s", code or "unknown")
    return PushResult(ok=False)


def send_push_batch(items):
    """`items`: a list of `(token, title, body, data)`. Returns one `PushResult` per item, in order.
    Never raises. A token that is not an Expo token can never be delivered and is reported unregistered,
    so the caller prunes it. A timeout, a 5xx or a malformed answer fails the affected items and prunes
    nothing."""
    results = [PushResult(ok=False)] * len(items)
    if not _configured():
        return results                                    # dev no-op: nothing is sent
    sendable = []
    for i, (token, title, body, data) in enumerate(items):
        if not is_expo_token(token):
            results[i] = PushResult(ok=False, unregistered=True)
        else:
            sendable.append((i, _message(token, title, body, data)))
    for start in range(0, len(sendable), EXPO_BATCH_LIMIT):
        chunk = sendable[start:start + EXPO_BATCH_LIMIT]
        try:
            status, payload = _expo_transport([m for _, m in chunk])
        except Exception:
            logger.exception("push transport failed for a batch of %d", len(chunk))
            continue
        tickets = payload.get("data") if isinstance(payload, dict) else None
        if status != 200 or not isinstance(tickets, list) or len(tickets) != len(chunk):
            logger.error("push provider answered %s with an unusable body for a batch of %d",
                         status, len(chunk))
            continue
        for (i, _), ticket in zip(chunk, tickets, strict=True):
            results[i] = _ticket_result(ticket)
    return results


def send_push(token, *, title, body, data) -> PushResult:
    return send_push_batch([(token, title, body, data)])[0]
