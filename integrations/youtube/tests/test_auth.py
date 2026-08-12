from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from auth import get_credentials


def main():
    print("===== NIK YOUTUBE AUTH TEST =====")

    credentials = get_credentials()

    print("AUTHENTICATION: SUCCESS")
    print("TOKEN VALID:", credentials.valid)
    print("REFRESH TOKEN:", bool(credentials.refresh_token))

    print("===============================")


if __name__ == "__main__":
    main()