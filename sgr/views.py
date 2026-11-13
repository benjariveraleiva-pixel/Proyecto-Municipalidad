import csv
import random
import string
from decouple import config
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.messages.views import SuccessMessageMixin
from django.core.mail import send_mail
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import ListView, CreateView, UpdateView

from .models import (
    Funcionario, Trimestre, Territorio, AsignacionMeta, Actividad,
    TuboCarta, BitacoraAuditoria, HistorialTubo, Vecino, JuntaVecinos,
    Hito, Evidencia, GestionSocial
)
from .forms import (
    AsignacionMetaForm, CompromisoTuboForm, TuboCartaForm,
    VecinoForm, JuntaVecinosForm, HitoForm, FuncionarioCreateForm,
    ActividadRegistroForm, SubirEvidenciaForm
)


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


@login_required(login_url='login')
def dashboard_inicio(request):
    trimestres = Trimestre.objects.all().order_by('-anio', '-numero')
    trimestre_id = request.GET.get('trimestre')
    trimestre_activo = trimestres.filter(id=trimestre_id).first() if trimestre_id else trimestres.first()

    func_actual = getattr(request.user, 'funcionario', None)
    delegacion_actual = func_actual.delegacion if func_actual else None

    filtro_funcionario = request.GET.get('funcionario', '')
    filtro_territorio = request.GET.get('territorio', '')
    filtro_q = request.GET.get('q', '').strip()

    for act in Actividad.objects.filter(ingresa_al_tubo=True, estado_tubo__in=['PENDIENTE', 'EN_PROCESO']):
        act.save()

    actividades_qs = Actividad.objects.select_related('funcionario_autor', 'responsable_tubo', 'territorio')
    asignaciones_qs = AsignacionMeta.objects.filter(activa=True).select_related('funcionario', 'meta')

    if trimestre_activo:
        asignaciones_qs = asignaciones_qs.filter(trimestre=trimestre_activo)

    if filtro_funcionario:
        actividades_qs = actividades_qs.filter(responsable_tubo_id=filtro_funcionario)
        asignaciones_qs = asignaciones_qs.filter(funcionario_id=filtro_funcionario)

    if filtro_territorio:
        actividades_qs = actividades_qs.filter(territorio_id=filtro_territorio)

    if filtro_q:
        actividades_qs = actividades_qs.filter(
            Q(codigo__icontains=filtro_q) |
            Q(solicitante_nombre__icontains=filtro_q) |
            Q(solicitante_rut__icontains=filtro_q)
        )

    total_aprobadas = actividades_qs.filter(estado_verificacion='APROBADA_PONDERA').count()
    total_pendientes_verif = actividades_qs.filter(estado_verificacion='PENDIENTE').count()
    total_vencidos = actividades_qs.filter(ingresa_al_tubo=True, estado_tubo='VENCIDO').count()

    funcionarios_lista = Funcionario.objects.select_related('cargo').all()
    semaforo_funcionarios = []
    suma_cumplimientos = 0.0

    for f in funcionarios_lista:
        metas_f = AsignacionMeta.objects.filter(funcionario=f, trimestre=trimestre_activo, activa=True)
        if not metas_f.exists():
            continue
        cumplimiento_pond_total = sum(m.resultado_ponderado for m in metas_f)
        ingresos_f = Actividad.objects.filter(funcionario_autor=f).count()

        if cumplimiento_pond_total >= 80:
            color = 'verde'
        elif cumplimiento_pond_total >= 55:
            color = 'amarillo'
        else:
            color = 'rojo'

        semaforo_funcionarios.append({
            'funcionario': f,
            'cumplimiento_ponderado': round(cumplimiento_pond_total, 1),
            'total_ingresos': ingresos_f,
            'color_semaforo': color,
        })
        suma_cumplimientos += cumplimiento_pond_total

    cumplimiento_general = round(suma_cumplimientos / len(semaforo_funcionarios), 1) if semaforo_funcionarios else 0.0

    items_tubo = []
    mapa_badges = {
        'PENDIENTE': 'estado-pendiente',
        'EN_PROCESO': 'estado-proceso',
        'REALIZADO': 'estado-realizado',
        'VENCIDO': 'estado-vencido',
    }
    for act in actividades_qs.filter(ingresa_al_tubo=True).order_by('fecha_compromiso')[:6]:
        items_tubo.append({
            'codigo': act.codigo,
            'solicitante': act.solicitante_nombre,
            'responsable': act.responsable_tubo.nombre_completo,
            'fecha_compromiso': act.fecha_compromiso,
            'estado_label': act.get_estado_tubo_display(),
            'clase_badge': mapa_badges.get(act.estado_tubo, 'estado-proceso')
        })

    for carta in TuboCarta.objects.select_related('responsable_seguimiento').all()[:4]:
        items_tubo.append({
            'codigo': carta.codigo,
            'solicitante': f"{carta.remitente} (Carta)",
            'responsable': carta.responsable_seguimiento.nombre_completo,
            'fecha_compromiso': carta.fecha_respuesta_compromiso,
            'estado_label': carta.get_estado_display(),
            'clase_badge': 'estado-proceso'
        })

    context = {
        'delegacion_actual': delegacion_actual,
        'trimestres': trimestres,
        'trimestre_activo': trimestre_activo,
        'meta_esperada_hoy': trimestre_activo.porcentaje_esperado_hoy if trimestre_activo else 0.0,
        'funcionarios_lista': funcionarios_lista,
        'territorios_lista': Territorio.objects.all(),
        'filtro_funcionario': filtro_funcionario,
        'filtro_territorio': filtro_territorio,
        'filtro_q': filtro_q,
        'cumplimiento_general': cumplimiento_general,
        'total_aprobadas': total_aprobadas,
        'total_pendientes_verif': total_pendientes_verif,
        'total_vencidos': total_vencidos,
        'asignaciones_metas': asignaciones_qs,
        'semaforo_funcionarios': semaforo_funcionarios,
        'items_tubo': items_tubo,
    }
    return render(request, 'dashboard_preview.html', context)


