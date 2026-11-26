import csv
import os
import random
import string
from functools import wraps
from decouple import config
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import ListView, CreateView, UpdateView

from .models import (
    Delegacion, Funcionario, Trimestre, Territorio, AsignacionMeta, Actividad,
    TuboCarta, BitacoraAuditoria, HistorialTubo, Vecino, JuntaVecinos,
    Hito, Evidencia, GestionSocial
)
from .forms import (
    AsignacionMetaForm, CompromisoTuboForm, TuboCartaForm,
    VecinoForm, JuntaVecinosForm, HitoForm, FuncionarioCreateForm,
    FuncionarioUpdateForm, ActividadRegistroForm, ActividadEditarForm,
    SubirEvidenciaForm
)


# ==============================================================================
# CONTROL DE PERMISOS POR ROL (RBAC)
# ==============================================================================
def usuario_tiene_algun_rol(user, roles_permitidos):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    func = getattr(user, 'funcionario', None)
    if not func:
        return False
    if func.tiene_rol('ADMIN'):
        return True
    return func.roles.filter(nombre__in=roles_permitidos, activo=True).exists()


def roles_requeridos(*roles_permitidos):
    def decorator(view_func):
        @wraps(view_func)
        @login_required(login_url='login')
        def _wrapped_view(request, *args, **kwargs):
            if not usuario_tiene_algun_rol(request.user, roles_permitidos):
                messages.error(
                    request,
                    "Acceso denegado: su perfil de usuario no tiene permisos para ingresar a ese módulo."
                )
                return redirect('dashboard_inicio')
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


class RolesRequeridosMixin(LoginRequiredMixin):
    roles_permitidos = []
    login_url = 'login'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.roles_permitidos and not usuario_tiene_algun_rol(request.user, self.roles_permitidos):
            messages.error(
                request,
                "Acceso denegado: su perfil de usuario no tiene permisos para ingresar a ese módulo."
            )
            return redirect('dashboard_inicio')
        return super().dispatch(request, *args, **kwargs)


def enviar_correo_institucional(destinatario, asunto, cuerpo):
    remitente = config('EMAIL_HOST_USER')
    clave = config('EMAIL_HOST_PASSWORD')

    try:
        send_mail(
            subject=asunto,
            message=cuerpo,
            from_email=remitente,
            recipient_list=[destinatario],
            fail_silently=False,
        )
    except Exception:
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(cuerpo, 'plain', 'utf-8')
        msg['Subject'] = asunto
        msg['From'] = f"SGR Municipalidad de La Serena <{remitente}>"
        msg['To'] = destinatario

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(remitente, clave)
            server.send_message(msg)


def login_institucional(request):
    if request.user.is_authenticated:
        return redirect('dashboard_inicio')

    if request.method == 'POST':
        identificador = request.POST.get('username', '').strip()
        clave = request.POST.get('password', '')

        func = Funcionario.objects.filter(
            Q(user__username__iexact=identificador) | Q(correo__iexact=identificador)
        ).select_related('user').first()

        if func and func.bloqueado_hasta and func.bloqueado_hasta > timezone.now():
            messages.error(request, "Cuenta bloqueada temporalmente por múltiples intentos fallidos. Intente más tarde.")
            return render(request, 'login.html')

        username_real = func.user.username if func else identificador
        user = authenticate(request, username=username_real, password=clave)

        if user is not None:
            if func:
                func.intentos_fallidos = 0
                func.bloqueado_hasta = None
                func.ultimo_acceso = timezone.now()
                func.save()
                BitacoraAuditoria.objects.create(
                    usuario=func, modulo='Seguridad', accion='Inicio de Sesión', detalle='Ingreso exitoso al SGR'
                )
            login(request, user)
            if func and func.debe_cambiar_clave:
                messages.warning(request, "Por seguridad institucional, debe definir su contraseña personal definitiva antes de continuar.")
                return redirect('cambiar_clave_obligatorio')
            return redirect('dashboard_inicio')
        else:
            if func:
                func.intentos_fallidos += 1
                if func.intentos_fallidos >= 5:
                    func.bloqueado_hasta = timezone.now() + timezone.timedelta(minutes=15)
                func.save()
            messages.error(request, "Credenciales incorrectas. Verifique su usuario y contraseña.")

    return render(request, 'login.html')


@login_required(login_url='login')
def cerrar_sesion(request):
    logout(request)
    messages.info(request, "Ha cerrado su sesión institucional correctamente.")
    return redirect('login')


# ==============================================================================
# DASHBOARD DIFERENCIADO POR ROL CON FILTRO POR DELEGACIÓN Y GRÁFICOS REALES
# ==============================================================================
@login_required(login_url='login')
def dashboard_inicio(request):
    trimestres = Trimestre.objects.all().order_by('-anio', '-numero')
    trimestre_id = request.GET.get('trimestre')
    trimestre_activo = trimestres.filter(id=trimestre_id).first() if trimestre_id else trimestres.first()

    func_actual = getattr(request.user, 'funcionario', None)
    delegacion_actual = func_actual.delegacion if func_actual else None

    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)
    es_delegado = bool(func_actual and func_actual.es_delegado and not es_admin)
    es_verificador = bool(func_actual and func_actual.es_verificador and not es_admin and not es_delegado)
    es_vista_personal = bool(func_actual and func_actual.es_solo_funcionario)
    puede_filtrar_delegacion = bool(es_admin or es_verificador)

    filtro_delegacion = request.GET.get('delegacion', '').strip()
    filtro_funcionario = request.GET.get('funcionario', '').strip()
    filtro_q = request.GET.get('q', '').strip()

    # Actualizar automáticamente compromisos vencidos
    hoy = timezone.localdate()
    Actividad.objects.filter(
        ingresa_al_tubo=True,
        estado_tubo__in=['PENDIENTE', 'EN_PROCESO'],
        fecha_compromiso__lt=hoy
    ).update(estado_tubo='VENCIDO')

    actividades_qs = Actividad.objects.select_related(
        'funcionario_autor', 'responsable_tubo', 'territorio', 'meta_asignada__meta', 'junta_solicitante'
    )
    asignaciones_qs = AsignacionMeta.objects.filter(activa=True).select_related('funcionario', 'meta')
    cartas_qs = TuboCarta.objects.select_related('responsable_seguimiento', 'delegacion')

    if trimestre_activo:
        asignaciones_qs = asignaciones_qs.filter(trimestre=trimestre_activo)
        actividades_qs = actividades_qs.filter(meta_asignada__trimestre=trimestre_activo)

    delegaciones_lista = Delegacion.objects.filter(activa=True).order_by('nombre')

    # Alcance automático según Rol
    if es_vista_personal and func_actual:
        modo_dashboard = 'PERSONAL'
        titulo_dashboard = f"Mi Panel de Gestión Personal · {func_actual.nombre_completo}"
        funcionarios_lista = Funcionario.objects.filter(id=func_actual.id).select_related('cargo', 'delegacion')
        delegaciones_lista = Delegacion.objects.filter(id=delegacion_actual.id) if delegacion_actual else Delegacion.objects.none()

        actividades_qs = actividades_qs.filter(
            Q(funcionario_autor=func_actual) | Q(responsable_tubo=func_actual)
        )
        asignaciones_qs = asignaciones_qs.filter(funcionario=func_actual)
        cartas_qs = cartas_qs.filter(responsable_seguimiento=func_actual)
        filtro_delegacion = str(delegacion_actual.id) if delegacion_actual else ''
        filtro_funcionario = str(func_actual.id)
    elif es_delegado and delegacion_actual:
        modo_dashboard = 'DELEGACION'
        titulo_dashboard = f"Panel de Delegación {delegacion_actual.nombre}"
        funcionarios_lista = Funcionario.objects.filter(delegacion=delegacion_actual).select_related('cargo', 'delegacion').order_by('nombres')
        delegaciones_lista = Delegacion.objects.filter(id=delegacion_actual.id)
        filtro_delegacion = str(delegacion_actual.id)

        actividades_qs = actividades_qs.filter(
            Q(territorio__delegacion=delegacion_actual) |
            Q(funcionario_autor__delegacion=delegacion_actual) |
            Q(responsable_tubo__delegacion=delegacion_actual)
        )
        asignaciones_qs = asignaciones_qs.filter(funcionario__delegacion=delegacion_actual)
        cartas_qs = cartas_qs.filter(delegacion=delegacion_actual)
    elif es_verificador:
        modo_dashboard = 'VERIFICACION'
        titulo_dashboard = "Panel de Verificación y Control de Evidencias"
        funcionarios_lista = Funcionario.objects.select_related('cargo', 'delegacion').order_by('nombres')
    else:
        modo_dashboard = 'GLOBAL'
        titulo_dashboard = "Panel Global · Coordinación de Delegaciones La Serena"
        funcionarios_lista = Funcionario.objects.select_related('cargo', 'delegacion').order_by('nombres')

    # Filtro por Delegación (Admin y Verificador)
    if puede_filtrar_delegacion and filtro_delegacion:
        delegacion_filtrada = delegaciones_lista.filter(id=filtro_delegacion).first()
        if delegacion_filtrada:
            delegacion_actual = delegacion_filtrada
            titulo_dashboard = f"Panel de Delegación {delegacion_filtrada.nombre}"
            funcionarios_lista = funcionarios_lista.filter(delegacion=delegacion_filtrada)
            actividades_qs = actividades_qs.filter(
                Q(funcionario_autor__delegacion=delegacion_filtrada) |
                Q(responsable_tubo__delegacion=delegacion_filtrada) |
                Q(territorio__delegacion=delegacion_filtrada)
            )
            asignaciones_qs = asignaciones_qs.filter(funcionario__delegacion=delegacion_filtrada)
            cartas_qs = cartas_qs.filter(delegacion=delegacion_filtrada)
        else:
            filtro_delegacion = ''

    # Si el funcionario seleccionado no pertenece a la delegación filtrada, limpiar selección
    if filtro_funcionario and not es_vista_personal:
        if not funcionarios_lista.filter(id=filtro_funcionario).exists():
            filtro_funcionario = ''

    # Filtro por Funcionario
    if filtro_funcionario and not es_vista_personal:
        actividades_qs = actividades_qs.filter(
            Q(funcionario_autor_id=filtro_funcionario) | Q(responsable_tubo_id=filtro_funcionario)
        )
        asignaciones_qs = asignaciones_qs.filter(funcionario_id=filtro_funcionario)
        cartas_qs = cartas_qs.filter(responsable_seguimiento_id=filtro_funcionario)

    if filtro_q:
        actividades_qs = actividades_qs.filter(
            Q(codigo__icontains=filtro_q) |
            Q(solicitante_nombre__icontains=filtro_q) |
            Q(solicitante_rut__icontains=filtro_q) |
            Q(junta_solicitante__nombre__icontains=filtro_q)
        )

    # KPIs Reales
    if es_vista_personal and func_actual:
        actividades_propias = actividades_qs.filter(funcionario_autor=func_actual)
        total_aprobadas = actividades_propias.filter(estado_verificacion='APROBADA_PONDERA').count()
        total_pendientes_verif = actividades_propias.filter(estado_verificacion='PENDIENTE').count()
        total_vencidos = actividades_qs.filter(
            ingresa_al_tubo=True, responsable_tubo=func_actual, estado_tubo='VENCIDO'
        ).count()
    else:
        total_aprobadas = actividades_qs.filter(estado_verificacion='APROBADA_PONDERA').count()
        total_pendientes_verif = actividades_qs.filter(estado_verificacion='PENDIENTE').count()
        total_vencidos = actividades_qs.filter(ingresa_al_tubo=True, estado_tubo='VENCIDO').count()

    # Semáforo real por funcionario (normalizado en base al 100% del usuario)
    semaforo_funcionarios = []
    suma_cumplimientos = 0.0
    funcionarios_para_semaforo = funcionarios_lista
    if filtro_funcionario and not es_vista_personal:
        funcionarios_para_semaforo = funcionarios_lista.filter(id=filtro_funcionario)

    for f in funcionarios_para_semaforo:
        metas_f = AsignacionMeta.objects.filter(funcionario=f, trimestre=trimestre_activo, activa=True)
        if not metas_f.exists():
            continue

        total_ponderacion_f = sum(float(m.ponderacion) for m in metas_f)
        cumplimiento_pond_total = sum(m.resultado_ponderado for m in metas_f)

        if total_ponderacion_f > 0:
            cumplimiento_base_100 = min(round((cumplimiento_pond_total / total_ponderacion_f) * 100.0, 1), 100.0)
        else:
            cumplimiento_base_100 = 0.0

        ingresos_f = Actividad.objects.filter(
            funcionario_autor=f, meta_asignada__trimestre=trimestre_activo
        ).count() if trimestre_activo else Actividad.objects.filter(funcionario_autor=f).count()

        if cumplimiento_base_100 >= 80:
            color = 'verde'
        elif cumplimiento_base_100 >= 55:
            color = 'amarillo'
        else:
            color = 'rojo'

        semaforo_funcionarios.append({
            'funcionario': f,
            'cumplimiento_ponderado': cumplimiento_base_100,
            'ponderacion_asignada': round(total_ponderacion_f, 1),
            'total_ingresos': ingresos_f,
            'color_semaforo': color,
        })
        suma_cumplimientos += cumplimiento_base_100

    cumplimiento_general = round(suma_cumplimientos / len(semaforo_funcionarios), 1) if semaforo_funcionarios else 0.0
    meta_esperada_hoy = trimestre_activo.porcentaje_esperado_hoy if trimestre_activo else 0.0

    # ==========================================================================
    # DATOS REALES PARA LOS 3 GRÁFICOS (CHART.JS)
    # ==========================================================================
    tubo_qs = actividades_qs.filter(ingresa_al_tubo=True)

    # Gráfico 1: Estado del Tubo de Compromisos
    chart_tubo_data = {
        'labels': ['Pendiente', 'En Proceso', 'Realizado', 'Cerrado', 'Vencido'],
        'values': [
            tubo_qs.filter(estado_tubo='PENDIENTE').count(),
            tubo_qs.filter(estado_tubo='EN_PROCESO').count(),
            tubo_qs.filter(estado_tubo='REALIZADO').count(),
            tubo_qs.filter(estado_tubo='CERRADO').count(),
            tubo_qs.filter(estado_tubo='VENCIDO').count(),
        ]
    }

    # Gráfico 2: Cumplimiento de Metas (Esperado a hoy vs Real con Tope 120%)
    metas_labels = []
    metas_reales = []
    metas_esperadas = []
    for asig in asignaciones_qs[:10]:
        etiqueta = f"{asig.meta.codigo} ({asig.funcionario.nombres.split()[0]})" if not es_vista_personal else f"{asig.meta.codigo} · {asig.meta.nombre[:22]}"
        metas_labels.append(etiqueta)
        metas_reales.append(float(asig.porcentaje_cumplimiento_aplicable))
        metas_esperadas.append(float(meta_esperada_hoy))

    chart_metas_data = {
        'labels': metas_labels,
        'reales': metas_reales,
        'esperadas': metas_esperadas,
    }

    # Gráfico 3: Carga por Funcionario (Equipo) o Estado de Mis Actividades (Personal)
    if es_vista_personal and func_actual:
        acts_verif = actividades_qs.filter(funcionario_autor=func_actual)
        chart_tercero_data = {
            'tipo': 'dona_verificacion',
            'labels': ['Aprobada y Pondera', 'Aprobada No Pondera', 'Pendiente Revisión', 'Solicita Antecedentes', 'Rechazada'],
            'values': [
                acts_verif.filter(estado_verificacion='APROBADA_PONDERA').count(),
                acts_verif.filter(estado_verificacion='APROBADA_NO_PONDERA').count(),
                acts_verif.filter(estado_verificacion='PENDIENTE').count(),
                acts_verif.filter(estado_verificacion='SOLICITUD_ANTECEDENTES').count(),
                acts_verif.filter(estado_verificacion='RECHAZADA').count(),
            ]
        }
    else:
        carga_labels = []
        carga_pendiente = []
        carga_proceso = []
        carga_cerrado = []
        carga_vencido = []

        for f in funcionarios_para_semaforo:
            tubo_f = tubo_qs.filter(responsable_tubo=f)
            if not tubo_f.exists():
                continue
            carga_labels.append(f.nombre_completo)
            carga_pendiente.append(tubo_f.filter(estado_tubo='PENDIENTE').count())
            carga_proceso.append(tubo_f.filter(estado_tubo='EN_PROCESO').count())
            carga_cerrado.append(tubo_f.filter(estado_tubo__in=['REALIZADO', 'CERRADO']).count())
            carga_vencido.append(tubo_f.filter(estado_tubo='VENCIDO').count())

        chart_tercero_data = {
            'tipo': 'carga_funcionarios',
            'labels': carga_labels,
            'pendientes': carga_pendiente,
            'en_proceso': carga_proceso,
            'cerrados': carga_cerrado,
            'vencidos': carga_vencido,
        }

    # Tabla resumen del Tubo
    items_tubo = []
    mapa_badges = {
        'PENDIENTE': 'estado-pendiente',
        'EN_PROCESO': 'estado-proceso',
        'REALIZADO': 'estado-realizado',
        'CERRADO': 'estado-realizado',
        'VENCIDO': 'estado-vencido',
    }
    for act in tubo_qs.order_by('fecha_compromiso')[:6]:
        items_tubo.append({
            'codigo': act.codigo,
            'solicitante': act.solicitante_nombre,
            'responsable': act.responsable_tubo.nombre_completo,
            'fecha_compromiso': act.fecha_compromiso,
            'estado_label': act.get_estado_tubo_display(),
            'clase_badge': mapa_badges.get(act.estado_tubo, 'estado-proceso')
        })

    for carta in cartas_qs[:4]:
        items_tubo.append({
            'codigo': carta.codigo,
            'solicitante': f"{carta.remitente} (Carta)",
            'responsable': carta.responsable_seguimiento.nombre_completo,
            'fecha_compromiso': carta.fecha_respuesta_compromiso,
            'estado_label': carta.get_estado_display(),
            'clase_badge': 'estado-proceso'
        })

    params_filtros = []
    if trimestre_activo:
        params_filtros.append(f"trimestre={trimestre_activo.id}")
    if filtro_delegacion and puede_filtrar_delegacion:
        params_filtros.append(f"delegacion={filtro_delegacion}")
    if filtro_funcionario and not es_vista_personal:
        params_filtros.append(f"funcionario={filtro_funcionario}")
    query_filtros = f"?{'&'.join(params_filtros)}" if params_filtros else ""

    context = {
        'modo_dashboard': modo_dashboard,
        'titulo_dashboard': titulo_dashboard,
        'es_vista_personal': es_vista_personal,
        'puede_filtrar_delegacion': puede_filtrar_delegacion,
        'delegacion_actual': delegacion_actual,
        'trimestres': trimestres,
        'trimestre_activo': trimestre_activo,
        'meta_esperada_hoy': meta_esperada_hoy,
        'delegaciones_lista': delegaciones_lista,
        'funcionarios_lista': funcionarios_lista,
        'filtro_delegacion': filtro_delegacion,
        'filtro_funcionario': filtro_funcionario,
        'filtro_q': filtro_q,
        'query_filtros': query_filtros,
        'cumplimiento_general': cumplimiento_general,
        'total_aprobadas': total_aprobadas,
        'total_pendientes_verif': total_pendientes_verif,
        'total_vencidos': total_vencidos,
        'asignaciones_metas': asignaciones_qs,
        'semaforo_funcionarios': semaforo_funcionarios,
        'items_tubo': items_tubo,
        'chart_tubo_data': chart_tubo_data,
        'chart_metas_data': chart_metas_data,
        'chart_tercero_data': chart_tercero_data,
    }
    return render(request, 'dashboard_preview.html', context)


