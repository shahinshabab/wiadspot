from django.contrib.auth.decorators import user_passes_test


def admin_required(view_func):
    return user_passes_test(
        lambda u: u.is_authenticated and u.groups.filter(name="Admin").exists(),
        login_url="/login/"
    )(view_func)


def manager_required(view_func):
    return user_passes_test(
        lambda u: u.is_authenticated and u.groups.filter(name="Manager").exists(),
        login_url="/login/"
    )(view_func)


def client_required(view_func):
    return user_passes_test(
        lambda u: u.is_authenticated and u.groups.filter(name="Client").exists(),
        login_url="/login/"
    )(view_func)


def partner_required(view_func):
    return user_passes_test(
        lambda u: u.is_authenticated and u.groups.filter(name="Partner").exists(),
        login_url="/login/"
    )(view_func)