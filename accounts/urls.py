from django.urls import path

from dashboard.views import login, register, resend_otp, verify_otp
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', login, name='login'),
    path('register/', register, name='register'),
    path('verify-otp/', verify_otp, name='verify_otp'),
    path('resend-otp/', resend_otp, name='resend_otp'),
    path('logout/', views.logout, name='logout'),
    path('profile/', views.profile, name='profile'),
]