# ==============================================================================
# SUB-DASHBOARDS DEDICADOS POR KPI (DRILL-DOWN DE PANTALLA COMPLETA)
# ==============================================================================
def _obtener_base_dashboard(request):
    trimestres = Trimestre.objects.all().order_by('-anio', '-numero')
    trimestre_id = request.GET.get('trimestre')
    trimestre_activo = trimestres.filter(id=trimestre_id).first() if trimestre_id else trimestres.first()

    func_actual = getattr(request.user, 'funcionario', None)
    delegacion_actual = func_actual.delegacion if func_actual else None

    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)
    es_delegado = bool(func_actual and func_actual.es_delegado and not es_admin)
    es_verificador = bool(func_actual and func_actual.es_verificador and not es_admin and not es_delegado)
    es_vista_personal = bool(func_actual and func_actual.es_solo_funcionario)
    puede_filtrar_delegacion = bool(es_admin or es_verificador)

    filtro_delegacion = request.GET.get('delegacion', '').strip()
    filtro_funcionario = request.GET.get('funcionario', '').strip()

    hoy = timezone.localdate()
    Actividad.objects.filter(
        ingresa_al_tubo=True,
        estado_tubo__in=['PENDIENTE', 'EN_PROCESO'],
        fecha_compromiso__lt=hoy
    ).update(estado_tubo='VENCIDO')

    actividades_qs = Actividad.objects.select_related(
        'funcionario_autor', 'funcionario_autor__delegacion', 'funcionario_autor__cargo',
        'responsable_tubo', 'responsable_tubo__delegacion',
        'territorio', 'territorio__delegacion',
        'meta_asignada__meta', 'verificado_por', 'junta_solicitante'
    ).prefetch_related('evidencias')

    asignaciones_qs = AsignacionMeta.objects.filter(activa=True).select_related(
        'funcionario', 'funcionario__cargo', 'funcionario__delegacion', 'meta', 'trimestre'
    )

    if trimestre_activo:
        asignaciones_qs = asignaciones_qs.filter(trimestre=trimestre_activo)
        actividades_qs = actividades_qs.filter(meta_asignada__trimestre=trimestre_activo)

    delegaciones_lista = Delegacion.objects.filter(activa=True).order_by('nombre')

    if es_vista_personal and func_actual:
        funcionarios_lista = Funcionario.objects.filter(id=func_actual.id).select_related('cargo', 'delegacion')
        delegaciones_lista = Delegacion.objects.filter(id=delegacion_actual.id) if delegacion_actual else Delegacion.objects.none()
        actividades_qs = actividades_qs.filter(Q(funcionario_autor=func_actual) | Q(responsable_tubo=func_actual))
        asignaciones_qs = asignaciones_qs.filter(funcionario=func_actual)
        filtro_delegacion = str(delegacion_actual.id) if delegacion_actual else ''
        filtro_funcionario = str(func_actual.id)
    elif es_delegado and delegacion_actual:
        funcionarios_lista = Funcionario.objects.filter(delegacion=delegacion_actual).select_related('cargo', 'delegacion').order_by('nombres')
        delegaciones_lista = Delegacion.objects.filter(id=delegacion_actual.id)
        filtro_delegacion = str(delegacion_actual.id)
        actividades_qs = actividades_qs.filter(
            Q(territorio__delegacion=delegacion_actual) |
            Q(funcionario_autor__delegacion=delegacion_actual) |
            Q(responsable_tubo__delegacion=delegacion_actual)
        )
        asignaciones_qs = asignaciones_qs.filter(funcionario__delegacion=delegacion_actual)
    else:
        funcionarios_lista = Funcionario.objects.select_related('cargo', 'delegacion').order_by('nombres')

    if puede_filtrar_delegacion and filtro_delegacion:
        delegacion_filtrada = delegaciones_lista.filter(id=filtro_delegacion).first()
        if delegacion_filtrada:
            delegacion_actual = delegacion_filtrada
            funcionarios_lista = funcionarios_lista.filter(delegacion=delegacion_filtrada)
            actividades_qs = actividades_qs.filter(
                Q(funcionario_autor__delegacion=delegacion_filtrada) |
                Q(responsable_tubo__delegacion=delegacion_filtrada) |
                Q(territorio__delegacion=delegacion_filtrada)
            )
            asignaciones_qs = asignaciones_qs.filter(funcionario__delegacion=delegacion_filtrada)
        else:
            filtro_delegacion = ''

    if filtro_funcionario and not es_vista_personal:
        if not funcionarios_lista.filter(id=filtro_funcionario).exists():
            filtro_funcionario = ''

    if filtro_funcionario and not es_vista_personal:
        actividades_qs = actividades_qs.filter(
            Q(funcionario_autor_id=filtro_funcionario) | Q(responsable_tubo_id=filtro_funcionario)
        )
        asignaciones_qs = asignaciones_qs.filter(funcionario_id=filtro_funcionario)

    params = []
    if trimestre_activo:
        params.append(f"trimestre={trimestre_activo.id}")
    if filtro_delegacion and puede_filtrar_delegacion:
        params.append(f"delegacion={filtro_delegacion}")
    if filtro_funcionario and not es_vista_personal:
        params.append(f"funcionario={filtro_funcionario}")
    query_filtros = f"?{'&'.join(params)}" if params else ""

    meta_esperada_hoy = trimestre_activo.porcentaje_esperado_hoy if trimestre_activo else 0.0

    return {
        'func_actual': func_actual,
        'es_admin': es_admin,
        'es_verificador': es_verificador,
        'es_vista_personal': es_vista_personal,
        'puede_filtrar_delegacion': puede_filtrar_delegacion,
        'delegacion_actual': delegacion_actual,
        'trimestres': trimestres,
        'trimestre_activo': trimestre_activo,
        'meta_esperada_hoy': meta_esperada_hoy,
        'delegaciones_lista': delegaciones_lista,
        'funcionarios_lista': funcionarios_lista,
        'filtro_delegacion': filtro_delegacion,
        'filtro_funcionario': filtro_funcionario,
        'query_filtros': query_filtros,
        'actividades_qs': actividades_qs,
        'asignaciones_qs': asignaciones_qs,
    }


