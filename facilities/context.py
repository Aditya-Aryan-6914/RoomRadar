def campus(request):
    """campus = institute owned by the user; my_inst = owned or joined (student) institute."""
    out = {"campus": None, "my_inst": None, "is_student": False, "is_member": False}
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return out
    owned = getattr(user, "institute", None)
    profile = getattr(user, "student_profile", None)
    my = owned or (profile.institute if profile else None)
    slug = getattr(getattr(request, "resolver_match", None), "kwargs", {}).get("slug")
    out.update(campus=owned, my_inst=my, is_student=bool(profile and not owned),
               is_member=bool(my and slug == my.slug))
    return out