# ==============================================================================
# MÓDULO 1: ASIGNACIÓN DE METAS A FUNCIONARIOS
# ==============================================================================
@login_required(login_url='login')
def asignacion_metas_view(request):
    trimestres = Trimestre.objects.all().order_by('-anio', '-numero')
    trimestre_activo = trimestres.first()
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()

    if request.method == 'POST':
        form = AsignacionMetaForm(request.POST)
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

    resumen_funcionarios = []
    for f in Funcionario.objects.select_related('cargo').all():
        metas_f = AsignacionMeta.objects.filter(funcionario=f, trimestre=trimestre_activo, activa=True).select_related('meta')
        total_pond = metas_f.aggregate(total=Sum('ponderacion'))['total'] or 0
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


# ==============================================================================
# MÓDULO 2: FLUJO DE COMPROMISOS (TUBO DE GESTIÓN CON REASIGNACIÓN)
# ==============================================================================
@login_required(login_url='login')
def tubo_compromisos_view(request):
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()

    if request.method == 'POST':
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

    q = (request.GET.get('q') or request.GET.get('buscar') or '').strip()
    estado_filtro = request.GET.get('estado', '').strip()

    compromisos = Actividad.objects.filter(ingresa_al_tubo=True).select_related(
        'territorio', 'responsable_tubo', 'meta_asignada__meta', 'vecino_solicitante'
    ).order_by('-id')

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
            Q(descripcion__icontains=q) |
            Q(territorio__nombre__icontains=q) |
            Q(area_apoyo__icontains=q) |
            Q(responsable_tubo__nombres__icontains=q) |
            Q(responsable_tubo__apellidos__icontains=q)
        )

    if estado_filtro:
        compromisos = compromisos.filter(estado_tubo=estado_filtro)

    return render(request, 'tubo_compromisos.html', {
        'form': form,
        'compromisos': compromisos,
        'estados_tubo': Actividad.ESTADOS_TUBO,
        'funcionarios_tubo': Funcionario.objects.filter(estado='ACTIVO').order_by('nombres'),
        'q': q,
        'estado_filtro': estado_filtro,
    })