@login_required(login_url='login')
def dashboard_cumplimiento_view(request):
    base = _obtener_base_dashboard(request)
    funcionarios_scope = base['funcionarios_lista']
    if base['filtro_funcionario'] and not base['es_vista_personal']:
        funcionarios_scope = funcionarios_scope.filter(id=base['filtro_funcionario'])

    semaforo_funcionarios = []
    suma_cumplimientos = 0.0

    for f in funcionarios_scope:
        metas_f = AsignacionMeta.objects.filter(
            funcionario=f, trimestre=base['trimestre_activo'], activa=True
        ).select_related('meta')
        if not metas_f.exists():
            continue

        total_pond = sum(float(m.ponderacion) for m in metas_f)
        pond_obtenida = sum(m.resultado_ponderado for m in metas_f)
        cumpl_base_100 = min(round((pond_obtenida / total_pond) * 100.0, 1), 100.0) if total_pond > 0 else 0.0
        brecha_f = round(cumpl_base_100 - float(base['meta_esperada_hoy']), 1)

        color = 'verde' if cumpl_base_100 >= 80 else ('amarillo' if cumpl_base_100 >= 55 else 'rojo')
        semaforo_funcionarios.append({
            'funcionario': f,
            'cumplimiento': cumpl_base_100,
            'ponderacion_asignada': round(total_pond, 1),
            'cantidad_metas': metas_f.count(),
            'brecha': brecha_f,
            'color_semaforo': color,
        })
        suma_cumplimientos += cumpl_base_100

    semaforo_funcionarios.sort(key=lambda x: x['cumplimiento'], reverse=True)
    cumplimiento_general = round(suma_cumplimientos / len(semaforo_funcionarios), 1) if semaforo_funcionarios else 0.0
    brecha_general = round(cumplimiento_general - float(base['meta_esperada_hoy']), 1)

    chart_cumplimiento = {
        'labels': [item['funcionario'].nombre_completo for item in semaforo_funcionarios],
        'reales': [item['cumplimiento'] for item in semaforo_funcionarios],
        'esperado': [float(base['meta_esperada_hoy']) for _ in semaforo_funcionarios],
    }

    context = {
        **base,
        'seccion_activa': 'cumplimiento',
        'cumplimiento_general': cumplimiento_general,
        'brecha_general': brecha_general,
        'semaforo_funcionarios': semaforo_funcionarios,
        'asignaciones_metas': base['asignaciones_qs'].order_by('funcionario__nombres', 'meta__codigo'),
        'chart_cumplimiento': chart_cumplimiento,
    }
    return render(request, 'dashboards/cumplimiento.html', context)


@login_required(login_url='login')
def dashboard_aprobadas_view(request):
    base = _obtener_base_dashboard(request)
    qs = base['actividades_qs']
    if base['es_vista_personal'] and base['func_actual']:
        qs = qs.filter(funcionario_autor=base['func_actual'])

    aprobadas_qs = qs.filter(estado_verificacion='APROBADA_PONDERA').order_by('-fecha_verificacion', '-id')
    no_ponderan_count = qs.filter(estado_verificacion='APROBADA_NO_PONDERA').count()
    con_evidencia_count = aprobadas_qs.filter(evidencias__isnull=False).distinct().count()

    conteo_por_func = {}
    for act in aprobadas_qs:
        nombre = act.funcionario_autor.nombre_completo
        conteo_por_func[nombre] = conteo_por_func.get(nombre, 0) + 1

    ordenado = sorted(conteo_por_func.items(), key=lambda x: x[1], reverse=True)
    chart_aprobadas = {
        'labels': [x[0] for x in ordenado],
        'values': [x[1] for x in ordenado],
    }

    context = {
        **base,
        'seccion_activa': 'aprobadas',
        'actividades_aprobadas': aprobadas_qs,
        'total_aprobadas': aprobadas_qs.count(),
        'no_ponderan_count': no_ponderan_count,
        'con_evidencia_count': con_evidencia_count,
        'chart_aprobadas': chart_aprobadas,
    }
    return render(request, 'dashboards/aprobadas.html', context)


@login_required(login_url='login')
def dashboard_pendientes_view(request):
    base = _obtener_base_dashboard(request)
    qs = base['actividades_qs']
    if base['es_vista_personal'] and base['func_actual']:
        qs = qs.filter(funcionario_autor=base['func_actual'])

    pendientes_qs = qs.filter(estado_verificacion='PENDIENTE').order_by('fecha_registro', 'id')
    hoy = timezone.localdate()

    pendientes_lista = []
    conteo_por_func = {}
    con_evidencia = 0
    max_espera = 0

    for act in pendientes_qs:
        fecha_base = act.fecha_registro.date() if act.fecha_registro else act.fecha_actividad
        dias_espera = max((hoy - fecha_base).days, 0) if fecha_base else 0
        if dias_espera > max_espera:
            max_espera = dias_espera
        evidencias_list = list(act.evidencias.all())
        if evidencias_list:
            con_evidencia += 1

        nombre = act.funcionario_autor.nombre_completo
        conteo_por_func[nombre] = conteo_por_func.get(nombre, 0) + 1
        pendientes_lista.append({
            'actividad': act,
            'dias_espera': dias_espera,
            'evidencias': evidencias_list,
        })

    ordenado = sorted(conteo_por_func.items(), key=lambda x: x[1], reverse=True)
    chart_pendientes = {
        'labels': [x[0] for x in ordenado],
        'values': [x[1] for x in ordenado],
    }

    context = {
        **base,
        'seccion_activa': 'pendientes',
        'pendientes_lista': pendientes_lista,
        'total_pendientes': len(pendientes_lista),
        'con_evidencia': con_evidencia,
        'max_espera': max_espera,
        'chart_pendientes': chart_pendientes,
    }
    return render(request, 'dashboards/pendientes.html', context)


@login_required(login_url='login')
def dashboard_vencidos_view(request):
    base = _obtener_base_dashboard(request)
    tubo_qs = base['actividades_qs'].filter(ingresa_al_tubo=True)
    if base['es_vista_personal'] and base['func_actual']:
        tubo_qs = tubo_qs.filter(responsable_tubo=base['func_actual'])

    vencidos_qs = tubo_qs.filter(estado_tubo='VENCIDO').order_by('fecha_compromiso', 'id')
    activos_tubo_count = tubo_qs.filter(estado_tubo__in=['PENDIENTE', 'EN_PROCESO']).count()
    hoy = timezone.localdate()

    vencidos_lista = []
    conteo_por_resp = {}
    max_atraso = 0

    for act in vencidos_qs:
        dias_atraso = max((hoy - act.fecha_compromiso).days, 0) if act.fecha_compromiso else 0
        if dias_atraso > max_atraso:
            max_atraso = dias_atraso
        resp_nombre = act.responsable_tubo.nombre_completo
        conteo_por_resp[resp_nombre] = conteo_por_resp.get(resp_nombre, 0) + 1
        vencidos_lista.append({
            'actividad': act,
            'dias_atraso': dias_atraso,
        })

    ordenado = sorted(conteo_por_resp.items(), key=lambda x: x[1], reverse=True)
    chart_vencidos = {
        'labels': [x[0] for x in ordenado],
        'values': [x[1] for x in ordenado],
    }

    context = {
        **base,
        'seccion_activa': 'vencidos',
        'vencidos_lista': vencidos_lista,
        'total_vencidos': len(vencidos_lista),
        'max_atraso': max_atraso,
        'activos_tubo_count': activos_tubo_count,
        'chart_vencidos': chart_vencidos,
    }
    return render(request, 'dashboards/vencidos.html', context)


# ==============================================================================
# GESTIÓN INTERNA DE FUNCIONARIOS (SOLO ADMIN - SIN ACCESO AL PANEL TÉCNICO)
# ==============================================================================
@roles_requeridos('ADMIN')
def funcionarios_list_view(request):
    q = request.GET.get('q', '').strip()
    delegacion_id = request.GET.get('delegacion', '').strip()
    estado_filtro = request.GET.get('estado', '').strip()

    funcionarios = Funcionario.objects.select_related('user', 'cargo', 'delegacion').prefetch_related('roles').order_by('nombres', 'apellidos')

    if q:
        funcionarios = funcionarios.filter(
            Q(nombres__icontains=q) |
            Q(apellidos__icontains=q) |
            Q(rut__icontains=q) |
            Q(correo__icontains=q) |
            Q(user__username__icontains=q)
        )
    if delegacion_id:
        funcionarios = funcionarios.filter(delegacion_id=delegacion_id)
    if estado_filtro:
        funcionarios = funcionarios.filter(estado=estado_filtro)

    return render(request, 'crud/funcionarios_list.html', {
        'funcionarios': funcionarios,
        'delegaciones': Delegacion.objects.filter(activa=True).order_by('nombre'),
        'estados_cuenta': Funcionario.ESTADOS_CUENTA,
        'q': q,
        'delegacion_filtro': delegacion_id,
        'estado_filtro': estado_filtro,
    })


@roles_requeridos('ADMIN')
def funcionario_editar_view(request, pk):
    func_obj = get_object_or_404(Funcionario.objects.select_related('user'), pk=pk)
    func_autor = getattr(request.user, 'funcionario', None)

    if func_obj.user.is_superuser and not request.user.is_superuser:
        messages.error(request, "Solo el desarrollador puede modificar la cuenta de superusuario.")
        return redirect('funcionarios_list')

    if request.method == 'POST':
        form = FuncionarioUpdateForm(request.POST, instance=func_obj)
        if form.is_valid():
            funcionario = form.save()
            roles_seleccionados = form.cleaned_data['roles']
            funcionario.roles.set(roles_seleccionados)

            # Sincronizar datos del User sin otorgar is_staff a empleados
            user = funcionario.user
            user.first_name = funcionario.nombres
            user.last_name = funcionario.apellidos
            user.email = funcionario.correo
            user.is_active = (funcionario.estado != 'INACTIVO')
            if not user.is_superuser:
                user.is_staff = False
            user.save()

            BitacoraAuditoria.objects.create(
                usuario=func_autor,
                modulo='Seguridad / Usuarios',
                accion='Edición de Funcionario',
                detalle=f"Se actualizaron datos/roles de {funcionario.nombre_completo} ({funcionario.rut}). Estado: {funcionario.get_estado_display()}."
            )
            messages.success(request, f"Funcionario {funcionario.nombre_completo} actualizado correctamente.")
            return redirect('funcionarios_list')
    else:
        form = FuncionarioUpdateForm(instance=func_obj)

    return render(request, 'crud/form_base.html', {
        'form': form,
        'titulo': f"Editar Funcionario · {func_obj.nombre_completo}",
        'url_cancelar': 'funcionarios_list',
    })


# ==============================================================================
# MÓDULO 1: ASIGNACIÓN Y EDICIÓN DE METAS A FUNCIONARIOS (ADMIN Y DELEGADO)
# ==============================================================================
@roles_requeridos('ADMIN', 'DELEGADO')
def asignacion_metas_view(request):
    trimestres = Trimestre.objects.all().order_by('-anio', '-numero')
    trimestre_activo = trimestres.first()
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()
    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)

    funcionarios_scope = Funcionario.objects.select_related('cargo', 'delegacion').all()
    if not es_admin and func_actual:
        funcionarios_scope = funcionarios_scope.filter(delegacion=func_actual.delegacion)

    if request.method == 'POST':
        form = AsignacionMetaForm(request.POST)
        form.fields['funcionario'].queryset = funcionarios_scope
        if form.is_valid():
            asig = form.save()
            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Metas e Indicadores',
                accion='Asignación de Meta',
                detalle=f"Meta {asig.meta.codigo} asignada a {asig.funcionario.nombre_completo} (Obj: {asig.cantidad_objetivo}, Pond: {asig.ponderacion}%)."
            )
            messages.success(
                request,
                f"Meta '{asig.meta.nombre}' asignada a {asig.funcionario.nombre_completo} ({asig.ponderacion}%)."
            )
            return redirect('asignacion_metas')
        else:
            messages.error(request, "No se pudo asignar la meta. Revise las validaciones del formulario.")
    else:
        form = AsignacionMetaForm(initial={'trimestre': trimestre_activo, 'activa': True})
        form.fields['funcionario'].queryset = funcionarios_scope

    resumen_funcionarios = []
    for f in funcionarios_scope:
        metas_f = AsignacionMeta.objects.filter(
            funcionario=f, trimestre=trimestre_activo
        ).select_related('meta').order_by('-activa', 'meta__codigo')
        total_pond = metas_f.filter(activa=True).aggregate(total=Sum('ponderacion'))['total'] or 0
        resumen_funcionarios.append({
            'funcionario': f,
            'metas': metas_f,
            'total_ponderacion': round(float(total_pond), 1),
            'disponible': round(100.0 - float(total_pond), 1),
        })

    return render(request, 'asignacion_metas.html', {
        'form': form,
        'resumen_funcionarios': resumen_funcionarios,
        'trimestre_activo': trimestre_activo,
    })


@roles_requeridos('ADMIN', 'DELEGADO')
def asignacion_meta_editar_view(request, pk):
    asig = get_object_or_404(AsignacionMeta.objects.select_related('funcionario', 'meta', 'trimestre'), pk=pk)
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()
    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)

    if not es_admin and func_actual and asig.funcionario.delegacion != func_actual.delegacion:
        messages.error(request, "No tiene permisos para editar metas de otra delegación.")
        return redirect('asignacion_metas')

    funcionarios_scope = Funcionario.objects.select_related('cargo').all()
    if not es_admin and func_actual:
        funcionarios_scope = funcionarios_scope.filter(delegacion=func_actual.delegacion)

    if request.method == 'POST':
        form = AsignacionMetaForm(request.POST, instance=asig)
        form.fields['funcionario'].queryset = funcionarios_scope
        if form.is_valid():
            asig_editada = form.save()
            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Metas e Indicadores',
                accion='Edición de Meta Asignada',
                detalle=f"Meta {asig_editada.meta.codigo} de {asig_editada.funcionario.nombre_completo} actualizada (Obj: {asig_editada.cantidad_objetivo}, Pond: {asig_editada.ponderacion}%, Activa: {asig_editada.activa})."
            )
            messages.success(request, f"Meta {asig_editada.meta.codigo} actualizada correctamente.")
            return redirect('asignacion_metas')
        else:
            messages.error(request, "No se pudo actualizar la meta. Revise las validaciones.")
    else:
        form = AsignacionMetaForm(instance=asig)
        form.fields['funcionario'].queryset = funcionarios_scope

    return render(request, 'crud/form_base.html', {
        'form': form,
        'titulo': f"Editar Meta Asignada · {asig.meta.codigo} ({asig.funcionario.nombre_completo})",
        'url_cancelar': 'asignacion_metas',
    })


