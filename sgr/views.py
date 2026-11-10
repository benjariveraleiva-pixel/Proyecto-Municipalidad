from django.shortcuts import render

def dashboard_inicio(request):
    return render(request, 'dashboard_preview.html')