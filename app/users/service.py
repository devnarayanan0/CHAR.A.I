def normalize_user_id(value: str | None) -> str:
    if not value:
        return "unknown"
    return value.strip()