@roles_requeridos('ADMIN', 'DELEGADO')
def asignacion_meta_toggle_view(request, pk):
    if request.method == 'POST':
        asig = get_object_or_404(AsignacionMeta.objects.select_related('funcionario', 'meta', 'trimestre'), pk=pk)
        func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()
        es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)

        if not es_admin and func_actual and asig.funcionario.delegacion != func_actual.delegacion:
            messages.error(request, "No tiene permisos para modificar metas de otra delegación.")
            return redirect('asignacion_metas')

        asig.activa = not asig.activa
        try:
            asig.full_clean()
            asig.save()
            estado_txt = "activada" if asig.activa else "desactivada"
            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Metas e Indicadores',
                accion=f"Meta {estado_txt.capitalize()}",
                detalle=f"Meta {asig.meta.codigo} de {asig.funcionario.nombre_completo} fue {estado_txt}."
            )
            messages.success(request, f"Meta {asig.meta.codigo} de {asig.funcionario.nombre_completo} {estado_txt} correctamente.")
        except ValidationError as e:
            texto_error = "; ".join(e.messages)
            messages.error(request, f"No se pudo cambiar el estado de la meta: {texto_error}")

    return redirect('asignacion_metas')


# ==============================================================================
# MÓDULO NUEVO: SEGUIMIENTO DE SOLICITUDES (FLUJO DE 5 ETAPAS)
# ==============================================================================
@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO', 'VERIFICADOR')
def seguimiento_list_view(request):
    func_actual = getattr(request.user, 'funcionario', None)
    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)
    es_delegado = bool(func_actual and func_actual.es_delegado and not es_admin)
    es_verificador = bool(func_actual and func_actual.es_verificador and not es_admin and not es_delegado)
    es_solo_funcionario = bool(func_actual and func_actual.es_solo_funcionario)
    puede_filtrar_delegacion = bool(es_admin or es_verificador)

    q = request.GET.get('q', '').strip()
    etapa_filtro = request.GET.get('etapa', '').strip()
    tipo_sol_filtro = request.GET.get('tipo_solicitante', '').strip()
    delegacion_filtro = request.GET.get('delegacion', '').strip()

    qs_base = Actividad.objects.select_related(
        'funcionario_autor', 'funcionario_autor__delegacion',
        'responsable_tubo', 'territorio', 'territorio__delegacion',
        'meta_asignada__meta', 'vecino_solicitante', 'junta_solicitante'
    ).prefetch_related('evidencias').order_by('-id')

    if es_solo_funcionario and func_actual:
        qs_base = qs_base.filter(Q(funcionario_autor=func_actual) | Q(responsable_tubo=func_actual))
    elif es_delegado and func_actual:
        qs_base = qs_base.filter(
            Q(territorio__delegacion=func_actual.delegacion) |
            Q(funcionario_autor__delegacion=func_actual.delegacion) |
            Q(responsable_tubo__delegacion=func_actual.delegacion)
        )

    if puede_filtrar_delegacion and delegacion_filtro:
        qs_base = qs_base.filter(
            Q(territorio__delegacion_id=delegacion_filtro) |
            Q(funcionario_autor__delegacion_id=delegacion_filtro)
        )

    resumen_etapas = {
        'etapa_1': qs_base.filter(etapa_seguimiento=1).count(),
        'etapa_2': qs_base.filter(etapa_seguimiento=2).count(),
        'etapa_3': qs_base.filter(etapa_seguimiento=3).count(),
        'etapa_4': qs_base.filter(etapa_seguimiento=4).count(),
        'etapa_5': qs_base.filter(etapa_seguimiento=5).count(),
    }

    actividades = qs_base
    if etapa_filtro.isdigit():
        actividades = actividades.filter(etapa_seguimiento=int(etapa_filtro))
    if tipo_sol_filtro:
        actividades = actividades.filter(tipo_solicitante=tipo_sol_filtro)
    if q:
        actividades = actividades.filter(
            Q(codigo__icontains=q) |
            Q(tipo_actividad__icontains=q) |
            Q(descripcion__icontains=q) |
            Q(solicitante_nombre__icontains=q) |
            Q(solicitante_rut__icontains=q) |
            Q(junta_solicitante__nombre__icontains=q) |
            Q(entidad_reparacion__icontains=q) |
            Q(territorio__nombre__icontains=q)
        )

    return render(request, 'seguimiento_list.html', {
        'actividades': actividades,
        'resumen_etapas': resumen_etapas,
        'etapas_choices': Actividad.ETAPAS_SEGUIMIENTO,
        'tipos_solicitante': Actividad.TIPOS_SOLICITANTE,
        'delegaciones': Delegacion.objects.filter(activa=True).order_by('nombre'),
        'puede_filtrar_delegacion': puede_filtrar_delegacion,
        'q': q,
        'etapa_filtro': etapa_filtro,
        'tipo_sol_filtro': tipo_sol_filtro,
        'delegacion_filtro': delegacion_filtro,
    })


@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO', 'VERIFICADOR')
def seguimiento_detalle_view(request, pk):
    act = get_object_or_404(
        Actividad.objects.select_related(
            'funcionario_autor', 'funcionario_autor__delegacion',
            'responsable_tubo', 'territorio', 'territorio__delegacion',
            'meta_asignada', 'meta_asignada__meta', 'meta_asignada__trimestre',
            'vecino_solicitante', 'junta_solicitante', 'verificado_por'
        ).prefetch_related('evidencias', 'historial_tubo__autor'),
        pk=pk
    )

    func_actual = getattr(request.user, 'funcionario', None)
    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)
    es_delegado = bool(func_actual and func_actual.es_delegado and not es_admin)
    es_verificador = bool(func_actual and func_actual.es_verificador)
    es_solo_funcionario = bool(func_actual and func_actual.es_solo_funcionario)

    if es_solo_funcionario and func_actual and act.funcionario_autor != func_actual and act.responsable_tubo != func_actual:
        messages.error(request, "No tiene permisos para ver el seguimiento de esta solicitud.")
        return redirect('seguimiento_list')
    if es_delegado and func_actual:
        delg_id = func_actual.delegacion_id
        if act.territorio.delegacion_id != delg_id and act.funcionario_autor.delegacion_id != delg_id and act.responsable_tubo.delegacion_id != delg_id:
            messages.error(request, "No tiene permisos para ver solicitudes de otra delegación.")
            return redirect('seguimiento_list')

    puede_operar_etapas = bool(
        not act.bloqueada_edicion and (
            es_admin or es_delegado or (func_actual and (act.funcionario_autor == func_actual or act.responsable_tubo == func_actual))
        )
    )
    puede_finalizar = bool(es_admin or es_verificador)

    pasos = [
        {
            'numero': 1,
            'etiqueta': 'Entrada',
            'titulo': 'Solicitud (Inicio)',
            'detalle': act.tipo_actividad,
            'fecha': act.fecha_actividad,
            'completado': act.etapa_seguimiento >= 1,
            'actual': act.etapa_seguimiento == 1,
        },
        {
            'numero': 2,
            'etiqueta': 'Evidencia Problema',
            'titulo': 'Verificar Terreno y Subir Evidencia',
            'detalle': act.obs_etapa_2 or ('Evidencia del problema cargada' if act.evidencias_problema.exists() else 'Pendiente visita y foto inicial'),
            'fecha': act.fecha_etapa_2,
            'completado': act.etapa_seguimiento >= 2,
            'actual': act.etapa_seguimiento == 2,
        },
        {
            'numero': 3,
            'etiqueta': 'Proceso',
            'titulo': 'Asignar Reparación / Gestión',
            'detalle': act.entidad_reparacion or 'Pendiente derivación a empresa o unidad',
            'fecha': act.fecha_etapa_3,
            'completado': act.etapa_seguimiento >= 3,
            'actual': act.etapa_seguimiento == 3,
        },
        {
            'numero': 4,
            'etiqueta': 'Evidencia Terminada',
            'titulo': 'Verificar Terreno Terminado',
            'detalle': act.obs_etapa_4 or ('Evidencia de término cargada' if act.evidencias_terminadas.exists() else 'Pendiente verificación de término'),
            'fecha': act.fecha_etapa_4,
            'completado': act.etapa_seguimiento >= 4,
            'actual': act.etapa_seguimiento == 4,
        },
        {
            'numero': 5,
            'etiqueta': 'Salida',
            'titulo': 'Finalizar / Cierre',
            'detalle': act.obs_etapa_5 or act.get_estado_verificacion_display(),
            'fecha': act.fecha_etapa_5 or (act.fecha_verificacion.date() if act.fecha_verificacion else None),
            'completado': act.etapa_seguimiento >= 5,
            'actual': act.etapa_seguimiento == 5,
        },
    ]

    meta_asig = act.meta_asignada
    meta_tengo_pct = meta_asig.porcentaje_cumplimiento_real if meta_asig else 0.0
    meta_falta_pct = meta_asig.porcentaje_faltante if meta_asig else 100.0

    return render(request, 'seguimiento_detalle.html', {
        'actividad': act,
        'pasos': pasos,
        'evidencias_problema': act.evidencias.filter(etapa='PROBLEMA').order_by('-fecha_carga'),
        'evidencias_terminadas': act.evidencias.filter(etapa='TERMINADO').order_by('-fecha_carga'),
        'evidencias_generales': act.evidencias.filter(etapa='GENERAL').order_by('-fecha_carga'),
        'puede_operar_etapas': puede_operar_etapas,
        'puede_finalizar': puede_finalizar,
        'meta_tengo_pct': meta_tengo_pct,
        'meta_falta_pct': meta_falta_pct,
        'hoy_iso': timezone.localdate().isoformat(),
    })


