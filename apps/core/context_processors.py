def navigation(request) -> dict:
    user = getattr(request, "user", None)
    role = getattr(user, "role", None) if user and user.is_authenticated else None
    return {"current_role": role}