@login_required(login_url='login')
def cambiar_estado_compromiso(request, pk):
    if request.method == 'POST':
        comp = get_object_or_404(Actividad, pk=pk, ingresa_al_tubo=True)
        nuevo_estado = request.POST.get('nuevo_estado') or comp.estado_tubo
        nuevo_resp_id = request.POST.get('nuevo_responsable')
        observacion = request.POST.get('observacion', '').strip() or 'Actualización en el Tubo de Gestión'
        func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()

        estado_ant = comp.estado_tubo
        resp_ant = comp.responsable_tubo

        if nuevo_resp_id:
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
@login_required(login_url='login')
def tubo_cartas_view(request):
    if request.method == 'POST':
        form = TuboCartaForm(request.POST)
        if form.is_valid():
            carta = form.save()
            messages.success(request, f"Carta {carta.codigo} (N° {carta.numero_carta}) registrada exitosamente.")
            return redirect('tubo_cartas')
    else:
        form = TuboCartaForm()

    estado_filtro = request.GET.get('estado', '')
    cartas = TuboCarta.objects.select_related('delegacion', 'responsable_seguimiento').order_by('-id')
    if estado_filtro:
        cartas = cartas.filter(estado=estado_filtro)

    return render(request, 'tubo_cartas.html', {
        'form': form,
        'cartas': cartas,
        'estados_carta': TuboCarta.ESTADOS_CARTA,
        'estado_filtro': estado_filtro,
    })


@login_required(login_url='login')
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
# MANTENEDORES (CRUD): VECINOS, JUNTAS, HITOS Y FUNCIONARIOS CON CORREO SMTP
# ==============================================================================
class VecinoListView(LoginRequiredMixin, ListView):
    model = Vecino
    template_name = 'crud/vecinos_list.html'
    context_object_name = 'vecinos'


class VecinoCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Vecino
    form_class = VecinoForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('vecinos_list')
    success_message = "Vecino registrado exitosamente."
    extra_context = {'titulo': 'Registrar Nuevo Vecino', 'url_cancelar': 'vecinos_list'}


class VecinoUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Vecino
    form_class = VecinoForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('vecinos_list')
    success_message = "Vecino actualizado exitosamente."
    extra_context = {'titulo': 'Editar Vecino', 'url_cancelar': 'vecinos_list'}


class JuntaListView(LoginRequiredMixin, ListView):
    model = JuntaVecinos
    template_name = 'crud/juntas_list.html'
    context_object_name = 'juntas'


class JuntaCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = JuntaVecinos
    form_class = JuntaVecinosForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('juntas_list')
    success_message = "Junta de Vecinos registrada exitosamente."
    extra_context = {'titulo': 'Registrar Junta de Vecinos', 'url_cancelar': 'juntas_list'}


class JuntaUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = JuntaVecinos
    form_class = JuntaVecinosForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('juntas_list')
    success_message = "Junta de Vecinos actualizada exitosamente."
    extra_context = {'titulo': 'Editar Junta de Vecinos', 'url_cancelar': 'juntas_list'}


class HitoListView(LoginRequiredMixin, ListView):
    model = Hito
    template_name = 'crud/hitos_list.html'
    context_object_name = 'hitos'


class HitoCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Hito
    form_class = HitoForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('hitos_list')
    success_message = "Hito programado exitosamente."
    extra_context = {'titulo': 'Programar Nuevo Hito', 'url_cancelar': 'hitos_list'}


class HitoUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Hito
    form_class = HitoForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('hitos_list')
    success_message = "Hito actualizado exitosamente."
    extra_context = {'titulo': 'Editar Hito', 'url_cancelar': 'hitos_list'}


class FuncionarioCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Funcionario
    form_class = FuncionarioCreateForm
    template_name = 'crud/form_base.html'
    success_url = reverse_lazy('dashboard_inicio')
    extra_context = {'titulo': 'Registrar Nuevo Funcionario', 'url_cancelar': 'dashboard_inicio'}

    def form_valid(self, form):
        caracteres = string.ascii_letters + string.digits
        clave_temporal = ''.join(random.choices(caracteres, k=8))

        user = User.objects.create_user(
            username=form.cleaned_data['username'],
            email=form.cleaned_data['correo'],
            password=clave_temporal,
            first_name=form.cleaned_data['nombres'],
            last_name=form.cleaned_data['apellidos']
        )

        roles_seleccionados = form.cleaned_data['roles']
        if roles_seleccionados.filter(nombre='ADMIN').exists():
            user.is_staff = True
            user.save()

        funcionario = form.save(commit=False)
        funcionario.user = user
        funcionario.estado = 'PENDIENTE'
        funcionario.debe_cambiar_clave = True
        funcionario.save()
        funcionario.roles.set(roles_seleccionados)

        # Enviar credencial temporal de un solo uso al correo del funcionario (Sección 12)
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
# MÓDULO: REGISTRO DE ACTIVIDADES, EVIDENCIAS Y BANDEJA DEL VERIFICADOR
# ==============================================================================
@login_required(login_url='login')
def actividades_list_view(request):
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()

    if request.method == 'POST':
        form = ActividadRegistroForm(request.POST, request.FILES)
        if form.is_valid():
            act = form.save(commit=False)
            act.funcionario_autor = func_actual
            act.estado_verificacion = 'PENDIENTE'
            if not act.responsable_tubo_id:
                act.responsable_tubo = func_actual
            act.save()

            archivo = form.cleaned_data.get('archivo_evidencia')
            if archivo:
                Evidencia.objects.create(
                    actividad=act,
                    archivo=archivo,
                    autor=func_actual,
                    observacion=form.cleaned_data.get('observacion_evidencia') or 'Evidencia inicial'
                )

            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Actividades',
                accion='Registro de Actividad',
                detalle=f"Se registró la actividad {act.codigo} asociada a la meta {act.meta_asignada.meta.codigo}"
            )
            messages.success(request, f"Actividad {act.codigo} registrada y enviada a revisión del Verificador.")
            return redirect('actividades_list')
        else:
            messages.error(request, "Error al registrar la actividad. Verifique los campos y el archivo adjunto.")
    else:
        form = ActividadRegistroForm(initial={'responsable_tubo': func_actual})

    estado_filtro = request.GET.get('estado', '')
    actividades = Actividad.objects.select_related(
        'funcionario_autor', 'meta_asignada__meta', 'territorio', 'verificado_por'
    ).prefetch_related('evidencias').order_by('-id')

    if estado_filtro:
        actividades = actividades.filter(estado_verificacion=estado_filtro)

    return render(request, 'actividades_list.html', {
        'form': form,
        'form_evidencia': SubirEvidenciaForm(),
        'actividades': actividades,
        'estados_verificacion': Actividad.ESTADOS_VERIFICACION,
        'estado_filtro': estado_filtro,
    })


@login_required(login_url='login')
def adjuntar_evidencia_view(request, pk):
    act = get_object_or_404(Actividad, pk=pk)
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()

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

            if act.estado_verificacion in ['SOLICITUD_ANTECEDENTES', 'RECHAZADA']:
                act.estado_verificacion = 'PENDIENTE'
                act.save()

            BitacoraAuditoria.objects.create(
                usuario=func_actual,
                modulo='Evidencias',
                accion='Carga de Evidencia',
                detalle=f"Se adjuntó evidencia {ev.codigo} a la actividad {act.codigo}"
            )
            messages.success(request, f"Evidencia {ev.codigo} adjuntada correctamente a la actividad {act.codigo}.")
        else:
            messages.error(request, "Archivo inválido. Verifique que sea imagen/PDF y pese menos de 10 MB.")
    return redirect('actividades_list')


