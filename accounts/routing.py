from django.shortcuts import redirect


def resolve_dashboard_route(user):
    """Return the named URL route for a user's role-based home dashboard."""
    if user.is_superuser or getattr(user, 'role', None) == 'company':
        return 'dashboard:dashboard'

    role = getattr(user, 'role', None)

    if role == 'team_leader':
        return 'management:team_leader_dashboard'

    if role in ('member', 'team_member'):
        return 'management:member_dashboard'

    return 'dashboard:profile'


def redirect_user_by_role(user):
    return redirect(resolve_dashboard_route(user))
