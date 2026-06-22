from django.shortcuts import render, redirect
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required


@login_required(login_url='accounts:login')
def profile(request):
    return render(request, 'accounts/profile.html', {'user': request.user})


def logout(request):
    auth_logout(request)
    return redirect('accounts:login')
