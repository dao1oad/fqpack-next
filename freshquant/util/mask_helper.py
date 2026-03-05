def mask(value, show_chars=3):
    if not value:
        return value
    masked = value[:1] + "****" + value[-show_chars:]
    return masked
