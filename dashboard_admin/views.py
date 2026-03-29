from django.shortcuts import render
from config.decorators import admin_required


@admin_required
def home(request):
    return render(request, "dashboard_admin/home.html")