from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


BASE_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_DIR = BASE_DIR / "credentials"

CLIENT_SECRETS_FILE = CREDENTIALS_DIR / "do_not_open_claude.json"
TOKEN_FILE = CREDENTIALS_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def get_credentials():
    credentials = None

    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(
            TOKEN_FILE,
            SCOPES,
        )

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRETS_FILE),
            SCOPES,
        )

        credentials = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    return credentials