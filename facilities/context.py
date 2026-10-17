def campus(request):
    """`campus` = the institute owned by the logged-in user (if any)."""
    user = getattr(request, "user", None)
    return {"campus": getattr(user, "institute", None) if user and user.is_authenticated else None}
