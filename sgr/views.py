from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from .models import (
    Funcionario, Trimestre, Territorio, AsignacionMeta, Actividad, TuboCarta, BitacoraAuditoria
)
from django.shortcuts import get_object_or_404
from django.db.models import Sum
from .models import HistorialTubo
from .forms import AsignacionMetaForm, CompromisoTuboForm, TuboCartaForm
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from .models import Vecino, JuntaVecinos, Hito
from .forms import VecinoForm, JuntaVecinosForm, HitoForm
import string
import random
from django.contrib.auth.models import User
from django.urls import reverse_lazy
from django.views.generic import CreateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib import messages
from .models import Funcionario
from .forms import FuncionarioCreateForm


def login_institucional(request):
    if request.user.is_authenticated:
        return redirect('dashboard_inicio')

    if request.method == 'POST':
        identificador = request.POST.get('username', '').strip()
        clave = request.POST.get('password', '')

        # Permitir login por username o por correo institucional
        func = Funcionario.objects.filter(
            Q(user__username__iexact=identificador) | Q(correo__iexact=identificador)
        ).select_related('user').first()

        # Verificar bloqueo temporal por intentos fallidos (Sección 12 Requerimientos)
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

    # Actualizar automáticamente compromisos vencidos antes de consultar
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

    # KPIs reales
    total_aprobadas = actividades_qs.filter(estado_verificacion='APROBADA_PONDERA').count()
    total_pendientes_verif = actividades_qs.filter(estado_verificacion='PENDIENTE').count()
    total_vencidos = actividades_qs.filter(ingresa_al_tubo=True, estado_tubo='VENCIDO').count()

    # Cálculo de Semáforo por Funcionario
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

    # Unificar Compromisos del Tubo y Cartas para la tabla resumen
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
# MÓDULO 1 LUNES: ASIGNACIÓN DE METAS A FUNCIONARIOS
# ==============================================================================
@login_required(login_url='login')
def asignacion_metas_view(request):
    trimestres = Trimestre.objects.all().order_by('-anio', '-numero')
    trimestre_activo = trimestres.first()

    if request.method == 'POST':
        form = AsignacionMetaForm(request.POST)
        if form.is_valid():
            asig = form.save()
            messages.success(
                request,
                f"Meta '{asig.meta.nombre}' asignada a {asig.funcionario.nombre_completo} ({asig.ponderacion}%)."
            )
            return redirect('asignacion_metas')
        else:
            messages.error(request, "No se pudo asignar la meta. Revise las validaciones del formulario.")
    else:
        form = AsignacionMetaForm(initial={'trimestre': trimestre_activo, 'activa': True})

    # Resumen de ponderación acumulada por funcionario en el trimestre activo
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
# MÓDULO 2 LUNES: FLUJO DE COMPROMISOS (TUBO DE GESTIÓN)
# ==============================================================================
@login_required(login_url='login')
def tubo_compromisos_view(request):
    if request.method == 'POST':
        form = CompromisoTuboForm(request.POST)
        if form.is_valid():
            comp = form.save(commit=False)
            func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()
            comp.funcionario_autor = func_actual
            comp.ingresa_al_tubo = True
            comp.estado_tubo = 'PENDIENTE'
            comp.save()
            messages.success(request, f"Compromiso {comp.codigo} ingresado al Tubo de Gestión.")
            return redirect('tubo_compromisos')
    else:
        form = CompromisoTuboForm()

    # Actualizar vencidos y aplicar filtros
    for act in Actividad.objects.filter(ingresa_al_tubo=True, estado_tubo__in=['PENDIENTE', 'EN_PROCESO']):
        act.save()

    estado_filtro = request.GET.get('estado', '')
    q = request.GET.get('q', '').strip()

    compromisos = Actividad.objects.filter(ingresa_al_tubo=True).select_related(
        'responsable_tubo', 'territorio', 'meta_asignada'
    ).order_by('-id')

    if estado_filtro:
        compromisos = compromisos.filter(estado_tubo=estado_filtro)
    if q:
        compromisos = compromisos.filter(
            Q(codigo__icontains=q) | Q(solicitante_nombre__icontains=q) | Q(solicitante_rut__icontains=q)
        )

    return render(request, 'tubo_compromisos.html', {
        'form': form,
        'compromisos': compromisos,
        'estados_tubo': Actividad.ESTADOS_TUBO,
        'estado_filtro': estado_filtro,
        'q': q,
    })


@login_required(login_url='login')
def cambiar_estado_compromiso(request, pk):
    if request.method == 'POST':
        comp = get_object_or_404(Actividad, pk=pk, ingresa_al_tubo=True)
        nuevo_estado = request.POST.get('nuevo_estado')
        observacion = request.POST.get('observacion', '').strip() or 'Actualización de estado en el Tubo'
        func_actual = getattr(request.user, 'funcionario', None) or Funcionario.objects.first()

        estado_ant = comp.estado_tubo
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
            autor=func_actual,
            motivo_observacion=observacion
        )
        messages.success(request, f"Estado del compromiso {comp.codigo} actualizado a '{comp.get_estado_tubo_display()}'.")
    return redirect('tubo_compromisos')


# ==============================================================================
# MÓDULO 3 LUNES: FLUJO DE CARTAS (TUBO DE CARTAS)
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
# MANTENEDORES (CRUD): VECINOS, JUNTAS E HITOS
# ==============================================================================

# --- CRUD VECINOS ---
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

# --- CRUD JUNTAS DE VECINOS ---
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

# --- CRUD HITOS PROGRAMADOS ---
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
    success_url = reverse_lazy('dashboard_inicio') # Redirige al dashboard temporalmente
    extra_context = {'titulo': 'Registrar Nuevo Funcionario', 'url_cancelar': 'dashboard_inicio'}

    def form_valid(self, form):
        # 1. Generar credencial temporal de un solo uso (8 caracteres aleatorios)
        caracteres = string.ascii_letters + string.digits
        clave_temporal = ''.join(random.choices(caracteres, k=8))
        
        # 2. Crear el User nativo de Django
        user = User.objects.create_user(
            username=form.cleaned_data['username'],
            email=form.cleaned_data['correo'],
            password=clave_temporal,
            first_name=form.cleaned_data['nombres'],
            last_name=form.cleaned_data['apellidos']
        )
        
        # Dar acceso al admin de Django solo si se le asigna el rol ADMIN
        roles_seleccionados = form.cleaned_data['roles']
        if roles_seleccionados.filter(nombre='ADMIN').exists():
            user.is_staff = True
            user.save()

        # 3. Vincular el Funcionario al User y forzar estado PENDIENTE
        funcionario = form.save(commit=False)
        funcionario.user = user
        funcionario.estado = 'PENDIENTE'
        funcionario.debe_cambiar_clave = True
        funcionario.save()
        
        # 4. Guardar la relación ManyToMany de los roles
        funcionario.roles.set(roles_seleccionados)
        
        # 5. Mostrar la clave generada al Administrador (En producción esto se envía por correo)
        messages.success(self.request, f"Funcionario registrado con éxito.")
        messages.warning(self.request, f"Credencial temporal para {user.username}: {clave_temporal} (Copie esta clave y entréguesela al funcionario).")
        
        return super().form_valid(form)