from django.shortcuts import render
from config.decorators import manager_required


@manager_required
def home(request):
    return render(request, "ads/home.html")