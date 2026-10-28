import streamlit as st
from supabase import create_client
import hashlib
import secrets
import hmac
import re
import io
import pandas as pd
from datetime import date

st.set_page_config(
    page_title="Registro de Bases/Comandos",
    page_icon="🗳️",
    layout="wide",
)

# ============================================================
# OCULTAR BARRA SUPERIOR, GITHUB, SHARE Y MENÚS DE STREAMLIT
# ============================================================
st.markdown("""
    <style>
        /* Fuerza la desaparición de la barra superior, el gatito, el share y los 3 puntos */
        header {visibility: hidden !important; display: none !important;}
        [data-testid="stHeader"] {display: none !important;}
        #MainMenu {visibility: hidden !important; display: none !important;}
        .stDeployButton {display: none !important;}
        footer {visibility: hidden !important; display: none !important;}
        
        /* Elimina cualquier barra de herramientas flotante */
        [data-testid="stToolbar"] {visibility: hidden !important; display: none !important;}
        [data-testid="stDecoration"] {visibility: hidden !important; display: none !important;}
        
        /* Ajusta el margen superior para que no quede un espacio en blanco */
        .block-container {padding-top: 1rem !important;}
    </style>
""", unsafe_allow_html=True)

# ============================================================
# CONEXIÓN
# Secrets necesarios:
# SUPABASE_URL, SUPABASE_KEY, ADMIN_USER, ADMIN_PASSWORD
# ADMIN_PASSWORD debe guardarse solo en Streamlit Secrets.
# ============================================================
@st.cache_resource
def conectar_supabase():
    url = st.secrets["SUPABASE_URL"].strip()
    key = st.secrets["SUPABASE_KEY"].strip()
    return create_client(url, key)

try:
    supabase = conectar_supabase()
except Exception:
    st.error(
        "No se pudo conectar con Supabase. Revisa SUPABASE_URL y "
        "SUPABASE_KEY en Streamlit Secrets."
    )
    st.stop()


# ============================================================
# LISTAS GEOGRÁFICAS (Puno, Perú)
# ============================================================
DISTRITOS_PUNO = {
    "Azángaro": [
        "Achaya", "Arapa", "Asillo", "Azángaro", "Caminaca",
        "Chupa", "José Domingo Choquehuanca", "Muñani", "Potoni",
        "Samán", "San Antón", "San José", "San Juan de Salinas",
        "Santiago de Pupuja", "Tirapata"
    ],
    "Carabaya": [
        "Ajoyani", "Ayapata", "Coasa", "Corani", "Crucero",
        "Ituata", "Macusani", "Ollachea", "San Gabán", "Usicayos"
    ],
    "Chucuito": [
        "Desaguadero", "Huacullani", "Juli", "Kelluyo",
        "Pisacoma", "Pomata", "Zepita"
    ],
    "El Collao": ["Capazo", "Ilave", "Pilcuyo", "Santa Rosa"],
    "Huancané": [
        "Cojata", "Huancané", "Huatasani", "Inchupalla",
        "Pusi", "Rosaspata", "Taraco", "Vilque Chico"
    ],
    "Lampa": [
        "Cabanilla", "Calapuja", "Lampa", "Nicasio", "Ocuviri",
        "Palca", "Paratía", "Pucará", "Santa Lucía", "Vilavila"
    ],
    "Melgar": [
        "Antauta", "Ayaviri", "Cupi", "Llalli", "Macari",
        "Nuñoa", "Orurillo", "Santa Rosa", "Umachiri"
    ],
    "Moho": ["Conima", "Huayrapata", "Moho", "Tilali"],
    "Puno": [
        "Acora", "Amantaní", "Atuncolla", "Capachica", "Chucuito",
        "Coata", "Huata", "Mañazo", "Paucarcolla", "Pichacani",
        "Platería", "Puno", "San Antonio", "Tiquillaca", "Vilque"
    ],
    "San Antonio de Putina": [
        "Ananea", "Pedro Vilca Apaza", "Putina",
        "Quilcapuncu", "Sina"
    ],
    "San Román": ["Cabana", "Cabanillas", "Caracoto", "Juliaca"],
    "Sandia": [
        "Alto Inambari", "Cuyocuyo", "Limbani", "Patambuco",
        "Phara", "Quiaca", "San Juan del Oro", "San Pedro de Putina Punco",
        "Sandia", "Yanahuaya"
    ],
    "Yunguyo": [
        "Anapia", "Copani", "Cuturapi", "Ollaraya",
        "Tinicachi", "Unicachi", "Yunguyo"
    ],
}
PROVINCIAS = sorted(DISTRITOS_PUNO.keys())

