from functools import wraps

from django.shortcuts import redirect


def guest_only(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.user.is_authenticated:
            if getattr(request.user, 'role', None) == 'company':
                return redirect('dashboard:dashboard')
            return redirect('accounts:profile')
        return view_func(request, *args, **kwargs)

    return _wrapped_view
