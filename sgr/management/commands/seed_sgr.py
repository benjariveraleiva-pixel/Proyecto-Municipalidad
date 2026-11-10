from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from sgr.models import (
    Delegacion, Territorio, Cargo, Rol, Funcionario,
    Vecino, JuntaVecinos, ParticipacionJunta, Hito,
    Trimestre, Meta, AsignacionMeta, Actividad, TuboCarta
)


class Command(BaseCommand):
    help = 'Carga los datos iniciales reales de las Delegaciones Municipales de La Serena'

    def handle(self, *args, **kwargs):
        self.stdout.write("Inicializando base de datos municipal SGR...")

        # 1. Roles del sistema
        roles_dict = {}
        for cod, _ in Rol.ROLES_SISTEMA:
            rol_obj, _ = Rol.objects.get_or_create(nombre=cod)
            roles_dict[cod] = rol_obj

        # 2. Cargos oficiales del Descriptor de Funciones Municipal
        cargos_nombres = [
            'Delegado Municipal',
            'Gestor Social',
            'Apoyo Administrativo',
            'Territorial Organizaciones Comunitarias',
            'Gestor de Compras y Proyectos',
            'Gestión y Planificación',
            'Coordinador de Servicios Comunitarios',
        ]
        cargos_dict = {}
        for nombre in cargos_nombres:
            c_obj, _ = Cargo.objects.get_or_create(nombre=nombre)
            cargos_dict[nombre] = c_obj

        # 3. Delegaciones de La Serena y sus Territorios
        del_companias, _ = Delegacion.objects.get_or_create(
            nombre='Compañías', defaults={'direccion': 'Esmeralda 2422, Las Compañías'}
        )
        del_rural, _ = Delegacion.objects.get_or_create(
            nombre='Rural', defaults={'direccion': 'Ruta D-205, Algarrobito'}
        )
        del_avmar, _ = Delegacion.objects.get_or_create(
            nombre='Avenida del Mar', defaults={'direccion': 'Av. del Mar 2500'}
        )

        ter_centro, _ = Territorio.objects.get_or_create(nombre='Las Compañías Centro', delegacion=del_companias)
        ter_olivar, _ = Territorio.objects.get_or_create(nombre='El Olivar / La Varilla', delegacion=del_companias)
        ter_lambert, _ = Territorio.objects.get_or_create(nombre='Pueblo de Lambert', delegacion=del_rural)

        # 4. Usuarios y Funcionarios Reales para Login (Contraseña: muni2026)
        usuarios_seed = [
            ('admin_sgr', '15.234.567-8', 'Administrador', 'General SGR', 'admin@laserena.cl', 'Gestión y Planificación', ['ADMIN', 'VERIFICADOR']),
            ('delegado_comp', '13.456.789-0', 'Roberto', 'Alcántara', 'ralcantara@laserena.cl', 'Delegado Municipal', ['DELEGADO']),
            ('amorales', '18.765.432-1', 'Andrea', 'Morales', 'amorales@laserena.cl', 'Gestor Social', ['FUNCIONARIO']),
            ('frojas', '19.112.233-4', 'Felipe', 'Rojas', 'frojas@laserena.cl', 'Territorial Organizaciones Comunitarias', ['FUNCIONARIO']),
            ('cdiaz', '17.998.877-6', 'Camila', 'Díaz', 'cdiaz@laserena.cl', 'Apoyo Administrativo', ['FUNCIONARIO']),
            ('verificador', '16.543.210-K', 'Erika', 'Miles', 'emiles@laserena.cl', 'Gestión y Planificación', ['VERIFICADOR']),
        ]

        funcionarios_dict = {}
        for username, rut, nom, ape, email, cargo_nom, lista_roles in usuarios_seed:
            user, created = User.objects.get_or_create(username=username, defaults={
                'first_name': nom, 'last_name': ape, 'email': email, 'is_staff': ('ADMIN' in lista_roles)
            })
            if created:
                user.set_password('muni2026')
                user.save()

            func, _ = Funcionario.objects.get_or_create(
                user=user,
                defaults={
                    'rut': rut,
                    'nombres': nom,
                    'apellidos': ape,
                    'correo': email,
                    'cargo': cargos_dict[cargo_nom],
                    'delegacion': del_companias,
                }
            )
            for r_cod in lista_roles:
                func.roles.add(roles_dict[r_cod])
            funcionarios_dict[username] = func

        # 5. Trimestre Activo (Trimestre 4 - 2026)
        tri4, _ = Trimestre.objects.get_or_create(
            anio=2026, numero=4,
            defaults={
                'nombre': 'Trimestre 4 (Oct - Dic)',
                'fecha_inicio': date(2026, 10, 1),
                'fecha_termino': date(2026, 12, 31),
                'estado': 'ABIERTO'
            }
        )

        # 6. Catálogo de Metas y Asignación Individual a Funcionarios
        m1, _ = Meta.objects.get_or_create(nombre='Atención social y programas comunitarios', defaults={'unidad_medida': 'Atenciones'})
        m2, _ = Meta.objects.get_or_create(nombre='Participación ciudadana y asesoría JJVV', defaults={'unidad_medida': 'Visitas / Reuniones'})
        m3, _ = Meta.objects.get_or_create(nombre='Soluciones de ingresos al Tubo y Cartas', defaults={'unidad_medida': 'Solicitudes resueltas'})

        asig_andrea_1, _ = AsignacionMeta.objects.get_or_create(
            funcionario=funcionarios_dict['amorales'], meta=m1, trimestre=tri4,
            defaults={'cantidad_objetivo': 10, 'ponderacion': 60.00}
        )
        asig_andrea_2, _ = AsignacionMeta.objects.get_or_create(
            funcionario=funcionarios_dict['amorales'], meta=m3, trimestre=tri4,
            defaults={'cantidad_objetivo': 5, 'ponderacion': 40.00}
        )
        asig_felipe_1, _ = AsignacionMeta.objects.get_or_create(
            funcionario=funcionarios_dict['frojas'], meta=m2, trimestre=tri4,
            defaults={'cantidad_objetivo': 8, 'ponderacion': 70.00}
        )
        asig_camila_1, _ = AsignacionMeta.objects.get_or_create(
            funcionario=funcionarios_dict['cdiaz'], meta=m3, trimestre=tri4,
            defaults={'cantidad_objetivo': 12, 'ponderacion': 100.00}
        )

        # 7. Vecinos, Junta de Vecinos e Hito Inicial
        vecino1, _ = Vecino.objects.get_or_create(
            rut='12.345.678-5',
            defaults={'nombres': 'Yesenia', 'apellidos': 'Merino Vega', 'telefono': '+56974193201', 'direccion': 'Pasaje El Toqui 412', 'territorio': ter_centro}
        )
        jjvv1, _ = JuntaVecinos.objects.get_or_create(
            nombre='JJVV Las Violetas',
            defaults={'direccion': 'Av. La Paz 1020', 'delegacion': del_companias, 'territorio': ter_centro, 'fecha_constitucion': date(2015, 5, 20)}
        )
        ParticipacionJunta.objects.get_or_create(vecino=vecino1, junta=jjvv1, defaults={'es_dirigente': True, 'cargo_directiva': 'Presidenta'})

        hito1, _ = Hito.objects.get_or_create(
            nombre='Operativo Navidad Territorial 2026',
            defaults={
                'periodicidad': 'Anual',
                'fecha_inicio': date(2026, 11, 20),
                'fecha_termino': date(2026, 12, 22),
                'delegacion': del_companias,
                'territorio': ter_centro,
                'estado': 'PROXIMO'
            }
        )
        hito1.responsables.add(funcionarios_dict['amorales'], funcionarios_dict['frojas'])

        # 8. Actividades Reales y Compromisos en el Tubo + Carta Inicial
        if Actividad.objects.count() == 0:
            hoy = date.today()
            Actividad.objects.create(
                fecha_actividad=hoy - timedelta(days=3),
                funcionario_autor=funcionarios_dict['amorales'],
                meta_asignada=asig_andrea_1,
                tipo_actividad='Atención Social Presencial',
                descripcion='Entrega de informe social y gestión de beneficio habitacional',
                vecino_solicitante=vecino1,
                solicitante_nombre=vecino1.nombre_completo,
                solicitante_rut=vecino1.rut,
                solicitante_telefono=vecino1.telefono,
                territorio=ter_centro,
                ingresa_al_tubo=True,
                responsable_tubo=funcionarios_dict['amorales'],
                area_apoyo='DIDECO Social',
                fecha_compromiso=hoy + timedelta(days=4),
                estado_tubo='EN_PROCESO',
                estado_verificacion='APROBADA_PONDERA'
            )
            Actividad.objects.create(
                fecha_actividad=hoy - timedelta(days=5),
                funcionario_autor=funcionarios_dict['frojas'],
                meta_asignada=asig_felipe_1,
                tipo_actividad='Reunión con Organización Comunitaria',
                descripcion='Solicitud de poda y mejoramiento de luminarias con directiva JJVV Las Violetas',
                solicitante_nombre='JJVV Las Violetas',
                solicitante_telefono='+56988776655',
                territorio=ter_centro,
                ingresa_al_tubo=True,
                responsable_tubo=funcionarios_dict['frojas'],
                area_apoyo='DISERCO / Alumbrado Público',
                fecha_compromiso=hoy - timedelta(days=1),  # Vencido automáticamente
                estado_tubo='PENDIENTE',
                estado_verificacion='PENDIENTE'
            )

        TuboCarta.objects.get_or_create(
            numero_carta='OF-2026-118',
            defaults={
                'remitente': 'Miguel Araya (Comunidad El Rincón)',
                'destinatario': 'Delegado Municipal Las Compañías',
                'telefono': '+56955443322',
                'materia': 'Solicitud de maquinaria pesada para perfilado de camino en sector La Varilla',
                'delegacion': del_companias,
                'responsable_seguimiento': funcionarios_dict['cdiaz'],
                'area_derivada': 'DISERCO Maquinarias',
                'fecha_respuesta_compromiso': date.today() + timedelta(days=5),
                'estado': 'EN_PROCESO'
            }
        )

        self.stdout.write(self.style.SUCCESS("¡Datos municipales cargados con éxito! Usuarios creados con clave: muni2026"))