CARGOS = [
    "Militante",
    "Coordinador de base",
    "Secretario de organización",
    "Secretario de economía",
    "Secretario de actas",
    "Fiscal",
    "Otro",
]


# ============================================================
# CONTRASEÑAS DE BASES
# Las contraseñas de bases se guardan con PBKDF2, no en texto plano.
# ============================================================
def crear_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 310000
    ).hex()
    return f"{salt}${digest}"


def verificar_password(password: str, guardada: str) -> bool:
    try:
        salt, digest = guardada.split("$", 1)
        calculado = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), 310000
        ).hex()
        return hmac.compare_digest(calculado, digest)
    except (ValueError, TypeError, AttributeError):
        return False


def credenciales_admin_validas(usuario: str, password: str) -> bool:
    try:
        admin_usuario = str(st.secrets["ADMIN_USER"]).strip()
        admin_password = str(st.secrets["ADMIN_PASSWORD"])
        return (
            hmac.compare_digest(usuario, admin_usuario)
            and hmac.compare_digest(password, admin_password)
        )
    except Exception:
        st.error(
            "Faltan ADMIN_USER o ADMIN_PASSWORD en Streamlit Secrets. "
            "Configúralos antes de iniciar sesión como administrador."
        )
        return False


def limpiar_sesion():
    for clave in (
        "base_id", "base_nombre", "base_provincia", "base_distrito",
        "es_admin", "mostrar_registro", "mostrar_integrante",
        "admin_autenticado"
    ):
        if clave in st.session_state:
            del st.session_state[clave]
    st.session_state.base_id = None
    st.session_state.base_nombre = ""
    st.session_state.base_provincia = ""
    st.session_state.base_distrito = ""
    st.session_state.es_admin = False
    st.session_state.admin_autenticado = False


