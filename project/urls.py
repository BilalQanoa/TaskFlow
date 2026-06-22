
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

from dashboard import views as dashboard_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('pages.urls')),
    path('accounts/', include('accounts.urls')),
    path('companies/', include('companies.urls')),
    path('dashboard/', include(('dashboard.urls', 'dashboard'), namespace='dashboard')),
    path('management/', include(('management.urls', 'management'), namespace='management')),
    path(
        'activate-employee/<uidb64>/<token>/',
        dashboard_views.activate_employee,
        name='activate_employee',
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
