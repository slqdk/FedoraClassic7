"""Mail: signing in to Outlook.com / Microsoft 365 with OAuth 2.0 (device code flow).

Microsoft switched off plain passwords for IMAP/SMTP, so Mail signs in the way Microsoft's own
apps do: Mail shows a short code, the user enters it on microsoft.com/devicelogin in any browser
and approves, and Mail receives a token. Mail uses the user's own application registration
(an "Application (client) ID" from Microsoft Entra), see ENTRA_STEPS.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import mail_accounts as acc_mod

SCOPES = "offline_access https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send"
BASE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0"

ENTRA_STEPS = """\
<p>Microsoft only lets registered programs read Outlook.com mail. You register Mail once,
for free, as your own program:</p>
<ol>
<li>Open <a href="https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade">
entra.microsoft.com &rarr; App registrations</a> and sign in with your Microsoft account
(if it asks you to create a free Azure account or directory, do that first).</li>
<li>Click <b>New registration</b>. Name: <i>Classic 7 Mail</i>.
Supported account types: <b>Personal Microsoft accounts only</b>
(or <i>Accounts in any organizational directory and personal Microsoft accounts</i> if you also use a work account).
Leave Redirect URI empty and click <b>Register</b>.</li>
<li>Copy the <b>Application (client) ID</b> shown on the overview page.</li>
<li>Open <b>Authentication</b>, set <b>Allow public client flows</b> to <b>Yes</b> and click <b>Save</b>.</li>
<li>Open <b>API permissions &rarr; Add a permission &rarr; APIs my organization uses</b>, search for
<i>Office 365 Exchange Online</i> &rarr; <b>Delegated permissions</b>, tick <b>IMAP.AccessAsUser.All</b>
and <b>SMTP.Send</b>, and click <b>Add permissions</b>. (For personal accounts this step can be skipped.)</li>
<li>Paste the Application (client) ID into Mail.</li>
</ol>"""


class OAuthError(Exception):
    pass


class Pending(OAuthError):
    """The user has not approved yet."""


def _post(url: str, data: dict, timeout: float = 20) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded",
                                                          "User-Agent": "Classic7-Mail/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:    # noqa: S310
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except ValueError:
            raise OAuthError(f"Microsoft answered {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise OAuthError(f"Microsoft's sign-in server can't be reached ({getattr(e, 'reason', e)}).") from e


def _error_text(r: dict) -> str:
    code = r.get("error", "")
    desc = (r.get("error_description") or "").split("\r\n")[0]
    if code == "unauthorized_client" or "AADSTS70002" in desc or "AADSTS7000218" in desc:
        return ("Microsoft refused the Application ID. Check that \"Allow public client flows\" is set to Yes "
                "in the app registration, and that it allows personal Microsoft accounts.")
    if "AADSTS700016" in desc:
        return "Microsoft doesn't know this Application (client) ID. Check that it was copied correctly."
    if code == "expired_token":
        return "The code expired before it was entered. Start the sign-in again."
    if code in ("access_denied", "authorization_declined"):
        return "Sign-in was declined."
    if code == "invalid_grant":
        return "The sign-in has expired or was revoked. Sign in again (Account Settings > Change)."
    return desc or code or "Sign-in failed."


def start_device_code(client_id: str, tenant: str = "consumers") -> dict:
    """Returns user_code, device_code, verification_uri, interval, expires_in, message."""
    r = _post(BASE.format(tenant=tenant) + "/devicecode", {"client_id": client_id, "scope": SCOPES})
    if "device_code" not in r:
        raise OAuthError(_error_text(r))
    r.setdefault("interval", 5)
    r.setdefault("verification_uri", "https://microsoft.com/devicelogin")
    return r


def poll_device_code(client_id: str, device_code: str, tenant: str = "consumers") -> dict:
    r = _post(BASE.format(tenant=tenant) + "/token",
              {"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": client_id,
               "device_code": device_code})
    if "access_token" in r:
        return r
    if r.get("error") in ("authorization_pending", "slow_down"):
        raise Pending(r.get("error"))
    raise OAuthError(_error_text(r))


def wait_device_code(client_id: str, flow: dict, tenant: str = "consumers", cancel: threading.Event | None = None) -> dict:
    deadline = time.time() + int(flow.get("expires_in", 900))
    interval = int(flow.get("interval", 5))
    while time.time() < deadline:
        if cancel is not None and cancel.wait(interval):
            raise OAuthError("Sign-in was cancelled.")
        if cancel is None:
            time.sleep(interval)
        try:
            return poll_device_code(client_id, flow["device_code"], tenant)
        except Pending as p:
            if str(p) == "slow_down":
                interval += 5
    raise OAuthError("The code expired before it was entered. Start the sign-in again.")


def refresh(client_id: str, refresh_token: str, tenant: str = "consumers") -> dict:
    r = _post(BASE.format(tenant=tenant) + "/token",
              {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh_token,
               "scope": SCOPES})
    if "access_token" not in r:
        raise OAuthError(_error_text(r))
    return r


# ---- token store ------------------------------------------------------------------------------
_lock = threading.Lock()
_cache: dict[str, tuple[str, float]] = {}       # account id -> (access token, expiry)


def store_tokens(account_id: str, tokens: dict):
    stored = {"refresh_token": tokens.get("refresh_token", "")}
    if not stored["refresh_token"]:
        old = _load(account_id)
        stored["refresh_token"] = old.get("refresh_token", "")
    acc_mod.set_secret(account_id, "oauth", json.dumps(stored))
    with _lock:
        _cache[account_id] = (tokens["access_token"], time.time() + int(tokens.get("expires_in", 3600)) - 120)


def _load(account_id: str) -> dict:
    try:
        return json.loads(acc_mod.get_secret(account_id, "oauth") or "{}")
    except ValueError:
        return {}


def signed_in(account_id: str) -> bool:
    return bool(_load(account_id).get("refresh_token"))


def access_token(account) -> str:
    """A valid access token for the account, refreshing it when needed."""
    with _lock:
        tok = _cache.get(account.id)
    if tok and tok[1] > time.time():
        return tok[0]
    rt = _load(account.id).get("refresh_token")
    if not rt:
        raise OAuthError("Not signed in to Microsoft. Open Account Settings and click Change to sign in.")
    tokens = refresh(account.oauth_client_id, rt, account.oauth_tenant or "consumers")
    store_tokens(account.id, tokens)
    return tokens["access_token"]


def forget(account_id: str):
    with _lock:
        _cache.pop(account_id, None)
    acc_mod.delete_secret(account_id, "oauth")


def xoauth2(user: str, token: str) -> str:
    return f"user={user}\x01auth=Bearer {token}\x01\x01"


def xoauth2_b64(user: str, token: str) -> str:
    return base64.b64encode(xoauth2(user, token).encode()).decode()