# Estado de sesión
defaults = {
    "base_id": None,
    "base_nombre": "",
    "base_provincia": "",
    "base_distrito": "",
    "es_admin": False,
    "admin_autenticado": False,
    "vista_publica": "Iniciar sesión",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ============================================================
# FUNCIONES DE DATOS
# ============================================================
def cargar_bases():
    return (
        supabase.table("bases_campana")
        .select("id,nombre_base,provincia,distrito,usuario,fecha_registro")
        .order("nombre_base")
        .execute().data or []
    )


def cargar_integrantes(base_id=None):
    consulta = (
        supabase.table("integrantes_base")
        .select("id,base_id,nombres,apellidos,dni,celular,cargo,fecha_registro")
        .order("apellidos")
    )
    if base_id is not None:
        consulta = consulta.eq("base_id", base_id)
    return consulta.execute().data or []


def nombre_completo(fila):
    return f'{fila.get("nombres", "")} {fila.get("apellidos", "")}'.strip()


def dataframe_integrantes(filas, incluir_base=False):
    salida = []
    for f in filas:
        item = {
            "Nombres": f.get("nombres", ""),
            "Apellidos": f.get("apellidos", ""),
            "DNI": f.get("dni", ""),
            "Celular": f.get("celular", ""),
            "Cargo / condición": f.get("cargo") or "",
            "Fecha de registro": str(f.get("fecha_registro", ""))[:10],
        }
        if incluir_base:
            item["Base ID"] = f.get("base_id", "")
        salida.append(item)
    return pd.DataFrame(salida)


def excel_bytes(df, hoja="Registros"):
    archivo = io.BytesIO()
    with pd.ExcelWriter(archivo, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=hoja[:31])
    archivo.seek(0)
    return archivo.getvalue()


def error_supabase(mensaje_generico, error):
    # No exponer detalles internos o secretos en pantalla.
    st.error(mensaje_generico)
    st.caption("Si persiste, revisa los logs de Streamlit y el esquema de Supabase.")


# ============================================================
# ENCABEZADO
# ============================================================
st.title("🗳️ Registro de Bases y Comandos")
st.caption("Gestión de bases, integrantes y asistencia a reuniones")


# ============================================================
# PANTALLA PÚBLICA: SOLO INICIAR SESIÓN
# Ya no existe el registro público de bases.
# ============================================================
if st.session_state.base_id is None and not st.session_state.admin_autenticado:
    st.subheader("Acceso al sistema")
    modo = st.radio(
        "Tipo de acceso",
        ["Responsable de base", "Administrador"],
        horizontal=True,
        key="tipo_acceso",
    )

    if modo == "Responsable de base":
        with st.form("inicio_sesion_base"):
            usuario_login = st.text_input("Usuario").strip()
            password_login = st.text_input("Contraseña", type="password")
            entrar = st.form_submit_button("Ingresar", use_container_width=True)

        if entrar:
            try:
                resultado = (
                    supabase.table("bases_campana")
                    .select("id,nombre_base,provincia,distrito,usuario,password_hash")
                    .eq("usuario", usuario_login)
                    .limit(1)
                    .execute()
                )
                if resultado.data and verificar_password(
                    password_login, resultado.data[0].get("password_hash", "")
                ):
                    cuenta = resultado.data[0]
                    st.session_state.base_id = cuenta["id"]
                    st.session_state.base_nombre = cuenta["nombre_base"]
                    st.session_state.base_provincia = cuenta.get("provincia") or ""
                    st.session_state.base_distrito = cuenta.get("distrito") or ""
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos.")
            except Exception as e:
                error_supabase("No se pudo comprobar el acceso.", e)

    else:
        with st.form("inicio_sesion_admin"):
            usuario_admin = st.text_input("Usuario administrador")
            password_admin = st.text_input("Contraseña de administrador", type="password")
            entrar_admin = st.form_submit_button("Ingresar como administrador", use_container_width=True)
        if entrar_admin:
            if credenciales_admin_validas(usuario_admin.strip(), password_admin):
                st.session_state.admin_autenticado = True
                st.session_state.es_admin = True
                st.rerun()


# ============================================================
# PANEL DE ADMINISTRADOR
# ============================================================
if st.session_state.admin_autenticado and st.session_state.es_admin:
    st.success("Sesión de administrador")
    pestañas = st.tabs([
        "Resumen", "Crear base", "Bases e integrantes",
        "Reuniones y asistencia", "Exportar"
    ])

    # ---- Resumen ----
    with pestañas[0]:
        try:
            bases = cargar_bases()
            integrantes = cargar_integrantes()
            c1, c2 = st.columns(2)
            c1.metric("Bases registradas", len(bases))
            c2.metric("Integrantes registrados", len(integrantes))
            st.subheader("Bases por provincia")
            if bases:
                df_bases = pd.DataFrame([
                    {
                        "Base": b.get("nombre_base", ""),
                        "Provincia": b.get("provincia") or "Sin asignar",
                        "Distrito": b.get("distrito") or "Sin asignar",
                        "Usuario": b.get("usuario", ""),
                    } for b in bases
                ])
                resumen = (
                    df_bases.groupby("Provincia", dropna=False)
                    .size().reset_index(name="Cantidad de bases")
                    .sort_values("Cantidad de bases", ascending=False)
                )
                st.dataframe(resumen, use_container_width=True, hide_index=True)
                st.dataframe(df_bases, use_container_width=True, hide_index=True)
            else:
                st.info("Todavía no hay bases registradas.")
        except Exception as e:
            error_supabase("No se pudo cargar el resumen. Comprueba las columnas nuevas.", e)

    # ---- Crear base ----
    with pestañas[1]:
        st.subheader("Crear una base o comando")
        st.info("Solo el administrador puede crear cuentas de base.")
        with st.form("crear_base_admin"):
            nombre = st.text_input("Nombre de la base o comando")
            provincia = st.selectbox("Provincia", ["Seleccionar provincia"] + PROVINCIAS)
            if provincia in DISTRITOS_PUNO:
                distritos_disponibles = DISTRITOS_PUNO[provincia]
            else:
                distritos_disponibles = []
            distrito = st.selectbox(
                "Distrito",
                ["Seleccionar distrito"] + sorted(distritos_disponibles),
                disabled=not distritos_disponibles,
            )
            usuario = st.text_input("Crear usuario de la base").strip()
            password = st.text_input(
                "Contraseña inicial (8 a 10 caracteres)", type="password"
            )
            confirmar = st.text_input("Confirmar contraseña", type="password")
            acepta = st.checkbox(
                "Confirmo que estoy autorizado para crear esta cuenta y que se informó "
                "el uso de los datos personales."
            )
            crear = st.form_submit_button("Crear base")

        if crear:
            if not nombre.strip() or provincia not in DISTRITOS_PUNO or distrito not in DISTRITOS_PUNO.get(provincia, []):
                st.warning("Completa el nombre, la provincia y el distrito.")
            elif not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", usuario):
                st.warning("El usuario debe tener de 3 a 40 caracteres: letras, números, punto, guion o guion bajo.")
            elif not 8 <= len(password) <= 10:
                st.warning("La contraseña debe tener entre 8 y 10 caracteres.")
            elif password != confirmar:
                st.warning("Las contraseñas no coinciden.")
            elif not acepta:
                st.warning("Confirma la autorización antes de crear la base.")
            else:
                try:
                    existe = (
                        supabase.table("bases_campana").select("id")
                        .eq("usuario", usuario).limit(1).execute()
                    )
                    if existe.data:
                        st.error("Ese nombre de usuario ya está ocupado.")
                    else:
                        supabase.table("bases_campana").insert({
                            "nombre_base": nombre.strip(),
                            "provincia": provincia,
                            "distrito": distrito,
                            "usuario": usuario,
                            "password_hash": crear_hash(password),
                        }).execute()
                        st.success("Base creada correctamente.")
                        st.info("Entrega la contraseña inicial de forma privada al responsable. No la publiques ni la reutilices.")
                except Exception as e:
                    error_supabase("No se pudo crear la base. Verifica las columnas de Supabase.", e)

    # ---- Bases e integrantes ----
    with pestañas[2]:
        st.subheader("Bases e integrantes")
        try:
            bases = cargar_bases()
            if bases:
                mapa_bases = {
                    f'{b.get("nombre_base","")} — {b.get("provincia") or "Sin provincia"} / {b.get("distrito") or "Sin distrito"} (ID {b["id"]})': b
                    for b in bases
                }
                seleccion = st.selectbox("Seleccionar base", list(mapa_bases.keys()))
                base_sel = mapa_bases[seleccion]
                miembros = cargar_integrantes(base_sel["id"])
                st.write(
                    f'**Provincia:** {base_sel.get("provincia") or "Sin asignar"} · '
                    f'**Distrito:** {base_sel.get("distrito") or "Sin asignar"} · '
                    f'**Integrantes:** {len(miembros)}'
                )
                buscar = st.text_input("Buscar por nombre, apellido o DNI", key="buscar_admin")
                filtrados = [
                    f for f in miembros
                    if buscar.strip().lower() in (
                        nombre_completo(f) + " " + str(f.get("dni", ""))
                    ).lower()
                ]
                if filtrados:
                    st.dataframe(dataframe_integrantes(filtrados), use_container_width=True, hide_index=True)
                else:
                    st.info("No hay integrantes que coincidan con la búsqueda.")
            else:
                st.info("No hay bases registradas.")
        except Exception as e:
            error_supabase("No se pudieron consultar las bases e integrantes.", e)

    # ---- Reuniones y asistencia ----
    with pestañas[3]:
        st.subheader("Reuniones y asistencia")
        st.write("Crea una reunión y luego marca «Presente» junto a cada persona que asistió.")
        with st.form("crear_reunion"):
            nombre_reunion = st.text_input("Nombre de la reunión")
            fecha_reunion = st.date_input("Fecha de la reunión", value=date.today())
            lugar_reunion = st.text_input("Lugar (opcional)")
            crear_reunion_btn = st.form_submit_button("Crear reunión")
        if crear_reunion_btn:
            if not nombre_reunion.strip():
                st.warning("Escribe el nombre de la reunión.")
            else:
                try:
                    creada = supabase.table("reuniones").insert({
                        "nombre": nombre_reunion.strip(),
                        "fecha": fecha_reunion.isoformat(),
                        "lugar": lugar_reunion.strip() or None,
                    }).execute()
                    if creada.data:
                        st.success("Reunión creada.")
                    else:
                        st.warning("Supabase no devolvió el registro de la reunión.")
                except Exception as e:
                    error_supabase("No se pudo crear la reunión. Comprueba que ejecutaste el SQL de reuniones.", e)

        st.divider()
        try:
            reuniones = (
                supabase.table("reuniones")
                .select("id,nombre,fecha,lugar")
                .order("fecha", desc=True)
                .execute().data or []
            )
            if reuniones:
                mapa_reuniones = {
                    f'{r["fecha"]} — {r["nombre"]} (ID {r["id"]})': r
                    for r in reuniones
                }
                reunion_label = st.selectbox("Seleccionar reunión", list(mapa_reuniones.keys()))
                reunion_sel = mapa_reuniones[reunion_label]
                todas_bases = cargar_bases()
                if todas_bases:
                    base_labels = {
                        f'{b.get("nombre_base","")} — {b.get("provincia") or ""}/{b.get("distrito") or ""} (ID {b["id"]})': b
                        for b in todas_bases
                    }
                    base_label = st.selectbox("Seleccionar base para pasar lista", list(base_labels.keys()))
                    base_asistencia = base_labels[base_label]
                    miembros = cargar_integrantes(base_asistencia["id"])
                    st.write(f'**Integrantes de {base_asistencia["nombre_base"]}:** {len(miembros)}')
                    if miembros:
                        asistencia_existente = (
                            supabase.table("asistencias")
                            .select("integrante_id,presente")
                            .eq("reunion_id", reunion_sel["id"])
                            .execute().data or []
                        )
                        presentes_ids = {a["integrante_id"] for a in asistencia_existente if a.get("presente")}
                        st.caption("Marca únicamente a quienes están presentes. No marcar a una persona no registra una falta.")
                        for miembro in miembros:
                            col_nombre, col_boton = st.columns([4, 1])
                            with col_nombre:
                                st.write(f'**{nombre_completo(miembro)}** · {miembro.get("cargo") or "Sin cargo asignado"}')
                            with col_boton:
                                ya_presente = miembro["id"] in presentes_ids
                                if ya_presente:
                                    st.button("✓ Presente", key=f"presente_{reunion_sel['id']}_{miembro['id']}", disabled=True, use_container_width=True)
                                else:
                                    if st.button("Marcar presente", key=f"marcar_{reunion_sel['id']}_{miembro['id']}", use_container_width=True):
                                        try:
                                            supabase.table("asistencias").upsert({
                                                "reunion_id": reunion_sel["id"],
                                                "integrante_id": miembro["id"],
                                                "presente": True,
                                            }, on_conflict="reunion_id,integrante_id").execute()
                                            st.success(f"Asistencia guardada para {nombre_completo(miembro)}.")
                                            st.rerun()
                                        except Exception as e:
                                            error_supabase("No se pudo guardar la asistencia.", e)
                        st.metric("Presentes registrados", len(presentes_ids))
                    else:
                        st.info("Esta base todavía no tiene integrantes.")
                st.divider()
                st.subheader("Historial de la reunión")
                historial = (
                    supabase.table("asistencias")
                    .select("integrante_id,presente,integrantes_base(nombres,apellidos,dni,cargo)")
                    .eq("reunion_id", reunion_sel["id"])
                    .eq("presente", True)
                    .execute().data or []
                )
                if historial:
                    historial_df = pd.DataFrame([
                        {
                            "Integrante": (
                                f'{a.get("integrantes_base", {}).get("nombres", "")} '
                                f'{a.get("integrantes_base", {}).get("apellidos", "")}'
                            ).strip(),
                            "DNI": a.get("integrantes_base", {}).get("dni", ""),
                            "Cargo": a.get("integrantes_base", {}).get("cargo", ""),
                            "Estado": "Presente",
                        } for a in historial
                    ])
                    st.dataframe(historial_df, use_container_width=True, hide_index=True)
                    st.download_button(
                        "Descargar asistencia de esta reunión (Excel)",
                        data=excel_bytes(historial_df, "Asistencia"),
                        file_name=f"asistencia_reunion_{reunion_sel['id']}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                else:
                    st.info("Todavía no se ha marcado a nadie como presente.")
            else:
                st.info("Primero crea una reunión.")
        except Exception as e:
            error_supabase("No se pudo cargar el módulo de asistencia. Revisa las tablas y las relaciones.", e)

    # ---- Exportar ----
    with pestañas[4]:
        st.subheader("Exportar datos")
        st.warning("Los archivos pueden contener datos personales. Guárdalos y compártelos solo con personas autorizadas.")
        try:
            bases = cargar_bases()
            integrantes = cargar_integrantes()
            c1, c2 = st.columns(2)
            with c1:
                if bases:
                    dfb = pd.DataFrame([{
                        "Nombre de base": b.get("nombre_base", ""),
                        "Provincia": b.get("provincia") or "",
                        "Distrito": b.get("distrito") or "",
                        "Usuario": b.get("usuario", ""),
                        "Fecha de registro": str(b.get("fecha_registro", ""))[:10],
                    } for b in bases])
                    st.download_button(
                        "Descargar bases (Excel)",
                        data=excel_bytes(dfb, "Bases"),
                        file_name="bases_campana.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
            with c2:
                if integrantes:
                    dfi = dataframe_integrantes(integrantes, incluir_base=True)
                    st.download_button(
                        "Descargar integrantes (Excel)",
                        data=excel_bytes(dfi, "Integrantes"),
                        file_name="integrantes_bases.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
        except Exception as e:
            error_supabase("No se pudieron preparar los archivos de exportación.", e)

    if st.button("Cerrar sesión de administrador"):
        limpiar_sesion()
        st.rerun()


# ============================================================
# PANEL DEL RESPONSABLE DE BASE
# ============================================================
if st.session_state.base_id is not None:
    base_id = st.session_state.base_id
    st.success(
        f'Sesión: {st.session_state.base_nombre} · '
        f'{st.session_state.base_provincia} / {st.session_state.base_distrito}'
    )
    st.subheader("Integrantes de tu base")

    with st.expander("Agregar integrante", expanded=st.session_state.get("mostrar_integrante", False)):
        with st.form("form_integrante"):
            nombres = st.text_input("Nombres")
            apellidos = st.text_input("Apellidos")
            dni = st.text_input("DNI (8 dígitos)")
            celular = st.text_input("Celular (9 a 15 dígitos)")
            cargo_seleccionado = st.selectbox("Cargo o condición", CARGOS)
            cargo_otro = ""
            if cargo_seleccionado == "Otro":
                cargo_otro = st.text_input("Especifica el cargo o condición")
            consentimiento = st.checkbox(
                "Confirmo que la persona fue informada sobre el uso de sus datos "
                "y autorizó su registro."
            )
            guardar = st.form_submit_button("Guardar integrante")
        if guardar:
            cargo_final = cargo_otro.strip() if cargo_seleccionado == "Otro" else cargo_seleccionado
            if not nombres.strip() or not apellidos.strip():
                st.warning("Completa nombres y apellidos.")
            elif not re.fullmatch(r"\d{8}", dni.strip()):
                st.warning("El DNI debe contener exactamente 8 dígitos.")
            elif not re.fullmatch(r"\+?\d{9,15}", celular.strip()):
                st.warning("Ingresa un celular válido, con 9 a 15 dígitos.")
            elif cargo_seleccionado == "Otro" and not cargo_final:
                st.warning("Especifica el cargo o condición.")
            elif not consentimiento:
                st.warning("Confirma que la persona fue informada y autorizó el registro.")
            else:
                try:
                    supabase.table("integrantes_base").insert({
                        "base_id": base_id,
                        "nombres": nombres.strip(),
                        "apellidos": apellidos.strip(),
                        "dni": dni.strip(),
                        "celular": celular.strip(),
                        "cargo": cargo_final,
                    }).execute()
                    st.success("Integrante registrado.")
                    st.rerun()
                except Exception as e:
                    error_supabase("No se pudo guardar el integrante. Comprueba si el DNI ya existe en esta base.", e)

    try:
        filas = cargar_integrantes(base_id)
        st.metric("Total de integrantes", len(filas))
        if filas:
            busqueda = st.text_input("Buscar integrante por nombre o DNI", key="buscar_base")
            filtrados = [
                f for f in filas
                if busqueda.strip().lower() in (
                    nombre_completo(f) + " " + str(f.get("dni", ""))
                ).lower()
            ]
            st.dataframe(dataframe_integrantes(filtrados), use_container_width=True, hide_index=True)
            st.download_button(
                "Descargar integrantes de mi base (Excel)",
                data=excel_bytes(dataframe_integrantes(filas), "Integrantes"),
                file_name="integrantes_mi_base.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            st.info("Todavía no hay integrantes registrados.")
    except Exception as e:
        error_supabase("No se pudo cargar la lista de integrantes.", e)

    if st.button("Cerrar sesión de base"):
        limpiar_sesion()
        st.rerun()


# ============================================================
# AVISO DE PRIVACIDAD
# ============================================================
st.divider()
with st.expander("Aviso de privacidad"):
    st.write(
        "Los nombres, DNI y teléfonos son datos personales. Recógelos solo "
        "con una finalidad informada y autorización válida, limita el acceso "
        "a usuarios autorizados y conserva los datos solo el tiempo necesario. "
        "Los registros de asistencia también deben utilizarse únicamente "
        "para la finalidad comunicada a las personas."
    )