@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO', 'VERIFICADOR')
def seguimiento_avanzar_view(request, pk):
    if request.method != 'POST':
        return redirect('seguimiento_detalle', pk=pk)

    act = get_object_or_404(Actividad.objects.select_related('funcionario_autor', 'responsable_tubo', 'territorio'), pk=pk)
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()
    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)
    es_delegado = bool(func_actual and func_actual.es_delegado)
    es_verificador = bool(func_actual and func_actual.es_verificador)

    try:
        etapa_objetivo = int(request.POST.get('etapa_objetivo', '0'))
    except ValueError:
        messages.error(request, "Etapa de seguimiento inválida.")
        return redirect('seguimiento_detalle', pk=pk)

    fecha_raw = request.POST.get('fecha_etapa', '').strip()
    fecha_etapa = parse_date(fecha_raw) if fecha_raw else timezone.localdate()
    if not fecha_etapa:
        fecha_etapa = timezone.localdate()

    observacion = request.POST.get('observacion', '').strip()
    archivo = request.FILES.get('archivo_evidencia')

    if archivo:
        ext = os.path.splitext(archivo.name)[1].lower()
        permitidos = ['.jpg', '.jpeg', '.png', '.pdf', '.doc', '.docx', '.xls', '.xlsx']
        if ext not in permitidos:
            messages.error(request, "Formato de evidencia no permitido. Use JPG, PNG, PDF, Word o Excel.")
            return redirect('seguimiento_detalle', pk=pk)
        if archivo.size > 10 * 1024 * 1024:
            messages.error(request, "El archivo supera el límite máximo de 10 MB.")
            return redirect('seguimiento_detalle', pk=pk)

    # Etapas operativas 2, 3 y 4
    if etapa_objetivo in (2, 3, 4):
        if act.bloqueada_edicion:
            messages.error(request, f"La solicitud {act.codigo} ya fue cerrada/aprobada y no permite cambios operativos.")
            return redirect('seguimiento_detalle', pk=pk)

        autorizado_operar = es_admin or es_delegado or (func_actual in (act.funcionario_autor, act.responsable_tubo))
        if not autorizado_operar:
            messages.error(request, "No tiene permisos para actualizar las etapas operativas de esta solicitud.")
            return redirect('seguimiento_detalle', pk=pk)

        if etapa_objetivo == 2:
            if not archivo and not act.evidencias.filter(etapa='PROBLEMA').exists():
                messages.error(request, "Para registrar la Etapa 2 debe adjuntar la evidencia fotográfica o documento del problema.")
                return redirect('seguimiento_detalle', pk=pk)

            if archivo:
                Evidencia.objects.create(
                    actividad=act,
                    archivo=archivo,
                    etapa='PROBLEMA',
                    tipo_archivo='Evidencia Problema (Terreno)',
                    autor=func_actual,
                    observacion=observacion or 'Verificación del problema en terreno'
                )
            act.fecha_etapa_2 = fecha_etapa
            act.obs_etapa_2 = observacion or act.obs_etapa_2 or 'Problema verificado en terreno'
            act.etapa_seguimiento = max(act.etapa_seguimiento, 2)
            act.save()

            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Seguimiento',
                accion='Etapa 2 · Evidencia Problema',
                detalle=f"Solicitud {act.codigo}: verificada en terreno el {fecha_etapa.strftime('%d/%m/%Y')}. {act.obs_etapa_2}"
            )
            messages.success(request, f"Etapa 2 (Evidencia del Problema) registrada para {act.codigo}.")

        elif etapa_objetivo == 3:
            entidad = request.POST.get('entidad_reparacion', '').strip()
            if not entidad:
                messages.error(request, "Debe indicar la empresa, unidad o área asignada para la reparación/gestión.")
                return redirect('seguimiento_detalle', pk=pk)

            estado_tubo_ant = act.estado_tubo
            act.fecha_etapa_3 = fecha_etapa
            act.entidad_reparacion = entidad
            act.obs_etapa_3 = observacion or f"Asignado a {entidad}"
            if not act.area_apoyo:
                act.area_apoyo = entidad[:120]
            act.etapa_seguimiento = max(act.etapa_seguimiento, 3)
            if act.ingresa_al_tubo and act.estado_tubo == 'PENDIENTE':
                act.estado_tubo = 'EN_PROCESO'
            act.save()

            if act.ingresa_al_tubo and estado_tubo_ant != act.estado_tubo:
                HistorialTubo.objects.create(
                    actividad=act,
                    estado_anterior=estado_tubo_ant,
                    estado_nuevo=act.estado_tubo,
                    responsable_anterior=act.responsable_tubo,
                    responsable_nuevo=act.responsable_tubo,
                    autor=func_actual,
                    motivo_observacion=f"Seguimiento Etapa 3 · Derivado a {entidad}. {observacion}".strip()
                )

            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Seguimiento',
                accion='Etapa 3 · Proceso / Derivación',
                detalle=f"Solicitud {act.codigo} asignada a {entidad} el {fecha_etapa.strftime('%d/%m/%Y')}."
            )
            messages.success(request, f"Etapa 3 (Proceso) registrada: asignada a {entidad}.")

        elif etapa_objetivo == 4:
            if not archivo and not act.evidencias.filter(etapa='TERMINADO').exists():
                messages.error(request, "Para registrar la Etapa 4 debe adjuntar la evidencia del trabajo terminado.")
                return redirect('seguimiento_detalle', pk=pk)

            if archivo:
                Evidencia.objects.create(
                    actividad=act,
                    archivo=archivo,
                    etapa='TERMINADO',
                    tipo_archivo='Evidencia Terminada (Terreno)',
                    autor=func_actual,
                    observacion=observacion or 'Verificación de trabajo terminado en terreno'
                )
            estado_tubo_ant = act.estado_tubo
            act.fecha_etapa_4 = fecha_etapa
            act.obs_etapa_4 = observacion or act.obs_etapa_4 or 'Trabajo verificado como terminado en terreno'
            act.etapa_seguimiento = max(act.etapa_seguimiento, 4)
            if act.estado_verificacion in ['SOLICITUD_ANTECEDENTES', 'RECHAZADA']:
                act.estado_verificacion = 'PENDIENTE'
            if act.ingresa_al_tubo and act.estado_tubo in ['PENDIENTE', 'EN_PROCESO', 'VENCIDO']:
                act.estado_tubo = 'REALIZADO'
            act.save()

            if act.ingresa_al_tubo and estado_tubo_ant != act.estado_tubo:
                HistorialTubo.objects.create(
                    actividad=act,
                    estado_anterior=estado_tubo_ant,
                    estado_nuevo=act.estado_tubo,
                    responsable_anterior=act.responsable_tubo,
                    responsable_nuevo=act.responsable_tubo,
                    autor=func_actual,
                    motivo_observacion=f"Seguimiento Etapa 4 · Evidencia de término cargada. {observacion}".strip()
                )

            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Seguimiento',
                accion='Etapa 4 · Evidencia Terminada',
                detalle=f"Solicitud {act.codigo}: evidencia terminada registrada el {fecha_etapa.strftime('%d/%m/%Y')}. Lista para cierre."
            )
            messages.success(request, f"Etapa 4 (Evidencia Terminada) registrada. La solicitud {act.codigo} quedó lista para cierre y validación final.")

    # Etapa 5: Salida / Finalizar y abonar a la meta (Solo Verificador o Admin)
    elif etapa_objetivo == 5:
        if not (es_admin or es_verificador):
            messages.error(request, "Solo un Verificador o Administrador puede ejecutar la Etapa 5 (Cierre definitivo y ponderación en meta).")
            return redirect('seguimiento_detalle', pk=pk)

        decision = request.POST.get('decision', 'APROBADA_PONDERA')
        if decision not in ['APROBADA_PONDERA', 'APROBADA_NO_PONDERA']:
            decision = 'APROBADA_PONDERA'

        estado_tubo_ant = act.estado_tubo
        act.etapa_seguimiento = 5
        act.fecha_etapa_5 = fecha_etapa
        act.obs_etapa_5 = observacion or 'Solicitud verificada y finalizada correctamente'
        act.estado_verificacion = decision
        act.observacion_verificador = act.obs_etapa_5
        act.verificado_por = func_actual
        act.fecha_verificacion = timezone.now()
        act.estado_tubo = 'CERRADO'
        act.fecha_cierre = fecha_etapa
        act.save()

        if act.ingresa_al_tubo:
            HistorialTubo.objects.create(
                actividad=act,
                estado_anterior=estado_tubo_ant,
                estado_nuevo='CERRADO',
                responsable_anterior=act.responsable_tubo,
                responsable_nuevo=act.responsable_tubo,
                autor=func_actual,
                motivo_observacion=f"Cierre definitivo Etapa 5 ({act.get_estado_verificacion_display()}). {act.obs_etapa_5}"
            )

        BitacoraAuditoria.objects.create(
            usuario=func_actual,
            modulo='Seguimiento',
            accion='Etapa 5 · Cierre y Salida',
            detalle=f"Solicitud {act.codigo} finalizada ({act.get_estado_verificacion_display()}) el {fecha_etapa.strftime('%d/%m/%Y')}."
        )
        messages.success(
            request,
            f"Etapa 5 completada: Solicitud {act.codigo} cerrada como '{act.get_estado_verificacion_display()}' y contabilizada en la meta."
        )
    else:
        messages.error(request, "Etapa de seguimiento no reconocida.")

    return redirect('seguimiento_detalle', pk=pk)


# ==============================================================================
# MÓDULO 2: FLUJO DE COMPROMISOS (TUBO DE GESTIÓN CON REASIGNACIÓN Y RBAC)
# ==============================================================================
@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO', 'VERIFICADOR')
def tubo_compromisos_view(request):
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()
    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)
    es_delegado = bool(func_actual and func_actual.es_delegado)
    es_solo_verificador = bool(func_actual and func_actual.es_verificador and not (es_admin or es_delegado or func_actual.es_funcionario_rol))

    if request.method == 'POST':
        if es_solo_verificador:
            messages.error(request, "El rol Verificador tiene acceso de solo lectura en el Tubo de Compromisos.")
            return redirect('tubo_compromisos')

        form = CompromisoTuboForm(request.POST)
        if form.is_valid():
            comp = form.save(commit=False)
            comp.funcionario_autor = func_actual
            comp.ingresa_al_tubo = True
            comp.estado_tubo = 'PENDIENTE'
            comp.save()

            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Tubo de Compromisos',
                accion='Ingreso al Tubo',
                detalle=f"Se ingresó compromiso {comp.codigo} al tubo."
            )
            messages.success(request, f"Compromiso {comp.codigo} ingresado al Tubo exitosamente.")
            return redirect('tubo_compromisos')
        else:
            messages.error(request, "Error al registrar el compromiso. Revise los campos.")
    else:
        form = CompromisoTuboForm(initial={'responsable_tubo': func_actual})
        if func_actual and func_actual.es_solo_funcionario:
            form.fields['meta_asignada'].queryset = AsignacionMeta.objects.filter(funcionario=func_actual, activa=True)
        elif es_delegado and not es_admin and func_actual:
            form.fields['meta_asignada'].queryset = AsignacionMeta.objects.filter(
                funcionario__delegacion=func_actual.delegacion, activa=True
            )

    q = (request.GET.get('q') or request.GET.get('buscar') or '').strip()
    estado_filtro = request.GET.get('estado', '').strip()

    compromisos = Actividad.objects.filter(ingresa_al_tubo=True).select_related(
        'territorio', 'responsable_tubo', 'meta_asignada__meta', 'vecino_solicitante', 'junta_solicitante'
    ).order_by('-id')

    if not es_admin and not es_solo_verificador and func_actual:
        compromisos = compromisos.filter(
            Q(territorio__delegacion=func_actual.delegacion) |
            Q(responsable_tubo__delegacion=func_actual.delegacion) |
            Q(funcionario_autor__delegacion=func_actual.delegacion)
        )

    if q:
        q_limpio = q.replace('.', '').replace('-', '')
        compromisos = compromisos.filter(
            Q(codigo__icontains=q) |
            Q(solicitante_nombre__icontains=q) |
            Q(solicitante_rut__icontains=q) |
            Q(solicitante_rut__icontains=q_limpio) |
            Q(vecino_solicitante__nombres__icontains=q) |
            Q(vecino_solicitante__apellidos__icontains=q) |
            Q(vecino_solicitante__rut__icontains=q) |
            Q(junta_solicitante__nombre__icontains=q) |
            Q(descripcion__icontains=q) |
            Q(territorio__nombre__icontains=q) |
            Q(area_apoyo__icontains=q) |
            Q(responsable_tubo__nombres__icontains=q) |
            Q(responsable_tubo__apellidos__icontains=q)
        )

    if estado_filtro:
        compromisos = compromisos.filter(estado_tubo=estado_filtro)

    funcionarios_tubo = Funcionario.objects.filter(estado='ACTIVO').order_by('nombres')
    if not es_admin and func_actual:
        funcionarios_tubo = funcionarios_tubo.filter(delegacion=func_actual.delegacion)

    return render(request, 'tubo_compromisos.html', {
        'form': form,
        'compromisos': compromisos,
        'estados_tubo': Actividad.ESTADOS_TUBO,
        'funcionarios_tubo': funcionarios_tubo,
        'q': q,
        'estado_filtro': estado_filtro,
    })


@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO')
def cambiar_estado_compromiso(request, pk):
    if request.method == 'POST':
        comp = get_object_or_404(Actividad, pk=pk, ingresa_al_tubo=True)
        func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()
        es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)
        es_delegado = bool(func_actual and func_actual.es_delegado)

        if comp.estado_verificacion == 'APROBADA_PONDERA' and comp.estado_tubo == 'CERRADO':
            messages.error(request, f"El compromiso {comp.codigo} ya fue validado, ponderado y cerrado definitivamente.")
            return redirect('tubo_compromisos')

        if not es_admin and not es_delegado and comp.responsable_tubo != func_actual:
            messages.error(
                request,
                f"No puede modificar el compromiso {comp.codigo} porque está asignado a {comp.responsable_tubo.nombre_completo}."
            )
            return redirect('tubo_compromisos')

        nuevo_estado = request.POST.get('nuevo_estado') or comp.estado_tubo
        nuevo_resp_id = request.POST.get('nuevo_responsable')
        observacion = request.POST.get('observacion', '').strip() or 'Actualización en el Tubo de Gestión'

        estado_ant = comp.estado_tubo
        resp_ant = comp.responsable_tubo

        if nuevo_resp_id and (es_admin or es_delegado):
            nuevo_resp = Funcionario.objects.filter(id=nuevo_resp_id).first()
            if nuevo_resp:
                comp.responsable_tubo = nuevo_resp

        comp.estado_tubo = nuevo_estado
        if observacion:
            comp.avances_observaciones = observacion
        if nuevo_estado in ['REALIZADO', 'CERRADO']:
            comp.fecha_cierre = timezone.now().date()
        comp.save()

        HistorialTubo.objects.create(
            actividad=comp,
            estado_anterior=estado_ant,
            estado_nuevo=nuevo_estado,
            responsable_anterior=resp_ant,
            responsable_nuevo=comp.responsable_tubo,
            autor=func_actual,
            motivo_observacion=observacion
        )

        if resp_ant != comp.responsable_tubo:
            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Tubo de Compromisos',
                accion='Reasignación de Responsable',
                detalle=f"Compromiso {comp.codigo} reasignado de {resp_ant.nombre_completo} a {comp.responsable_tubo.nombre_completo}. Motivo: {observacion}"
            )

        messages.success(request, f"Compromiso {comp.codigo} actualizado (Estado: {comp.get_estado_tubo_display()} | Responsable: {comp.responsable_tubo.nombre_completo}).")
    return redirect('tubo_compromisos')


# ==============================================================================
# MÓDULO 3: FLUJO DE CARTAS (TUBO DE CARTAS)
# ==============================================================================
@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO')
def tubo_cartas_view(request):
    func_actual = getattr(request.user, 'funcionario', None)
    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)

    if request.method == 'POST':
        form = TuboCartaForm(request.POST)
        if form.is_valid():
            carta = form.save()
            messages.success(request, f"Carta {carta.codigo} (N° {carta.numero_carta}) registrada exitosamente.")
            return redirect('tubo_cartas')
    else:
        form = TuboCartaForm(initial={'delegacion': func_actual.delegacion if func_actual else None})

    estado_filtro = request.GET.get('estado', '')
    cartas = TuboCarta.objects.select_related('delegacion', 'responsable_seguimiento').order_by('-id')
    if not es_admin and func_actual:
        cartas = cartas.filter(delegacion=func_actual.delegacion)
    if estado_filtro:
        cartas = cartas.filter(estado=estado_filtro)

    return render(request, 'tubo_cartas.html', {
        'form': form,
        'cartas': cartas,
        'estados_carta': TuboCarta.ESTADOS_CARTA,
        'estado_filtro': estado_filtro,
    })


