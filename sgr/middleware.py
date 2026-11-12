from django.shortcuts import redirect
from django.urls import reverse


class PrimerAccesoMiddleware:
    """
    Obliga a todo funcionario con credencial temporal (debe_cambiar_clave=True)
    a definir su contraseña definitiva antes de poder navegar por el SGR.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            func = getattr(request.user, 'funcionario', None)
            if func and func.debe_cambiar_clave:
                rutas_permitidas = [
                    reverse('cambiar_clave_obligatorio'),
                    reverse('logout'),
                ]
                if request.path not in rutas_permitidas and not request.path.startswith('/static/'):
                    return redirect('cambiar_clave_obligatorio')

        return self.get_response(request)