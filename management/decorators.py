from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required

from accounts.routing import redirect_user_by_role


def team_leader_required(view_func):
    @wraps(view_func)
    @login_required(login_url='accounts:login')
    def _wrapped_view(request, *args, **kwargs):
        if request.user.role != 'team_leader':
            messages.error(request, 'Access denied. This workspace is reserved for Team Leaders.')
            return redirect_user_by_role(request.user)
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def member_required(view_func):
    @wraps(view_func)
    @login_required(login_url='accounts:login')
    def _wrapped_view(request, *args, **kwargs):
        if request.user.role != 'member':
            messages.error(request, 'Access denied. This workspace is reserved for Team Members.')
            return redirect_user_by_role(request.user)
        return view_func(request, *args, **kwargs)

    return _wrapped_view