@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO')
def cambiar_estado_carta(request, pk):
    if request.method == 'POST':
        carta = get_object_or_404(TuboCarta, pk=pk)
        nuevo_estado = request.POST.get('nuevo_estado')
        pronunciamiento = request.POST.get('pronunciamiento', '').strip()
        func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()

        estado_ant = carta.estado
        carta.estado = nuevo_estado
        if pronunciamiento:
            carta.pronunciamiento = pronunciamiento
        if nuevo_estado in ['FINALIZADA', 'NO_APLICA']:
            carta.fecha_cierre = timezone.now().date()
        carta.save()

        HistorialTubo.objects.create(
            carta=carta,
            estado_anterior=estado_ant,
            estado_nuevo=nuevo_estado,
            autor=func_actual,
            motivo_observacion=pronunciamiento or f"Transición a estado {nuevo_estado}"
        )
        messages.success(request, f"Carta {carta.codigo} actualizada al estado '{carta.get_estado_display()}'.")
    return redirect('tubo_cartas')


# ==============================================================================
# MANTENEDORES (CRUD): VECINOS, JUNTAS, HITOS Y FUNCIONARIOS CON RBAC
# ==============================================================================
class VecinoListView(RolesRequeridosMixin, ListView):
    roles_permitidos = ['ADMIN', 'DELEGADO', 'FUNCIONARIO']
    model = Vecino
    template_name = 'crud/vecinos_list.html'
    context_object_name = 'vecinos'


class VecinoCreateView(RolesRequeridosMixin, SuccessMessageMixin, CreateView):
    roles_permitidos = ['ADMIN', 'DELEGADO', 'FUNCIONARIO']
    model = Vecino
    form_class = VecinoForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('vecinos_list')
    success_message = "Vecino registrado exitosamente."
    extra_context = {'titulo': 'Registrar Nuevo Vecino', 'url_cancelar': 'vecinos_list'}


class VecinoUpdateView(RolesRequeridosMixin, SuccessMessageMixin, UpdateView):
    roles_permitidos = ['ADMIN', 'DELEGADO', 'FUNCIONARIO']
    model = Vecino
    form_class = VecinoForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('vecinos_list')
    success_message = "Vecino actualizado exitosamente."
    extra_context = {'titulo': 'Editar Vecino', 'url_cancelar': 'vecinos_list'}


class JuntaListView(RolesRequeridosMixin, ListView):
    roles_permitidos = ['ADMIN', 'DELEGADO', 'FUNCIONARIO']
    model = JuntaVecinos
    template_name = 'crud/juntas_list.html'
    context_object_name = 'juntas'

    def get_queryset(self):
        qs = JuntaVecinos.objects.select_related('delegacion', 'territorio').order_by('nombre')
        q = self.request.GET.get('q', '').strip()
        delegacion_id = self.request.GET.get('delegacion', '').strip()
        estado = self.request.GET.get('estado', '').strip()

        if q:
            qs = qs.filter(
                Q(codigo__icontains=q) |
                Q(nombre__icontains=q) |
                Q(direccion__icontains=q) |
                Q(territorio__nombre__icontains=q)
            )
        if delegacion_id:
            qs = qs.filter(delegacion_id=delegacion_id)
        if estado == 'activas':
            qs = qs.filter(activa=True)
        elif estado == 'inactivas':
            qs = qs.filter(activa=False)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['delegaciones'] = Delegacion.objects.filter(activa=True).order_by('nombre')
        context['q'] = self.request.GET.get('q', '').strip()
        context['delegacion_filtro'] = self.request.GET.get('delegacion', '').strip()
        context['estado_filtro'] = self.request.GET.get('estado', '').strip()
        context['total_juntas'] = JuntaVecinos.objects.count()
        context['total_activas'] = JuntaVecinos.objects.filter(activa=True).count()
        return context


class JuntaCreateView(RolesRequeridosMixin, SuccessMessageMixin, CreateView):
    roles_permitidos = ['ADMIN', 'DELEGADO', 'FUNCIONARIO']
    model = JuntaVecinos
    form_class = JuntaVecinosForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('juntas_list')
    success_message = "Junta de Vecinos registrada exitosamente."
    extra_context = {'titulo': 'Registrar Junta de Vecinos', 'url_cancelar': 'juntas_list'}


class JuntaUpdateView(RolesRequeridosMixin, SuccessMessageMixin, UpdateView):
    roles_permitidos = ['ADMIN', 'DELEGADO', 'FUNCIONARIO']
    model = JuntaVecinos
    form_class = JuntaVecinosForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('juntas_list')
    success_message = "Junta de Vecinos actualizada exitosamente."
    extra_context = {'titulo': 'Editar Junta de Vecinos', 'url_cancelar': 'juntas_list'}


class HitoListView(RolesRequeridosMixin, ListView):
    roles_permitidos = ['ADMIN', 'DELEGADO', 'FUNCIONARIO']
    model = Hito
    template_name = 'crud/hitos_list.html'
    context_object_name = 'hitos'


class HitoCreateView(RolesRequeridosMixin, SuccessMessageMixin, CreateView):
    roles_permitidos = ['ADMIN', 'DELEGADO']
    model = Hito
    form_class = HitoForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('hitos_list')
    success_message = "Hito programado exitosamente."
    extra_context = {'titulo': 'Programar Nuevo Hito', 'url_cancelar': 'hitos_list'}


class HitoUpdateView(RolesRequeridosMixin, SuccessMessageMixin, UpdateView):
    roles_permitidos = ['ADMIN', 'DELEGADO']
    model = Hito
    form_class = HitoForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('hitos_list')
    success_message = "Hito actualizado exitosamente."
    extra_context = {'titulo': 'Editar Hito', 'url_cancelar': 'hitos_list'}


class FuncionarioCreateView(RolesRequeridosMixin, SuccessMessageMixin, CreateView):
    roles_permitidos = ['ADMIN']
    model = Funcionario
    form_class = FuncionarioCreateForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('funcionarios_list')
    extra_context = {'titulo': 'Registrar Nuevo Funcionario', 'url_cancelar': 'funcionarios_list'}

    def form_valid(self, form):
        caracteres = string.ascii_letters + string.digits
        clave_temporal = ''.join(random.choices(caracteres, k=8))

        # Ningún empleado recibe is_staff=True; el panel técnico queda exclusivo para el desarrollador
        user = User.objects.create_user(
            username=form.cleaned_data['username'],
            email=form.cleaned_data['correo'],
            password=clave_temporal,
            first_name=form.cleaned_data['nombres'],
            last_name=form.cleaned_data['apellidos'],
            is_staff=False,
            is_superuser=False,
        )

        roles_seleccionados = form.cleaned_data['roles']

        funcionario = form.save(commit=False)
        funcionario.user = user
        funcionario.estado = 'PENDIENTE'
        funcionario.debe_cambiar_clave = True
        funcionario.save()
        funcionario.roles.set(roles_seleccionados)

        asunto = "Activación de Cuenta Institucional | SGR Municipalidad de La Serena"
        cuerpo = (
            f"Hola {funcionario.nombre_completo},\n\n"
            f"Se ha creado su cuenta en el Sistema de Gestión de Resultados (SGR) de la Ilustre Municipalidad de La Serena.\n\n"
            f"Usuario: {user.username}\n"
            f"Contraseña temporal de un solo uso: {clave_temporal}\n\n"
            f"En su primer ingreso el sistema le solicitará obligatoriamente definir su contraseña personal definitiva.\n\n"
            f"Coordinación de Delegaciones Municipales"
        )
        try:
            enviar_correo_institucional(funcionario.correo, asunto, cuerpo)
            messages.success(self.request, f"Funcionario registrado y credencial temporal enviada al correo {funcionario.correo}.")
        except Exception:
            messages.warning(self.request, f"Funcionario creado. Credencial temporal para {user.username}: {clave_temporal}")

        func_autor = getattr(self.request.user, 'funcionario', None)
        BitacoraAuditoria.objects.create(
            usuario=func_autor,
            modulo='Seguridad / Usuarios',
            accion='Creación de Funcionario',
            detalle=f"Se registró al funcionario {funcionario.nombre_completo} ({funcionario.rut}) en estado PENDIENTE."
        )

        return super().form_valid(form)


# ==============================================================================
# MÓDULO: REGISTRO Y EDICIÓN DE ACTIVIDADES, EVIDENCIAS Y BANDEJA DEL VERIFICADOR
# ==============================================================================
@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO')
def actividades_list_view(request):
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()
    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)
    es_delegado = bool(func_actual and func_actual.es_delegado)
    es_solo_funcionario = bool(func_actual and func_actual.es_solo_funcionario)

    if request.method == 'POST':
        form = ActividadRegistroForm(request.POST, request.FILES)
        if es_solo_funcionario:
            form.fields['meta_asignada'].queryset = AsignacionMeta.objects.filter(funcionario=func_actual, activa=True)
        elif es_delegado and not es_admin:
            form.fields['meta_asignada'].queryset = AsignacionMeta.objects.filter(
                funcionario__delegacion=func_actual.delegacion, activa=True
            )

        if form.is_valid():
            act = form.save(commit=False)
            act.funcionario_autor = func_actual
            act.estado_verificacion = 'PENDIENTE'
            if act.tipo_solicitante == 'JUNTA' and act.junta_solicitante:
                act.vecino_solicitante = None
                if not act.solicitante_nombre:
                    act.solicitante_nombre = act.junta_solicitante.nombre
            if not act.responsable_tubo_id:
                act.responsable_tubo = func_actual
            act.save()

            archivo = form.cleaned_data.get('archivo_evidencia')
            if archivo:
                obs_ev = form.cleaned_data.get('observacion_evidencia') or 'Evidencia inicial del problema'
                Evidencia.objects.create(
                    actividad=act,
                    archivo=archivo,
                    etapa='PROBLEMA',
                    tipo_archivo='Evidencia Problema (Inicial)',
                    autor=func_actual,
                    observacion=obs_ev
                )
                act.etapa_seguimiento = 2
                act.fecha_etapa_2 = timezone.localdate()
                act.obs_etapa_2 = obs_ev
                act.save()

            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Actividades',
                accion='Registro de Actividad',
                detalle=f"Se registró la actividad {act.codigo} asociada a la meta {act.meta_asignada.meta.codigo}"
            )
            messages.success(request, f"Actividad {act.codigo} registrada correctamente. Puede continuar su avance en Seguimiento.")
            return redirect('actividades_list')
        else:
            messages.error(request, "Error al registrar la actividad. Verifique los campos y el archivo adjunto.")
    else:
        form = ActividadRegistroForm(initial={'responsable_tubo': func_actual})
        if es_solo_funcionario:
            form.fields['meta_asignada'].queryset = AsignacionMeta.objects.filter(funcionario=func_actual, activa=True)
        elif es_delegado and not es_admin:
            form.fields['meta_asignada'].queryset = AsignacionMeta.objects.filter(
                funcionario__delegacion=func_actual.delegacion, activa=True
            )

    estado_filtro = request.GET.get('estado', '')
    q = request.GET.get('q', '').strip()
    actividades = Actividad.objects.select_related(
        'funcionario_autor', 'meta_asignada__meta', 'hito', 'territorio',
        'verificado_por', 'vecino_solicitante', 'junta_solicitante'
    ).prefetch_related('evidencias').order_by('-id')

    if es_solo_funcionario:
        actividades = actividades.filter(funcionario_autor=func_actual)
    elif es_delegado and not es_admin and func_actual:
        actividades = actividades.filter(funcionario_autor__delegacion=func_actual.delegacion)

    if estado_filtro:
        actividades = actividades.filter(estado_verificacion=estado_filtro)
    if q:
        actividades = actividades.filter(
            Q(codigo__icontains=q) |
            Q(tipo_actividad__icontains=q) |
            Q(descripcion__icontains=q) |
            Q(solicitante_nombre__icontains=q) |
            Q(solicitante_rut__icontains=q) |
            Q(junta_solicitante__nombre__icontains=q)
        )

    vecinos_qs = Vecino.objects.filter(activo=True).select_related('territorio').order_by('rut')
    vecinos_datos = [
        {
            'id': v.id,
            'rut': v.rut,
            'nombre': v.nombre_completo,
            'telefono': v.telefono or '',
            'direccion': v.direccion or '',
            'territorio_id': v.territorio_id or '',
        }
        for v in vecinos_qs
    ]

    juntas_qs = JuntaVecinos.objects.filter(activa=True).select_related('territorio').order_by('nombre')
    juntas_datos = [
        {
            'id': j.id,
            'codigo': j.codigo,
            'nombre': j.nombre,
            'direccion': j.direccion or '',
            'territorio_id': j.territorio_id or '',
        }
        for j in juntas_qs
    ]

    return render(request, 'actividades_list.html', {
        'form': form,
        'form_evidencia': SubirEvidenciaForm(),
        'actividades': actividades,
        'estados_verificacion': Actividad.ESTADOS_VERIFICACION,
        'estado_filtro': estado_filtro,
        'q': q,
        'vecinos_datos': vecinos_datos,
        'juntas_datos': juntas_datos,
        'territorios_modal': Territorio.objects.filter(activo=True).order_by('nombre'),
    })


