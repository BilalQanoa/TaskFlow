from django.shortcuts import render, redirect


def register(request):
    return render (request, 'register.html')


def login (request):
    return render (request, 'login.html')


def profile (request):
    return render (request, 'profile.html')

def logout (request):
    pass

