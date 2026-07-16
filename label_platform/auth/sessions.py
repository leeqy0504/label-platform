from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


SESSION_COOKIE = "platform_session"
SESSION_SALT = "label-platform-session"


def create_session_token(secret: str, user_id: str) -> str:
    serializer = URLSafeTimedSerializer(secret_key=secret, salt=SESSION_SALT)
    return serializer.dumps({"user_id": user_id})


def read_session_token(secret: str, token: str, max_age: int) -> str | None:
    serializer = URLSafeTimedSerializer(secret_key=secret, salt=SESSION_SALT)
    try:
        payload = serializer.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None

    user_id = payload.get("user_id") if isinstance(payload, dict) else None
    return user_id if isinstance(user_id, str) else None