@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO')
def actividad_editar_view(request, pk):
    act = get_object_or_404(Actividad.objects.select_related('funcionario_autor', 'meta_asignada'), pk=pk)
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()
    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)
    es_delegado = bool(func_actual and func_actual.es_delegado)
    es_solo_funcionario = bool(func_actual and func_actual.es_solo_funcionario)

    if act.bloqueada_edicion:
        messages.error(request, f"La actividad {act.codigo} ya fue aprobada y está bloqueada contra ediciones.")
        return redirect('actividades_list')

    if es_solo_funcionario and act.funcionario_autor != func_actual:
        messages.error(request, "No puede editar actividades registradas por otro funcionario.")
        return redirect('actividades_list')

    if es_delegado and not es_admin and func_actual and act.funcionario_autor.delegacion != func_actual.delegacion:
        messages.error(request, "No puede editar actividades de otra delegación.")
        return redirect('actividades_list')

    if request.method == 'POST':
        form = ActividadEditarForm(request.POST, instance=act)
        if es_solo_funcionario:
            form.fields['meta_asignada'].queryset = AsignacionMeta.objects.filter(
                Q(funcionario=func_actual, activa=True) | Q(pk=act.meta_asignada_id)
            )
        elif es_delegado and not es_admin and func_actual:
            form.fields['meta_asignada'].queryset = AsignacionMeta.objects.filter(
                Q(funcionario__delegacion=func_actual.delegacion, activa=True) | Q(pk=act.meta_asignada_id)
            )

        if form.is_valid():
            act_editada = form.save()
            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Actividades',
                accion='Edición de Actividad',
                detalle=f"Se editó la actividad {act_editada.codigo} ({act_editada.tipo_actividad})."
            )
            messages.success(request, f"Actividad {act_editada.codigo} actualizada correctamente.")
            return redirect('actividades_list')
    else:
        form = ActividadEditarForm(instance=act)
        if es_solo_funcionario:
            form.fields['meta_asignada'].queryset = AsignacionMeta.objects.filter(
                Q(funcionario=func_actual, activa=True) | Q(pk=act.meta_asignada_id)
            )
        elif es_delegado and not es_admin and func_actual:
            form.fields['meta_asignada'].queryset = AsignacionMeta.objects.filter(
                Q(funcionario__delegacion=func_actual.delegacion, activa=True) | Q(pk=act.meta_asignada_id)
            )

    return render(request, 'crud/form_base.html', {
        'form': form,
        'titulo': f"Editar Actividad · {act.codigo}",
        'url_cancelar': 'actividades_list',
    })


@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO')
def vecino_registro_rapido_view(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido.'})

    nombre_completo = request.POST.get('nombre_completo', '').strip()
    rut = request.POST.get('rut', '').strip()
    telefono = request.POST.get('telefono', '').strip()
    direccion = request.POST.get('direccion', '').strip()
    territorio_id = request.POST.get('territorio_id', '').strip()

    if not nombre_completo:
        return JsonResponse({'ok': False, 'error': 'Debe ingresar el nombre completo del vecino.'})
    if not rut:
        return JsonResponse({'ok': False, 'error': 'Debe ingresar el RUT del vecino.'})
    if not telefono:
        return JsonResponse({'ok': False, 'error': 'Debe ingresar el número de teléfono del vecino.'})
    if not direccion:
        return JsonResponse({'ok': False, 'error': 'Debe ingresar la dirección obligatoria del vecino.'})

    rut_norm = ''.join(c for c in rut.upper() if c.isalnum())
    if len(rut_norm) < 7:
        return JsonResponse({'ok': False, 'error': 'El RUT ingresado no parece válido.'})

    for rut_existente in Vecino.objects.values_list('rut', flat=True):
        if ''.join(c for c in (rut_existente or '').upper() if c.isalnum()) == rut_norm:
            return JsonResponse({'ok': False, 'error': f'Ya existe un vecino registrado con el RUT {rut_existente}.'})

    territorio = Territorio.objects.filter(id=territorio_id).first() if territorio_id else None
    if not territorio:
        func_actual = getattr(request.user, 'funcionario', None)
        if func_actual and func_actual.delegacion:
            territorio = Territorio.objects.filter(delegacion=func_actual.delegacion, activo=True).first()
        if not territorio:
            territorio = Territorio.objects.filter(activo=True).first()

    if not territorio:
        return JsonResponse({'ok': False, 'error': 'Debe seleccionar un territorio válido.'})

    partes = nombre_completo.split(None, 1)
    nombres = partes[0]
    apellidos = partes[1] if len(partes) > 1 else ''

    vecino = Vecino.objects.create(
        rut=rut,
        nombres=nombres,
        apellidos=apellidos,
        telefono=telefono,
        correo='',
        direccion=direccion,
        territorio=territorio,
        activo=True,
    )

    func_actual = getattr(request.user, 'funcionario', None)
    BitacoraAuditoria.objects.create(
        usuario=func_actual,
        modulo='Vecinos',
        accion='Registro Rápido de Vecino',
        detalle=f"Se registró al vecino {vecino.nombre_completo} (RUT: {vecino.rut}, Dir: {vecino.direccion}) desde el formulario de actividades."
    )

    return JsonResponse({
        'ok': True,
        'vecino': {
            'id': vecino.id,
            'rut': vecino.rut,
            'nombre': vecino.nombre_completo,
            'telefono': vecino.telefono or '',
            'direccion': vecino.direccion or '',
            'territorio_id': vecino.territorio_id or '',
        }
    })


@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO')
def adjuntar_evidencia_view(request, pk):
    act = get_object_or_404(Actividad, pk=pk)
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()
    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)

    if not es_admin and func_actual.es_solo_funcionario and act.funcionario_autor != func_actual:
        messages.error(request, "No puede adjuntar evidencias a actividades registradas por otro funcionario.")
        return redirect('actividades_list')

    if act.bloqueada_edicion:
        messages.error(request, f"La actividad {act.codigo} ya fue aprobada y se encuentra bloqueada contra modificaciones.")
        return redirect('actividades_list')

    if request.method == 'POST':
        form = SubirEvidenciaForm(request.POST, request.FILES)
        if form.is_valid():
            ev = form.save(commit=False)
            ev.actividad = act
            ev.autor = func_actual
            ev.save()

            if ev.etapa == 'PROBLEMA' and act.etapa_seguimiento < 2:
                act.etapa_seguimiento = 2
                act.fecha_etapa_2 = timezone.localdate()
                if ev.observacion:
                    act.obs_etapa_2 = ev.observacion
            elif ev.etapa == 'TERMINADO' and act.etapa_seguimiento < 4:
                act.etapa_seguimiento = 4
                act.fecha_etapa_4 = timezone.localdate()
                if ev.observacion:
                    act.obs_etapa_4 = ev.observacion

            if act.estado_verificacion in ['SOLICITUD_ANTECEDENTES', 'RECHAZADA']:
                act.estado_verificacion = 'PENDIENTE'
            act.save()

            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Evidencias',
                accion='Carga de Evidencia',
                detalle=f"Se adjuntó evidencia {ev.codigo} ({ev.get_etapa_display()}) a la actividad {act.codigo}"
            )
            messages.success(request, f"Evidencia {ev.codigo} adjuntada correctamente a la actividad {act.codigo}.")
        else:
            messages.error(request, "Archivo inválido. Verifique que sea imagen/PDF y pese menos de 10 MB.")
    return redirect('actividades_list')


@roles_requeridos('ADMIN', 'VERIFICADOR')
def bandeja_verificacion_view(request):
    estado_filtro = request.GET.get('estado', 'PENDIENTE')
    funcionario_filtro = request.GET.get('funcionario', '')

    actividades = Actividad.objects.select_related(
        'funcionario_autor', 'meta_asignada__meta', 'hito', 'territorio',
        'verificado_por', 'junta_solicitante'
    ).prefetch_related('evidencias').order_by('-fecha_registro')

    if estado_filtro and estado_filtro != 'TODOS':
        actividades = actividades.filter(estado_verificacion=estado_filtro)
    if funcionario_filtro:
        actividades = actividades.filter(funcionario_autor_id=funcionario_filtro)

    resumen = {
        'pendientes': Actividad.objects.filter(estado_verificacion='PENDIENTE').count(),
        'ponderan': Actividad.objects.filter(estado_verificacion='APROBADA_PONDERA').count(),
        'no_ponderan': Actividad.objects.filter(estado_verificacion='APROBADA_NO_PONDERA').count(),
        'antecedentes': Actividad.objects.filter(estado_verificacion='SOLICITUD_ANTECEDENTES').count(),
        'rechazadas': Actividad.objects.filter(estado_verificacion='RECHAZADA').count(),
    }

    return render(request, 'verificacion_bandeja.html', {
        'actividades': actividades,
        'estados_verificacion': Actividad.ESTADOS_VERIFICACION,
        'estado_filtro': estado_filtro,
        'funcionario_filtro': funcionario_filtro,
        'funcionarios': Funcionario.objects.all(),
        'resumen': resumen,
    })


@roles_requeridos('ADMIN', 'VERIFICADOR')
def dictaminar_actividad_view(request, pk):
    if request.method == 'POST':
        act = get_object_or_404(Actividad, pk=pk)
        func_verificador = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()

        if act.estado_verificacion == 'APROBADA_PONDERA' and act.estado_tubo == 'CERRADO':
            messages.warning(request, f"La actividad {act.codigo} ya fue validada, ponderada y cerrada anteriormente.")
            return redirect('bandeja_verificacion')

        decision = request.POST.get('decision')
        observacion = request.POST.get('observacion_verificador', '').strip()

        if decision in ['SOLICITUD_ANTECEDENTES', 'RECHAZADA'] and not observacion:
            messages.error(request, f"Debe escribir una observación indicando el motivo al rechazar o solicitar antecedentes en {act.codigo}.")
            return redirect('bandeja_verificacion')

        estado_anterior = act.get_estado_verificacion_display()
        estado_tubo_anterior = act.estado_tubo

        act.estado_verificacion = decision
        act.observacion_verificador = observacion
        act.verificado_por = func_verificador
        act.fecha_verificacion = timezone.now()

        cierre_msg = ""
        if decision == 'APROBADA_PONDERA':
            act.estado_tubo = 'CERRADO'
            act.fecha_cierre = timezone.localdate()
            act.etapa_seguimiento = 5
            act.fecha_etapa_5 = timezone.localdate()
            act.obs_etapa_5 = observacion or 'Aprobada y cerrada desde Bandeja de Verificación'
            cierre_msg = " Actividad cerrada automáticamente (Etapa 5 completada)."

        act.save()

        if decision == 'APROBADA_PONDERA' and act.ingresa_al_tubo:
            HistorialTubo.objects.create(
                actividad=act,
                estado_anterior=estado_tubo_anterior,
                estado_nuevo='CERRADO',
                responsable_anterior=act.responsable_tubo,
                responsable_nuevo=act.responsable_tubo,
                autor=func_verificador,
                motivo_observacion=f"Cierre automático al aprobar y ponderar actividad. {observacion}".strip()
            )

        BitacoraAuditoria.objects.create(
            usuario=func_verificador,
            modulo='Verificación',
            accion=f"Dictamen: {act.get_estado_verificacion_display()}",
            detalle=f"Actividad {act.codigo} pasó de '{estado_anterior}' a '{act.get_estado_verificacion_display()}'.{cierre_msg} Obs: {observacion or 'Sin observaciones'}"
        )
        messages.success(
            request,
            f"Dictamen registrado: Actividad {act.codigo} marcada como '{act.get_estado_verificacion_display()}'.{cierre_msg}"
        )
    return redirect('bandeja_verificacion')


# ==============================================================================
# SEGURIDAD: ACTIVACIÓN EN PRIMER LOGIN Y RECUPERACIÓN DE CONTRASEÑA
# ==============================================================================
@login_required(login_url='login')
def cambiar_clave_obligatorio_view(request):
    func = getattr(request.user, 'funcionario', None)

    if request.method == 'POST':
        nueva_clave = request.POST.get('nueva_clave', '').strip()
        confirmar_clave = request.POST.get('confirmar_clave', '').strip()

        if len(nueva_clave) < 8:
            messages.error(request, "La nueva contraseña debe tener al menos 8 caracteres.")
        elif nueva_clave != confirmar_clave:
            messages.error(request, "Las contraseñas ingresadas no coinciden.")
        elif nueva_clave == 'muni2026':
            messages.error(request, "No puede utilizar la contraseña genérica de demostración. Elija una personal.")
        else:
            user = request.user
            user.set_password(nueva_clave)
            user.save()
            update_session_auth_hash(request, user)

            if func:
                func.debe_cambiar_clave = False
                func.estado = 'ACTIVO'
                func.save()
                BitacoraAuditoria.objects.create(
                    usuario=func,
                    modulo='Seguridad',
                    accion='Activación de Cuenta / Cambio de Clave',
                    detalle='El funcionario estableció su contraseña definitiva y activó su cuenta.'
                )

            messages.success(request, "¡Cuenta activada con éxito! Su contraseña definitiva ha sido guardada.")
            return redirect('dashboard_inicio')

    return render(request, 'cambiar_clave_obligatorio.html', {'funcionario': func})


