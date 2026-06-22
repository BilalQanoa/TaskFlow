from functools import wraps

from django.shortcuts import redirect

from .routing import redirect_user_by_role


def guest_only(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect_user_by_role(request.user)
        return view_func(request, *args, **kwargs)

    return _wrapped_view
