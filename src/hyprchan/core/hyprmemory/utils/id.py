import uuid


def generate_id() -> str:
    """Generate a stable unique identifier for memory objects."""
    return uuid.uuid4().hex