def recuperar_clave_view(request):
    if request.method == 'POST':
        identificador = request.POST.get('identificador', '').strip()
        func = Funcionario.objects.filter(
            Q(user__username__iexact=identificador) | Q(correo__iexact=identificador)
        ).select_related('user').first()

        request.session['reset_identificador'] = identificador
        request.session.pop('reset_autorizado_id', None)

        if func:
            codigo = f"{random.randint(100000, 999999)}"
            func.codigo_recuperacion = codigo
            func.codigo_expiracion = timezone.now() + timezone.timedelta(minutes=10)
            func.save()

            asunto = "Código de Recuperación de Contraseña | SGR Municipalidad de La Serena"
            mensaje = (
                f"Hola {func.nombre_completo},\n\n"
                f"Se ha solicitado restablecer su contraseña en el Sistema de Gestión de Resultados (SGR).\n\n"
                f"Su código de verificación de un solo uso es: {codigo}\n\n"
                f"Este código tiene una vigencia de 10 minutos. Si usted no realizó esta solicitud, ignore este mensaje.\n\n"
                f"Coordinación de Delegaciones\nIlustre Municipalidad de La Serena"
            )
            try:
                enviar_correo_institucional(func.correo, asunto, mensaje)
            except Exception as e:
                messages.error(request, f"Error SMTP: {e}")
                return render(request, 'recuperar_clave.html')

            BitacoraAuditoria.objects.create(
                usuario=func,
                modulo='Seguridad',
                accion='Envío Código Recuperación',
                detalle=f"Se envió código de verificación al correo {func.correo}."
            )

        messages.info(request, "Hemos enviado un código de 6 dígitos a su correo electrónico registrado.")
        return redirect('verificar_codigo_recuperacion')

    return render(request, 'recuperar_clave.html')


def verificar_codigo_view(request):
    identificador = request.session.get('reset_identificador')
    if not identificador:
        messages.warning(request, "Primero debe ingresar su correo institucional.")
        return redirect('recuperar_clave')

    if request.method == 'POST':
        codigo_ingresado = request.POST.get('codigo', '').strip()
        func = Funcionario.objects.filter(
            Q(user__username__iexact=identificador) | Q(correo__iexact=identificador)
        ).select_related('user').first()

        if (
            func
            and func.codigo_recuperacion
            and func.codigo_recuperacion == codigo_ingresado
            and func.codigo_expiracion
            and func.codigo_expiracion > timezone.now()
        ):
            func.codigo_recuperacion = None
            func.codigo_expiracion = None
            func.save()

            request.session['reset_autorizado_id'] = func.id
            messages.success(request, "Código verificado correctamente. Ahora puede ingresar su nueva contraseña.")
            return redirect('nueva_clave_recuperacion')
        else:
            messages.error(request, "Código incorrecto o expirado. Se ha rechazado el acceso al cambio de contraseña.")

    return render(request, 'verificar_codigo.html')


def nueva_clave_recuperacion_view(request):
    func_id = request.session.get('reset_autorizado_id')
    if not func_id:
        messages.error(request, "Acceso denegado. Debe validar el código enviado a su correo primero.")
        return redirect('recuperar_clave')

    func = get_object_or_404(Funcionario, id=func_id)

    if request.method == 'POST':
        nueva_clave = request.POST.get('nueva_clave', '').strip()
        confirmar_clave = request.POST.get('confirmar_clave', '').strip()

        if len(nueva_clave) < 8:
            messages.error(request, "La contraseña debe tener al menos 8 caracteres.")
        elif nueva_clave != confirmar_clave:
            messages.error(request, "Las contraseñas no coinciden.")
        else:
            func.user.set_password(nueva_clave)
            func.user.save()

            func.debe_cambiar_clave = False
            func.estado = 'ACTIVO'
            func.intentos_fallidos = 0
            func.bloqueado_hasta = None
            func.save()

            request.session.pop('reset_autorizado_id', None)
            request.session.pop('reset_identificador', None)

            try:
                enviar_correo_institucional(
                    func.correo,
                    "Confirmación de Cambio de Contraseña | SGR La Serena",
                    f"Hola {func.nombre_completo},\n\nSu contraseña del Sistema SGR ha sido actualizada exitosamente."
                )
            except Exception:
                pass

            BitacoraAuditoria.objects.create(
                usuario=func,
                modulo='Seguridad',
                accion='Contraseña Restablecida por Código',
                detalle='El usuario restableció su contraseña exitosamente mediante código de correo.'
            )

            messages.success(request, "¡Su contraseña ha sido actualizada con éxito! Ya puede iniciar sesión.")
            return redirect('login')

    return render(request, 'nueva_clave_recuperacion.html', {'funcionario': func})


# ==============================================================================
# GESTIONES SOCIALES (LAS 3 ETAPAS Y DÍAS DE DEMORA)
# ==============================================================================
@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO')
def gestiones_sociales_view(request):
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()
    es_admin = request.user.is_superuser or (func_actual and func_actual.es_admin)

    if request.method == 'POST' and 'crear_gestion' in request.POST:
        vecino_id = request.POST.get('vecino')
        requerimiento = request.POST.get('requerimiento', '').strip()

        vecino_obj = get_object_or_404(Vecino, id=vecino_id)

        nueva_gs = GestionSocial.objects.create(
            vecino=vecino_obj,
            territorio=vecino_obj.territorio,
            asistente_social=func_actual,
            requerimiento=requerimiento
        )

        BitacoraAuditoria.objects.create(
            usuario=func_actual,
            modulo='Gestiones Sociales',
            accion='Ingreso de Caso',
            detalle=f"Se ingresó el caso social {nueva_gs.codigo} para el vecino {vecino_obj.rut}."
        )
        messages.success(request, f"Gestión Social {nueva_gs.codigo} ingresada con éxito.")
        return redirect('gestiones_sociales')

    q = request.GET.get('q', '').strip()
    gestiones = GestionSocial.objects.select_related('vecino', 'territorio', 'asistente_social').order_by('-id')
    if not es_admin and func_actual:
        gestiones = gestiones.filter(
            Q(territorio__delegacion=func_actual.delegacion) | Q(asistente_social=func_actual)
        )

    if q:
        gestiones = gestiones.filter(
            Q(codigo__icontains=q) |
            Q(vecino__nombres__icontains=q) |
            Q(vecino__apellidos__icontains=q) |
            Q(vecino__rut__icontains=q) |
            Q(requerimiento__icontains=q)
        )

    return render(request, 'gestiones_sociales.html', {
        'gestiones': gestiones,
        'vecinos': Vecino.objects.filter(activo=True).order_by('nombres'),
        'q': q,
    })


@roles_requeridos('ADMIN', 'DELEGADO', 'FUNCIONARIO')
def actualizar_etapa_social(request, pk):
    if request.method == 'POST':
        gs = get_object_or_404(GestionSocial, pk=pk)
        func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()

        fecha_v = request.POST.get('fecha_visita')
        fecha_i = request.POST.get('fecha_informe')
        fecha_b = request.POST.get('fecha_beneficio')
        estado_rechazo = request.POST.get('rechazar')

        if estado_rechazo == 'SI':
            gs.estado = 'RECHAZADA'
            gs.observaciones = request.POST.get('observaciones', '')
        else:
            if gs.estado == 'RECHAZADA':
                gs.estado = 'INGRESADA'
            gs.fecha_visita = fecha_v if fecha_v else None
            gs.fecha_informe = fecha_i if fecha_i else None
            gs.fecha_beneficio = fecha_b if fecha_b else None
            gs.observaciones = request.POST.get('observaciones', '')

        gs.save()

        BitacoraAuditoria.objects.create(
            usuario=func_actual,
            modulo='Gestiones Sociales',
            accion='Actualización de Etapas',
            detalle=f"Caso {gs.codigo} actualizado a '{gs.get_estado_display()}'. Demora: {gs.dias_demora} días."
        )
        messages.success(request, f"Etapas del caso {gs.codigo} actualizadas correctamente. (Demora actual: {gs.dias_demora} días).")

    return redirect('gestiones_sociales')


# ==============================================================================
# REPORTES Y BITÁCORA (SOLO ADMIN, DELEGADO Y VERIFICADOR)
# ==============================================================================
@roles_requeridos('ADMIN', 'DELEGADO', 'VERIFICADOR')
def reportes_bitacora_view(request):
    func_actual = getattr(request.user, 'funcionario', None)
    es_admin_o_verif = request.user.is_superuser or (func_actual and (func_actual.es_admin or func_actual.es_verificador))

    modulo_filtro = request.GET.get('modulo', '').strip()
    q_bitacora = request.GET.get('q', '').strip()

    bitacora = BitacoraAuditoria.objects.select_related('usuario').order_by('-fecha_hora')
    if not es_admin_o_verif and func_actual:
        bitacora = bitacora.filter(usuario__delegacion=func_actual.delegacion)

    if modulo_filtro:
        bitacora = bitacora.filter(modulo__iexact=modulo_filtro)
    if q_bitacora:
        bitacora = bitacora.filter(
            Q(accion__icontains=q_bitacora) |
            Q(detalle__icontains=q_bitacora) |
            Q(usuario__nombres__icontains=q_bitacora) |
            Q(usuario__apellidos__icontains=q_bitacora)
        )

    historial_tubo = HistorialTubo.objects.select_related(
        'actividad', 'carta', 'autor', 'responsable_anterior', 'responsable_nuevo'
    ).order_by('-fecha')
    if not es_admin_o_verif and func_actual:
        historial_tubo = historial_tubo.filter(autor__delegacion=func_actual.delegacion)

    resumen_sistema = {
        'total_actividades': Actividad.objects.count(),
        'aprobadas': Actividad.objects.filter(estado_verificacion='APROBADA_PONDERA').count(),
        'compromisos_tubo': Actividad.objects.filter(ingresa_al_tubo=True).count(),
        'cartas': TuboCarta.objects.count(),
        'hitos': Hito.objects.count(),
        'eventos_auditoria': bitacora.count(),
    }

    modulos_disponibles = BitacoraAuditoria.objects.values_list('modulo', flat=True).distinct()

    return render(request, 'reportes_bitacora.html', {
        'bitacora': bitacora[:100],
        'historial_tubo': historial_tubo[:30],
        'resumen': resumen_sistema,
        'modulos_disponibles': modulos_disponibles,
        'modulo_filtro': modulo_filtro,
        'q': q_bitacora,
    })


@roles_requeridos('ADMIN', 'DELEGADO', 'VERIFICADOR')
def exportar_reporte_csv(request):
    tipo = request.GET.get('tipo', 'actividades')
    func_actual = getattr(request.user, 'funcionario', None)
    es_admin_o_verif = request.user.is_superuser or (func_actual and (func_actual.es_admin or func_actual.es_verificador))

    delegacion_nombre = func_actual.delegacion.nombre if func_actual and func_actual.delegacion else 'General La Serena'
    trimestre_activo = Trimestre.objects.order_by('-anio', '-numero').first()
    trimestre_str = f"{trimestre_activo.nombre} ({trimestre_activo.anio})" if trimestre_activo else '2026'
    fecha_gen = timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M:%S')

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="reporte_{tipo}_sgr.csv"'
    writer = csv.writer(response, delimiter=';')

    writer.writerow(['SISTEMA DE GESTION DE RESULTADOS (SGR) - ILUSTRE MUNICIPALIDAD DE LA SERENA'])
    writer.writerow(['Fecha y Hora de Generacion:', fecha_gen, 'Delegacion:', delegacion_nombre, 'Trimestre:', trimestre_str])
    writer.writerow([])

    if tipo == 'bitacora':
        writer.writerow(['Fecha y Hora', 'Usuario', 'Modulo', 'Accion', 'Detalle'])
        qs = BitacoraAuditoria.objects.select_related('usuario').order_by('-fecha_hora')
        if not es_admin_o_verif and func_actual:
            qs = qs.filter(usuario__delegacion=func_actual.delegacion)
        for b in qs:
            autor = b.usuario.nombre_completo if b.usuario else 'Sistema'
            writer.writerow([b.fecha_hora.strftime('%d/%m/%Y %H:%M'), autor, b.modulo, b.accion, b.detalle])
    elif tipo == 'sociales':
        writer.writerow(['Codigo', 'Fecha Ingreso', 'Vecino', 'RUT', 'Territorio', 'Requerimiento', 'Visita', 'Informe', 'Beneficio', 'Demora (Dias)', 'Estado'])
        qs = GestionSocial.objects.select_related('vecino', 'territorio').order_by('-id')
        if not es_admin_o_verif and func_actual:
            qs = qs.filter(territorio__delegacion=func_actual.delegacion)
        for gs in qs:
            writer.writerow([
                gs.codigo,
                gs.fecha_ingreso.strftime('%d/%m/%Y'),
                gs.vecino.nombre_completo,
                gs.vecino.rut,
                gs.territorio.nombre,
                gs.requerimiento,
                gs.fecha_visita.strftime('%d/%m/%Y') if gs.fecha_visita else '-',
                gs.fecha_informe.strftime('%d/%m/%Y') if gs.fecha_informe else '-',
                gs.fecha_beneficio.strftime('%d/%m/%Y') if gs.fecha_beneficio else '-',
                gs.dias_demora,
                gs.get_estado_display(),
            ])
    else:
        writer.writerow(['Codigo', 'Fecha', 'Tipo', 'Solicitante', 'RUT', 'Territorio', 'Responsable', 'Etapa Seguimiento', 'Estado Tubo', 'Verificacion'])
        qs = Actividad.objects.select_related('territorio', 'responsable_tubo').order_by('-id')
        if not es_admin_o_verif and func_actual:
            qs = qs.filter(territorio__delegacion=func_actual.delegacion)
        for a in qs:
            writer.writerow([
                a.codigo,
                a.fecha_actividad.strftime('%d/%m/%Y'),
                a.tipo_actividad,
                a.solicitante_nombre,
                a.solicitante_rut,
                a.territorio.nombre,
                a.responsable_tubo.nombre_completo,
                a.get_etapa_seguimiento_display(),
                a.get_estado_tubo_display(),
                a.get_estado_verificacion_display(),
            ])

    return response