"""Provider token verification seam (US-A2).

STATUS: NOT WIRED, AND BLOCKED ON PAPERWORK — not on effort.
`dev/sprint-0-checklist.md` S0-05 (Apple Developer Program) and S0-06 (Google OAuth client)
are both still unchecked, so there is no audience/client ID to verify a token *against*.
Adding `google-auth` now would install a dependency nothing can exercise.

TO FINISH (once S0-05 / S0-06 land):
  1. `pip install google-auth` and add it to requirements.txt.
  2. Set GOOGLE_OAUTH_CLIENT_ID (and APPLE_CLIENT_ID) in the environment.
  3. Replace the body of `verify_token` with the real check — for Google:
         from google.oauth2 import id_token as g_id_token
         from google.auth.transport import requests as g_requests
         claims = g_id_token.verify_oauth2_token(
             id_token, g_requests.Request(), settings.GOOGLE_OAUTH_CLIENT_ID)
     and for Apple, verify the JWT against Apple's JWKS with the same audience check.
     Return a dict with at least {"sub", "email"} — that is all the view consumes.

⚠️ The audience check is the whole point. A token verified without pinning it to OUR client ID
is a token minted for someone else's app, which would let its holder sign in as that user here.
Never "verify" by decoding without validating the signature and the audience.

The mobile side has a matching seam at `mobile_app/src/auth/socialAuth.ts` — both drop in together.
"""


class SocialNotConfigured(Exception):
    """Raised when provider verification is not wired/configured. The view turns this into a
    clean 503 rather than letting a NotImplementedError surface as an opaque 500."""


def verify_token(provider, id_token):
    """Return the provider's claims, at minimum {"sub", "email"}.

    Tests monkeypatch this. Production wiring per the module docstring.
    """
    raise SocialNotConfigured(provider)
