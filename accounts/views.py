from django.shortcuts import render, redirect
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from .decorators import guest_only
from .forms import CompanyRegistrationForm, UserLoginForm


@guest_only
def register(request):
    if request.method == 'POST':
        form = CompanyRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            if user.role == 'company':
                return redirect('dashboard:dashboard')
            return redirect('accounts:profile')
    else:
        form = CompanyRegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})


@guest_only
def login(request):
    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)
            if user.role == 'company':
                return redirect('dashboard:dashboard')
            return redirect('accounts:profile')
    else:
        form = UserLoginForm()

    return render(request, 'accounts/login.html', {'form': form})

@login_required(login_url='accounts:login')
def profile(request):
    return render(request, 'accounts/profile.html', {'user': request.user})

def logout(request):
    auth_logout(request)
    return redirect('accounts:login')