from django.contrib.auth.decorators import user_passes_test

from .role_utils import has_role_access


def admin_required(view_func):
    return user_passes_test(
        lambda u: has_role_access(u, "Admin"),
        login_url="login"
    )(view_func)


def manager_required(view_func):
    return user_passes_test(
        lambda u: has_role_access(u, "Manager"),
        login_url="login"
    )(view_func)


def client_required(view_func):
    return user_passes_test(
        lambda u: has_role_access(u, "Client"),
        login_url="login"
    )(view_func)


def partner_required(view_func):
    return user_passes_test(
        lambda u: has_role_access(u, "Partner"),
        login_url="login"
    )(view_func)