@login_required(login_url='login')
def bandeja_verificacion_view(request):
    estado_filtro = request.GET.get('estado', 'PENDIENTE')
    funcionario_filtro = request.GET.get('funcionario', '')

    actividades = Actividad.objects.select_related(
        'funcionario_autor', 'meta_asignada__meta', 'territorio', 'verificado_por'
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


@login_required(login_url='login')
def dictaminar_actividad_view(request, pk):
    if request.method == 'POST':
        act = get_object_or_404(Actividad, pk=pk)
        func_verificador = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()

        decision = request.POST.get('decision')
        observacion = request.POST.get('observacion_verificador', '').strip()

        if decision in ['SOLICITUD_ANTECEDENTES', 'RECHAZADA'] and not observacion:
            messages.error(request, f"Debe escribir una observación indicando el motivo al rechazar o solicitar antecedentes en {act.codigo}.")
            return redirect('bandeja_verificacion')

        estado_anterior = act.get_estado_verificacion_display()
        act.estado_verificacion = decision
        act.observacion_verificador = observacion
        act.verificado_por = func_verificador
        act.fecha_verificacion = timezone.now()
        act.save()

        BitacoraAuditoria.objects.create(
            usuario=func_verificador,
            modulo='Verificación',
            accion=f"Dictamen: {act.get_estado_verificacion_display()}",
            detalle=f"Actividad {act.codigo} pasó de '{estado_anterior}' a '{act.get_estado_verificacion_display()}'. Obs: {observacion or 'Sin observaciones'}"
        )
        messages.success(
            request,
            f"Dictamen registrado: Actividad {act.codigo} marcada como '{act.get_estado_verificacion_display()}'."
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
# PUNTO 4: GESTIONES SOCIALES (LAS 3 ETAPAS Y DÍAS DE DEMORA)
# ==============================================================================
@login_required(login_url='login')
def gestiones_sociales_view(request):
    func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()

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


@login_required(login_url='login')
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
# PUNTO 5: REPORTES Y BITÁCORA (EXPORTACIÓN CSV CON METADATOS SECCIÓN 16)
# ==============================================================================
@login_required(login_url='login')
def reportes_bitacora_view(request):
    modulo_filtro = request.GET.get('modulo', '').strip()
    q_bitacora = request.GET.get('q', '').strip()

    bitacora = BitacoraAuditoria.objects.select_related('usuario').order_by('-fecha_hora')
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
    ).order_by('-fecha')[:30]

    resumen_sistema = {
        'total_actividades': Actividad.objects.count(),
        'aprobadas': Actividad.objects.filter(estado_verificacion='APROBADA_PONDERA').count(),
        'compromisos_tubo': Actividad.objects.filter(ingresa_al_tubo=True).count(),
        'cartas': TuboCarta.objects.count(),
        'hitos': Hito.objects.count(),
        'eventos_auditoria': BitacoraAuditoria.objects.count(),
    }

    modulos_disponibles = BitacoraAuditoria.objects.values_list('modulo', flat=True).distinct()

    return render(request, 'reportes_bitacora.html', {
        'bitacora': bitacora[:100],
        'historial_tubo': historial_tubo,
        'resumen': resumen_sistema,
        'modulos_disponibles': modulos_disponibles,
        'modulo_filtro': modulo_filtro,
        'q': q_bitacora,
    })


@login_required(login_url='login')
def exportar_reporte_csv(request):
    tipo = request.GET.get('tipo', 'actividades')
    func_actual = getattr(request.user, 'funcionario', None)
    delegacion_nombre = func_actual.delegacion.nombre if func_actual and func_actual.delegacion else 'General La Serena'
    trimestre_activo = Trimestre.objects.order_by('-anio', '-numero').first()
    trimestre_str = f"{trimestre_activo.nombre} ({trimestre_activo.anio})" if trimestre_activo else '2026'
    fecha_gen = timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M:%S')

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="reporte_{tipo}_sgr.csv"'
    writer = csv.writer(response, delimiter=';')

    # Encabezado institucional exigido en Sección 16 de la guía
    writer.writerow(['SISTEMA DE GESTION DE RESULTADOS (SGR) - ILUSTRE MUNICIPALIDAD DE LA SERENA'])
    writer.writerow(['Fecha y Hora de Generacion:', fecha_gen, 'Delegacion:', delegacion_nombre, 'Trimestre:', trimestre_str])
    writer.writerow([])

    if tipo == 'bitacora':
        writer.writerow(['Fecha y Hora', 'Usuario', 'Modulo', 'Accion', 'Detalle'])
        for b in BitacoraAuditoria.objects.select_related('usuario').order_by('-fecha_hora'):
            autor = b.usuario.nombre_completo if b.usuario else 'Sistema'
            writer.writerow([b.fecha_hora.strftime('%d/%m/%Y %H:%M'), autor, b.modulo, b.accion, b.detalle])
    elif tipo == 'sociales':
        writer.writerow(['Codigo', 'Fecha Ingreso', 'Vecino', 'RUT', 'Territorio', 'Requerimiento', 'Visita', 'Informe', 'Beneficio', 'Demora (Dias)', 'Estado'])
        for gs in GestionSocial.objects.select_related('vecino', 'territorio').order_by('-id'):
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
        writer.writerow(['Codigo', 'Fecha', 'Tipo', 'Solicitante', 'RUT', 'Territorio', 'Responsable', 'Estado Tubo', 'Verificacion'])
        for a in Actividad.objects.select_related('territorio', 'responsable_tubo').order_by('-id'):
            writer.writerow([
                a.codigo,
                a.fecha_actividad.strftime('%d/%m/%Y'),
                a.tipo_actividad,
                a.solicitante_nombre,
                a.solicitante_rut,
                a.territorio.nombre,
                a.responsable_tubo.nombre_completo,
                a.get_estado_tubo_display(),
                a.get_estado_verificacion_display(),
            ])

    return response