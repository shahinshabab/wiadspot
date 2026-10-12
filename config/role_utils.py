def user_has_group(user, group_name):
    return user.is_authenticated and user.groups.filter(name=group_name).exists()


def has_role_access(user, group_name):
    """Superusers may enter every workspace; others need the matching group."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name=group_name).exists()


def get_user_role(user):
    if not user.is_authenticated:
        return None

    if user.groups.filter(name="Admin").exists():
        return "Admin"
    if user.groups.filter(name="Manager").exists():
        return "Manager"
    if user.groups.filter(name="Client").exists():
        return "Client"
    if user.groups.filter(name="Partner").exists():
        return "Partner"

    return None