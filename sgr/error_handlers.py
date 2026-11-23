import logging
import pymysql
from django.conf import settings
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.db import DatabaseError, InterfaceError, connection
from django.http import Http404, HttpResponse
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

# Catálogo de errores web genéricos (sin exponer detalles internos)
ERRORES_WEB = {
    400: (
        "Solicitud incorrecta",
        "La petición enviada no es válida o no pudo ser procesada por el sistema."
    ),
    401: (
        "Acceso no autorizado",
        "Debe iniciar sesión con credenciales válidas para acceder a este recurso."
    ),
    403: (
        "Acceso denegado",
        "No cuenta con los permisos necesarios para acceder a esta sección o su sesión de seguridad expiró."
    ),
    404: (
        "Página no encontrada",
        "La dirección o el recurso que intenta consultar no existe o ya no está disponible."
    ),
    405: (
        "Método no permitido",
        "La operación solicitada no está permitida para esta dirección."
    ),
    408: (
        "Tiempo de espera agotado",
        "La solicitud tardó demasiado tiempo en completarse. Intente nuevamente."
    ),
    429: (
        "Demasiadas solicitudes",
        "Se han registrado demasiados intentos en poco tiempo. Espere unos momentos antes de reintentar."
    ),
    500: (
        "Error interno del sistema",
        "Ocurrió un inconveniente inesperado al procesar su solicitud. Por favor, intente nuevamente más tarde."
    ),
    502: (
        "Error de comunicación del servidor",
        "El servidor recibió una respuesta inválida de un servicio interno."
    ),
    503: (
        "Servicio temporalmente no disponible",
        "El sistema no se encuentra disponible en este momento. Intente nuevamente en unos minutos."
    ),
    504: (
        "Tiempo de respuesta agotado",
        "Un servicio interno tardó demasiado en responder. Intente nuevamente en unos instantes."
    ),
}

ERROR_BASE_DATOS = (
    "Error de conexión con la base de datos",
    "No fue posible establecer comunicación con la base de datos en este momento. Intente nuevamente más tarde."
)


def _es_error_base_datos(exc):
    """Detecta cualquier fallo proveniente de Django DB o PyMySQL."""
    return isinstance(exc, (DatabaseError, InterfaceError, pymysql.MySQLError))


def _base_datos_caida():
    """Verifica rápidamente si la conexión a MySQL está caída."""
    try:
        connection.ensure_connection()
        return False
    except Exception:
        return True


def renderizar_error_sgr(codigo, titulo=None, mensaje=None):
    """Renderiza la pantalla institucional de error con respaldo inline a prueba de fallos."""
    default_titulo, default_mensaje = ERRORES_WEB.get(
        codigo,
        ("Error inesperado", "No fue posible completar la operación solicitada.")
    )
    titulo_final = titulo or default_titulo
    mensaje_final = mensaje or default_mensaje
    logo_url = f"{settings.STATIC_URL.rstrip('/')}/img/logo_rojo.jpg"

    context = {
        'codigo': codigo,
        'titulo': titulo_final,
        'mensaje': mensaje_final,
        'logo_url': logo_url,
    }

    try:
        html = render_to_string('error_sgr.html', context)
    except Exception:
        # Respaldo extremo si llegase a faltar incluso templates/error_sgr.html
        html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
        <title>Error {codigo} | SGR</title></head>
        <body style="margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
        background:#7A111E;color:#fff;font-family:Segoe UI,Arial,sans-serif;text-align:center;padding:24px;">
        <div><img src="{logo_url}" style="width:120px;border-radius:16px;margin-bottom:18px;" onerror="this.style.display='none'">
        <div style="font-size:84px;font-weight:800;line-height:1;">{codigo}</div>
        <h1 style="margin:14px 0 8px;">{titulo_final}</h1>
        <p style="max-width:420px;opacity:.9;">{mensaje_final}</p>
        <a href="/" style="display:inline-block;margin-top:20px;padding:10px 24px;background:#fff;
        color:#7A111E;border-radius:8px;text-decoration:none;font-weight:700;">Volver al Inicio</a>
        </div></body></html>"""

    response = HttpResponse(html, status=codigo, content_type='text/html; charset=utf-8')
    response._es_error_sgr = True
    return response


class ManejoErroresSGRMiddleware:
    """
    Intercepta excepciones y respuestas de error HTTP (>= 400) para mostrar siempre
    la pantalla institucional sin filtrar detalles técnicos.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def _activo(self):
        return getattr(settings, 'PANTALLAS_ERROR_PERSONALIZADAS', True) or not settings.DEBUG

    def _ruta_excluida(self, request):
        rutas_estaticas = tuple(
            r for r in (settings.STATIC_URL, settings.MEDIA_URL) if r
        )
        return request.path.startswith(rutas_estaticas)

    def __call__(self, request):
        if not self._activo() or self._ruta_excluida(request):
            return self.get_response(request)

        try:
            response = self.get_response(request)
        except Exception as exc:
            return self._manejar_excepcion(request, exc)

        if response.status_code >= 400 and not getattr(response, '_es_error_sgr', False):
            # Si falló un middleware interno (como SessionMiddleware) con 500 por caída de MySQL
            if response.status_code == 500 and _base_datos_caida():
                titulo, mensaje = ERROR_BASE_DATOS
                return renderizar_error_sgr(503, titulo=titulo, mensaje=mensaje)
            return renderizar_error_sgr(response.status_code)

        return response

    def process_exception(self, request, exception):
        if not self._activo() or self._ruta_excluida(request):
            return None
        return self._manejar_excepcion(request, exception)

    def _manejar_excepcion(self, request, exception):
        # Guardar traza real SOLO en la consola del servidor
        logger.exception("Error interceptado por SGR en %s", request.path)

        if isinstance(exception, Http404):
            return renderizar_error_sgr(404)

        if isinstance(exception, PermissionDenied):
            return renderizar_error_sgr(403)

        if isinstance(exception, SuspiciousOperation):
            return renderizar_error_sgr(400)

        if _es_error_base_datos(exception):
            titulo, mensaje = ERROR_BASE_DATOS
            return renderizar_error_sgr(503, titulo=titulo, mensaje=mensaje)

        return renderizar_error_sgr(500)


# ==============================================================================
# MANEJADORES OFICIALES DE DJANGO (PRODUCCIÓN CON DEBUG = False)
# ==============================================================================
def error_400_view(request, exception=None):
    return renderizar_error_sgr(400)


def error_403_view(request, exception=None):
    return renderizar_error_sgr(403)


def error_404_view(request, exception=None):
    return renderizar_error_sgr(404)


def error_500_view(request):
    if _base_datos_caida():
        titulo, mensaje = ERROR_BASE_DATOS
        return renderizar_error_sgr(503, titulo=titulo, mensaje=mensaje)
    return renderizar_error_sgr(500)


def error_csrf_view(request, reason=""):
    return renderizar_error_sgr(
        403,
        titulo="Sesión de seguridad expirada",
        mensaje="La verificación de seguridad del formulario venció o no es válida. Vuelva atrás, recargue la página e intente nuevamente."
    )