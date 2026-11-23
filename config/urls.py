from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from sgr import views, views_admin

urlpatterns = [
    # Autenticación y Dashboard
    path('login/', views.login_institucional, name='login'),
    path('logout/', views.cerrar_sesion, name='logout'),
    path('', views.dashboard_inicio, name='dashboard_inicio'),
    path('dashboard/cumplimiento/', views.dashboard_cumplimiento_view, name='dashboard_cumplimiento'),
    path('dashboard/aprobadas/', views.dashboard_aprobadas_view, name='dashboard_aprobadas'),
    path('dashboard/pendientes/', views.dashboard_pendientes_view, name='dashboard_pendientes'),
    path('dashboard/vencidos/', views.dashboard_vencidos_view, name='dashboard_vencidos'),
    path('funcionarios/nuevo/', views.FuncionarioCreateView.as_view(), name='funcionarios_crear'),

    # Metas y Flujos del Tubo
    path('metas/', views.asignacion_metas_view, name='asignacion_metas'),
    path('tubo-compromisos/', views.tubo_compromisos_view, name='tubo_compromisos'),
    path('tubo-compromisos/<int:pk>/estado/', views.cambiar_estado_compromiso, name='cambiar_estado_compromiso'),
    path('tubo-cartas/', views.tubo_cartas_view, name='tubo_cartas'),
    path('tubo-cartas/<int:pk>/estado/', views.cambiar_estado_carta, name='cambiar_estado_carta'),

    # Mantenedores Operativos (CRUD)
    path('vecinos/', views.VecinoListView.as_view(), name='vecinos_list'),
    path('vecinos/nuevo/', views.VecinoCreateView.as_view(), name='vecinos_crear'),
    path('vecinos/registro-rapido/', views.vecino_registro_rapido_view, name='vecino_registro_rapido'),
    path('vecinos/<int:pk>/editar/', views.VecinoUpdateView.as_view(), name='vecinos_editar'),

    path('juntas/', views.JuntaListView.as_view(), name='juntas_list'),
    path('juntas/nueva/', views.JuntaCreateView.as_view(), name='juntas_crear'),
    path('juntas/<int:pk>/editar/', views.JuntaUpdateView.as_view(), name='juntas_editar'),

    path('hitos/', views.HitoListView.as_view(), name='hitos_list'),
    path('hitos/nuevo/', views.HitoCreateView.as_view(), name='hitos_crear'),
    path('hitos/<int:pk>/editar/', views.HitoUpdateView.as_view(), name='hitos_editar'),

    # Actividades, Evidencias y Verificación
    path('actividades/', views.actividades_list_view, name='actividades_list'),
    path('actividades/<int:pk>/evidencia/', views.adjuntar_evidencia_view, name='adjuntar_evidencia'),
    path('verificacion/', views.bandeja_verificacion_view, name='bandeja_verificacion'),
    path('verificacion/<int:pk>/dictaminar/', views.dictaminar_actividad_view, name='dictaminar_actividad'),

    # Seguridad de Cuentas (Primer acceso y Flujo de 3 pasos de Recuperación)
    path('seguridad/activar-cuenta/', views.cambiar_clave_obligatorio_view, name='cambiar_clave_obligatorio'),
    path('seguridad/recuperar-clave/', views.recuperar_clave_view, name='recuperar_clave'),
    path('seguridad/verificar-codigo/', views.verificar_codigo_view, name='verificar_codigo_recuperacion'),
    path('seguridad/nueva-clave/', views.nueva_clave_recuperacion_view, name='nueva_clave_recuperacion'),

    # Gestiones Sociales, Reportes y Bitácora
    path('gestiones-sociales/', views.gestiones_sociales_view, name='gestiones_sociales'),
    path('gestiones-sociales/actualizar/<int:pk>/', views.actualizar_etapa_social, name='actualizar_etapa_social'),
    path('reportes-bitacora/', views.reportes_bitacora_view, name='reportes_bitacora'),
    path('reportes-bitacora/exportar/', views.exportar_reporte_csv, name='exportar_reporte_csv'),

    # Centro de Administración Integral SGR (Reemplazo total de Django Admin - Solo ADMIN)
    path('administracion/', views_admin.admin_sgr_home, name='admin_sgr_home'),
    path('administracion/<slug:slug>/', views_admin.admin_sgr_list, name='admin_sgr_list'),
    path('administracion/<slug:slug>/nuevo/', views_admin.admin_sgr_crear, name='admin_sgr_crear'),
    path('administracion/<slug:slug>/<int:pk>/editar/', views_admin.admin_sgr_editar, name='admin_sgr_editar'),
    path('administracion/<slug:slug>/<int:pk>/eliminar/', views_admin.admin_sgr_eliminar, name='admin_sgr_eliminar'),

    
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    handler400 = 'sgr.error_handlers.error_400_view'
    handler403 = 'sgr.error_handlers.error_403_view'
    handler404 = 'sgr.error_handlers.error_404_view'
    handler500 = 'sgr.error_handlers.error_500_view'