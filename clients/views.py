from django.shortcuts import render
from django.http import HttpResponse
from config.decorators import client_required


@client_required
def home(request):
    return render(request, "clients/home.html")