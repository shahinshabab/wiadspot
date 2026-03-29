from django.shortcuts import render
from django.http import HttpResponse
from config.decorators import partner_required


@partner_required
def home(request):
    return render(request, "partner/home.html")