"""Root URL configuration: admin at /avcadmin/, API at /api/."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("avcadmin/", admin.site.urls),
    path("api/", include("wareApp.urls")),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

admin.site.site_header = "Aviconn Admin"
admin.site.site_title = "Aviconn Admin Portal"
admin.site.index_title = "Welcome to Aviconn Portal"
