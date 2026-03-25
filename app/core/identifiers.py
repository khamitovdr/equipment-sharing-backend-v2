import secrets
import string

SHORT_ID_ALPHABET = string.ascii_uppercase + string.digits
SHORT_ID_LENGTH = 6


def generate_short_id(length: int = SHORT_ID_LENGTH) -> str:
    return "".join(secrets.choice(SHORT_ID_ALPHABET) for _ in range(length))
