"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from sgr import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', views.login_institucional, name='login'),
    path('logout/', views.cerrar_sesion, name='logout'),
    path('', views.dashboard_inicio, name='dashboard_inicio'),
    path('funcionarios/nuevo/', views.FuncionarioCreateView.as_view(), name='funcionarios_crear'),

    # Nuevas rutas para la entrega del Lunes 16/11
    path('metas/', views.asignacion_metas_view, name='asignacion_metas'),
    path('tubo-compromisos/', views.tubo_compromisos_view, name='tubo_compromisos'),
    path('tubo-compromisos/<int:pk>/estado/', views.cambiar_estado_compromiso, name='cambiar_estado_compromiso'),
    path('tubo-cartas/', views.tubo_cartas_view, name='tubo_cartas'),
    path('tubo-cartas/<int:pk>/estado/', views.cambiar_estado_carta, name='cambiar_estado_carta'),

    # Rutas CRUD
    path('vecinos/', views.VecinoListView.as_view(), name='vecinos_list'),
    path('vecinos/nuevo/', views.VecinoCreateView.as_view(), name='vecinos_crear'),
    path('vecinos/<int:pk>/editar/', views.VecinoUpdateView.as_view(), name='vecinos_editar'),

    path('juntas/', views.JuntaListView.as_view(), name='juntas_list'),
    path('juntas/nueva/', views.JuntaCreateView.as_view(), name='juntas_crear'),
    path('juntas/<int:pk>/editar/', views.JuntaUpdateView.as_view(), name='juntas_editar'),

    path('hitos/', views.HitoListView.as_view(), name='hitos_list'),
    path('hitos/nuevo/', views.HitoCreateView.as_view(), name='hitos_crear'),
    path('hitos/<int:pk>/editar/', views.HitoUpdateView.as_view(), name='hitos_editar'),

    # Módulo de Actividades, Evidencias y Verificación
    path('actividades/', views.actividades_list_view, name='actividades_list'),
    path('actividades/<int:pk>/evidencia/', views.adjuntar_evidencia_view, name='adjuntar_evidencia'),
    path('verificacion/', views.bandeja_verificacion_view, name='bandeja_verificacion'),
    path('verificacion/<int:pk>/dictaminar/', views.dictaminar_actividad_view, name='dictaminar_actividad'),

    # Seguridad de Cuentas (Primer acceso y Recuperación)
    path('seguridad/activar-cuenta/', views.cambiar_clave_obligatorio_view, name='cambiar_clave_obligatorio'),
    path('seguridad/recuperar-clave/', views.recuperar_clave_view, name='recuperar_clave'),

    # Seguridad de Cuentas (Primer acceso y Flujo de 3 pasos de Recuperación)
    path('seguridad/activar-cuenta/', views.cambiar_clave_obligatorio_view, name='cambiar_clave_obligatorio'),
    path('seguridad/recuperar-clave/', views.recuperar_clave_view, name='recuperar_clave'),
    path('seguridad/verificar-codigo/', views.verificar_codigo_view, name='verificar_codigo_recuperacion'),
    path('seguridad/nueva-clave/', views.nueva_clave_recuperacion_view, name='nueva_clave_recuperacion'),

    path('gestiones-sociales/', views.gestiones_sociales_view, name='gestiones_sociales'),
    path('reportes-bitacora/', views.reportes_bitacora_view, name='reportes_bitacora'),
    path('reportes-bitacora/exportar/', views.exportar_reporte_csv, name='exportar_reporte_csv'),

    path('gestiones-sociales/actualizar/<int:pk>/', views.actualizar_etapa_social, name='actualizar_etapa_social'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)