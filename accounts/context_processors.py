def agency_permissions(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"agency_perms": frozenset()}
    return {"agency_perms": user.agency_permissions}
