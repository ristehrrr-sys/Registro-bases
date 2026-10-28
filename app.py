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
    page_title="Registro de Bases y Comandos",
    page_icon="🗳️",
    layout="wide",
)

# ============================================================
# OCULTAR BARRA SUPERIOR Y MENÚS DE STREAMLIT (como en tu versión)
# ============================================================
st.markdown("""
    <style>
        header {visibility: hidden !important; display: none !important;}
        [data-testid="stHeader"] {display: none !important;}
        #MainMenu {visibility: hidden !important; display: none !important;}
        .stDeployButton {display: none !important;}
        footer {visibility: hidden !important; display: none !important;}
        [data-testid="stToolbar"] {visibility: hidden !important; display: none !important;}
        [data-testid="stDecoration"] {visibility: hidden !important; display: none !important;}
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
def cargar_bases(solo_activas=False):
    q = supabase.table("bases_campana").select(
        "id,nombre_base,provincia,distrito,usuario,fecha_registro,activo"
    ).order("nombre_base")
    if solo_activas:
        q = q.eq("activo", True)
    return q.execute().data or []


def cargar_integrantes(base_id=None, solo_bases_activas=False):
    q = supabase.table("integrantes_base").select(
        "id,base_id,nombres,apellidos,dni,celular,cargo,fecha_registro"
    ).order("apellidos")
    if base_id is not None:
        q = q.eq("base_id", base_id)
    filas = q.execute().data or []
    if solo_bases_activas:
        activos = {str(b["id"]) for b in cargar_bases(solo_activas=True)}
        filas = [f for f in filas if str(f.get("base_id")) in activos]
    return filas


def nombre_completo(fila):
    return f'{fila.get("nombres", "")} {fila.get("apellidos", "")}'.strip()


def excel_bytes(df, hoja="Registros"):
    archivo = io.BytesIO()
    with pd.ExcelWriter(archivo, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=hoja[:31])
    archivo.seek(0)
    return archivo.getvalue()


def excel_con_hojas(hojas):
    archivo = io.BytesIO()
    with pd.ExcelWriter(archivo, engine="openpyxl") as writer:
        for nombre, df in hojas.items():
            (df if not df.empty else pd.DataFrame({"Sin registros": []})).to_excel(
                writer, index=False, sheet_name=nombre[:31]
            )
    archivo.seek(0)
    return archivo.getvalue()


def df_bases(filas):
    return pd.DataFrame([{
        "Base": b.get("nombre_base", ""), "Provincia": b.get("provincia", ""),
        "Distrito": b.get("distrito", ""), "Usuario": b.get("usuario", ""),
        "Estado": "Activa" if b.get("activo", True) else "Desactivada",
        "Fecha de registro": str(b.get("fecha_registro", ""))[:10]
    } for b in filas])


def df_integrantes(filas, mapa_bases=None):
    mapa_bases = mapa_bases or {}
    return pd.DataFrame([{
        "Base": mapa_bases.get(str(f.get("base_id")), str(f.get("base_id", ""))),
        "Nombres": f.get("nombres", ""), "Apellidos": f.get("apellidos", ""),
        "DNI": f.get("dni", ""), "Celular": f.get("celular", ""),
        "Cargo / condición en esta base": f.get("cargo") or "",
        "Fecha de registro": str(f.get("fecha_registro", ""))[:10]
    } for f in filas])


def error_supabase(mensaje, error=None):
    st.error(mensaje)
    st.caption("Comprueba que ejecutaste el SQL de actualización y que los Secrets de Supabase son correctos.")


def cargar_reuniones_generales():
    return supabase.table("reuniones_generales").select(
        "id,fecha,tema,creada_en"
    ).order("fecha", desc=True).execute().data or []


def cargar_asistencias_generales(reunion_id):
    return supabase.table("asistencias_generales").select(
        "id,reunion_id,dni,nombres,apellidos,celular,bases_texto,registrado_en"
    ).eq("reunion_id", reunion_id).order("apellidos").execute().data or []


def dni_normalizado(valor):
    return str(valor or "").strip()


def persona_por_dni(filas, dni):
    coincidencias = [f for f in filas if dni_normalizado(f.get("dni")) == dni]
    if not coincidencias:
        return None, []
    # Identidad única por DNI; se conservan cargos distintos en cada base.
    principal = coincidencias[0]
    bases = []
    for f in coincidencias:
        nombre = mapa_bases_global.get(str(f.get("base_id")), "Base desconocida")
        if nombre not in bases:
            bases.append(nombre)
    return principal, bases


# ============================================================
# ENCABEZADO Y ACCESO
# ============================================================
st.title("🗳️ Registro de Bases y Comandos")
st.caption("Gestión de bases, integrantes, reuniones y asistencia general")

if st.session_state.base_id is None and not st.session_state.admin_autenticado:
    st.subheader("Acceso al sistema")
    modo = st.radio("Tipo de acceso", ["Secretario general de base", "Administrador"], horizontal=True)
    if modo == "Secretario general de base":
        with st.form("inicio_sesion_base"):
            usuario_login = st.text_input("Usuario").strip()
            password_login = st.text_input("Contraseña", type="password")
            entrar = st.form_submit_button("Ingresar", use_container_width=True)
        if entrar:
            try:
                resultado = supabase.table("bases_campana").select(
                    "id,nombre_base,provincia,distrito,usuario,password_hash,activo"
                ).eq("usuario", usuario_login).eq("activo", True).limit(1).execute()
                if resultado.data and verificar_password(password_login, resultado.data[0].get("password_hash", "")):
                    cuenta = resultado.data[0]
                    st.session_state.base_id = cuenta["id"]
                    st.session_state.base_nombre = cuenta["nombre_base"]
                    st.session_state.base_provincia = cuenta.get("provincia") or ""
                    st.session_state.base_distrito = cuenta.get("distrito") or ""
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos, o la base está desactivada.")
            except Exception as e:
                error_supabase("No se pudo comprobar el acceso.", e)
    else:
        with st.form("inicio_sesion_admin"):
            usuario_admin = st.text_input("Usuario administrador")
            password_admin = st.text_input("Contraseña de administrador", type="password")
            entrar_admin = st.form_submit_button("Ingresar como administrador", use_container_width=True)
        if entrar_admin and credenciales_admin_validas(usuario_admin.strip(), password_admin):
            st.session_state.admin_autenticado = True
            st.session_state.es_admin = True
            st.rerun()

# Base list for names, used by both admin and attendance module.
try:
    todas_bases_global = cargar_bases()
    mapa_bases_global = {str(b["id"]): b.get("nombre_base", "") for b in todas_bases_global}
except Exception:
    todas_bases_global = []
    mapa_bases_global = {}

# ============================================================
# PANEL ADMINISTRADOR
# ============================================================
if st.session_state.admin_autenticado and st.session_state.es_admin:
    st.success("Sesión de administrador")
    tabs = st.tabs(["Resumen", "Crear base", "Administrar bases", "Todas las personas", "Asistencia general", "Exportar"])

    with tabs[0]:
        try:
            bases = cargar_bases()
            activas = [b for b in bases if b.get("activo", True)]
            filas = cargar_integrantes(solo_bases_activas=True)
            personas_unicas = {dni_normalizado(f.get("dni")) for f in filas if dni_normalizado(f.get("dni"))}
            c1, c2, c3 = st.columns(3)
            c1.metric("Bases activas", len(activas))
            c2.metric("Registros de pertenencia", len(filas))
            c3.metric("Personas únicas en bases activas", len(personas_unicas))
            st.caption("Una persona registrada en varias bases cuenta una sola vez en el total de personas únicas.")
            st.subheader("Bases activas")
            st.dataframe(df_bases(activas), use_container_width=True, hide_index=True)
        except Exception as e:
            error_supabase("No se pudo cargar el resumen.", e)

    with tabs[1]:
        st.subheader("Crear base y cuenta del secretario general")
        with st.form("crear_base_admin"):
            nombre = st.text_input("Nombre de la base o comando")
            provincia = st.selectbox("Provincia", ["Seleccionar provincia"] + PROVINCIAS)
            distritos = DISTRITOS_PUNO.get(provincia, [])
            distrito = st.selectbox("Distrito", ["Seleccionar distrito"] + sorted(distritos), disabled=not distritos)
            usuario = st.text_input("Usuario del secretario general").strip()
            password = st.text_input("Contraseña inicial (8 a 10 caracteres)", type="password")
            confirmar = st.text_input("Confirmar contraseña", type="password")
            acepta = st.checkbox("Confirmo que estoy autorizado para crear esta cuenta.")
            crear = st.form_submit_button("Crear base")
        if crear:
            if not nombre.strip() or provincia not in DISTRITOS_PUNO or distrito not in distritos:
                st.warning("Completa nombre, provincia y distrito.")
            elif not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", usuario):
                st.warning("El usuario debe tener de 3 a 40 caracteres: letras, números, punto, guion o guion bajo.")
            elif not 8 <= len(password) <= 10:
                st.warning("La contraseña debe tener entre 8 y 10 caracteres.")
            elif password != confirmar:
                st.warning("Las contraseñas no coinciden.")
            elif not acepta:
                st.warning("Confirma la autorización antes de crear la cuenta.")
            else:
                try:
                    existe = supabase.table("bases_campana").select("id").eq("usuario", usuario).limit(1).execute().data
                    if existe:
                        st.error("Ese usuario ya está ocupado.")
                    else:
                        supabase.table("bases_campana").insert({
                            "nombre_base": nombre.strip(), "provincia": provincia, "distrito": distrito,
                            "usuario": usuario, "password_hash": crear_hash(password), "activo": True
                        }).execute()
                        st.success("Base creada. Entrega las credenciales al secretario de forma privada.")
                except Exception as e:
                    error_supabase("No se pudo crear la base. Verifica el SQL aplicado.", e)

    with tabs[2]:
        st.subheader("Administrar bases")
        st.caption("Las bases desactivadas desaparecen de las listas operativas, pero sus datos se conservan.")
        try:
            bases = cargar_bases()
            if bases:
                st.dataframe(df_bases(bases), use_container_width=True, hide_index=True)
                opciones = {f'{b.get("nombre_base")} · {b.get("usuario")} · {"Activa" if b.get("activo", True) else "Desactivada"}': b for b in bases}
                seleccion = st.selectbox("Selecciona una base", list(opciones), key="base_admin_sel")
                elegida = opciones[seleccion]
                activa = bool(elegida.get("activo", True))
                st.write(f'**Integrantes asociados:** {len(cargar_integrantes(elegida["id"]))}')
                if activa:
                    confirmar_estado = st.checkbox(f'Confirmo desactivar «{elegida["nombre_base"]}»', key=f'desact_{elegida["id"]}')
                    if st.button("Desactivar base", disabled=not confirmar_estado):
                        supabase.table("bases_campana").update({"activo": False}).eq("id", elegida["id"]).execute()
                        st.success("Base desactivada. Los datos se conservaron.")
                        st.rerun()
                else:
                    confirmar_estado = st.checkbox(f'Confirmo reactivar «{elegida["nombre_base"]}»', key=f'react_{elegida["id"]}')
                    if st.button("Reactivar base", disabled=not confirmar_estado):
                        supabase.table("bases_campana").update({"activo": True}).eq("id", elegida["id"]).execute()
                        st.success("Base reactivada.")
                        st.rerun()
            else:
                st.info("No hay bases registradas.")
        except Exception as e:
            error_supabase("No se pudieron administrar las bases.", e)

    with tabs[3]:
        st.subheader("Personas y pertenencias a bases activas")
        try:
            bases_activas = cargar_bases(solo_activas=True)
            filas = cargar_integrantes(solo_bases_activas=True)
            buscar = st.text_input("Buscar por nombre, DNI o base")
            df = df_integrantes(filas, mapa_bases_global)
            if not df.empty:
                if buscar.strip():
                    mask = df.astype(str).apply(lambda col: col.str.contains(buscar.strip(), case=False, na=False)).any(axis=1)
                    df = df[mask]
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No hay integrantes en bases activas.")
        except Exception as e:
            error_supabase("No se pudo cargar el padrón.", e)

    with tabs[4]:
        st.subheader("Control de asistencia general")
        st.caption("Cada DNI se registra una sola vez por reunión. Si pertenece a varias bases activas, se muestran todas sus pertenencias y se cuenta una sola persona en el total general.")
        try:
            with st.form("crear_reunion_general"):
                fecha_reunion = st.date_input("Fecha de la reunión", value=date.today())
                tema_reunion = st.text_input("Tema o motivo de la reunión")
                crear_reunion = st.form_submit_button("Crear reunión general")
            if crear_reunion:
                if not tema_reunion.strip():
                    st.warning("Escribe el tema o motivo de la reunión.")
                else:
                    supabase.table("reuniones_generales").insert({"fecha": str(fecha_reunion), "tema": tema_reunion.strip()}).execute()
                    st.success("Reunión creada.")
                    st.rerun()
            reuniones = cargar_reuniones_generales()
            if reuniones:
                mapa_reuniones = {f'{r["fecha"]} · {r["tema"]} · ID {r["id"]}': r for r in reuniones}
                reunion_label = st.selectbox("Reunión", list(mapa_reuniones), key="reunion_general_sel")
                reunion = mapa_reuniones[reunion_label]
                presentes = cargar_asistencias_generales(reunion["id"])
                st.metric("Personas únicas presentes", len({a["dni"] for a in presentes}))
                with st.form("registrar_asistencia_general"):
                    dni_buscar = st.text_input("DNI que dicta la persona (8 dígitos)").strip()
                    registrar = st.form_submit_button("Buscar persona")
                if registrar:
                    if not re.fullmatch(r"\d{8}", dni_buscar):
                        st.warning("El DNI debe tener exactamente 8 dígitos.")
                    else:
                        miembros_activos = cargar_integrantes(solo_bases_activas=True)
                        principal, bases_persona = persona_por_dni(miembros_activos, dni_buscar)
                        if principal is None:
                            st.warning("No se encontró ese DNI en ninguna base activa. Pide al secretario que revise su registro.")
                        else:
                            st.session_state["persona_asistencia_encontrada"] = {
                                "dni": dni_buscar, "nombres": principal.get("nombres", ""),
                                "apellidos": principal.get("apellidos", ""),
                                "celular": principal.get("celular", ""), "bases": bases_persona,
                                "reunion_id": reunion["id"]
                            }
                encontrado = st.session_state.get("persona_asistencia_encontrada")
                if encontrado and str(encontrado.get("reunion_id")) == str(reunion["id"]):
                    st.write(f'**Persona:** {encontrado["nombres"]} {encontrado["apellidos"]}')
                    st.write(f'**DNI:** {encontrado["dni"]}')
                    st.write("**Bases activas:** " + (", ".join(encontrado["bases"]) or "Ninguna"))
                    if any(a.get("dni") == encontrado["dni"] for a in presentes):
                        st.info("Esta persona ya figura presente en esta reunión.")
                    elif st.button("Confirmar y registrar asistencia", key=f'confirmar_asistencia_{encontrado["dni"]}_{reunion["id"]}'):
                        try:
                            supabase.table("asistencias_generales").insert({
                                "reunion_id": reunion["id"], "dni": encontrado["dni"],
                                "nombres": encontrado["nombres"], "apellidos": encontrado["apellidos"],
                                "celular": encontrado["celular"], "bases_texto": ", ".join(encontrado["bases"])
                            }).execute()
                            st.session_state.pop("persona_asistencia_encontrada", None)
                            st.success("Asistencia registrada una sola vez.")
                            st.rerun()
                        except Exception as e:
                            error_supabase("No se pudo registrar la asistencia. Puede que ya esté registrada.", e)
                st.divider()
                st.subheader("Lista de asistencia")
                presentes = cargar_asistencias_generales(reunion["id"])
                df_asist = pd.DataFrame([{
                    "Nombres": a.get("nombres", ""), "Apellidos": a.get("apellidos", ""),
                    "DNI": a.get("dni", ""), "Celular": a.get("celular", ""),
                    "Bases correspondientes": a.get("bases_texto", ""),
                    "Hora de registro": str(a.get("registrado_en", ""))
                } for a in presentes])
                if not df_asist.empty:
                    st.dataframe(df_asist, use_container_width=True, hide_index=True)
                    st.download_button("Descargar asistencia (Excel)", data=excel_bytes(df_asist, "Asistencia"), file_name=f'asistencia_general_{reunion["id"]}.xlsx', mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                else:
                    st.info("Todavía no hay asistentes registrados en esta reunión.")
            else:
                st.info("Crea una reunión general para comenzar a pasar lista.")
        except Exception as e:
            error_supabase("No se pudo cargar la asistencia general. Ejecuta primero el SQL de actualización.", e)

    with tabs[5]:
        st.subheader("Exportación consolidada")
        st.warning("El archivo contiene datos personales. Compártelo solo con personas autorizadas.")
        try:
            bases = cargar_bases(solo_activas=True)
            ids_activas = {str(b["id"]) for b in bases}
            miembros = [f for f in cargar_integrantes() if str(f.get("base_id")) in ids_activas]
            mapa = {str(b["id"]): b.get("nombre_base", "") for b in bases}
            # Sheet 1: one row per membership so cargo remains specific to each base.
            df_miembros = df_integrantes(miembros, mapa)
            # Sheet 2: one row per unique DNI, list all active bases.
            por_dni = {}
            for f in miembros:
                dni = dni_normalizado(f.get("dni"))
                llave = dni or f'{nombre_completo(f)}|{f.get("celular", "")}'
                if llave not in por_dni:
                    por_dni[llave] = {"Nombres": f.get("nombres", ""), "Apellidos": f.get("apellidos", ""), "DNI": dni, "Celular": f.get("celular", ""), "Bases": [], "Cargos por base": []}
                bnombre = mapa.get(str(f.get("base_id")), "")
                if bnombre and bnombre not in por_dni[llave]["Bases"]:
                    por_dni[llave]["Bases"].append(bnombre)
                    por_dni[llave]["Cargos por base"].append(f'{bnombre}: {f.get("cargo") or "Sin cargo"}')
            df_personas = pd.DataFrame([{**v, "Bases": "; ".join(v["Bases"]), "Cargos por base": "; ".join(v["Cargos por base"])} for v in por_dni.values()])
            reuniones = cargar_reuniones_generales()
            df_reuniones = pd.DataFrame([{"Fecha": r.get("fecha"), "Tema": r.get("tema"), "ID reunión": r.get("id")} for r in reuniones])
            asistencias = []
            for r in reuniones:
                for a in cargar_asistencias_generales(r["id"]):
                    asistencias.append({"Fecha": r.get("fecha"), "Reunión": r.get("tema"), "DNI": a.get("dni"), "Nombres": a.get("nombres"), "Apellidos": a.get("apellidos"), "Bases correspondientes": a.get("bases_texto"), "Hora de registro": a.get("registrado_en")})
            df_asistencias = pd.DataFrame(asistencias)
            conteo_base = {}
            for a in asistencias:
                for nombre_base in [x.strip() for x in str(a.get("Bases correspondientes", "")).split(",") if x.strip()]:
                    conteo_base[nombre_base] = conteo_base.get(nombre_base, 0) + 1
            df_resumen_asistencia = pd.DataFrame([
                {"Base": nombre_base, "Registros de asistencia reflejados": total}
                for nombre_base, total in sorted(conteo_base.items())
            ])
            st.metric("Personas únicas en bases activas", len(df_personas))
            st.download_button("Descargar TODO en un solo Excel", data=excel_con_hojas({"Bases activas": df_bases(bases), "Personas únicas": df_personas, "Pertenencias y cargos": df_miembros, "Reuniones generales": df_reuniones, "Asistencias": df_asistencias, "Asistencia por base": df_resumen_asistencia}), file_name="registro_general_bases.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            # A consolidated PDF summary; detailed rows remain available in Excel.
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import landscape, A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib.styles import getSampleStyleSheet
            pdf_buffer = io.BytesIO()
            doc = SimpleDocTemplate(pdf_buffer, pagesize=landscape(A4), rightMargin=24, leftMargin=24, topMargin=24, bottomMargin=24)
            styles = getSampleStyleSheet()
            story = [Paragraph("Registro de Bases y Comandos — Informe general", styles["Title"]), Spacer(1, 10), Paragraph(f"Bases activas: {len(bases)} · Personas únicas: {len(df_personas)} · Reuniones generales: {len(reuniones)}", styles["Normal"]), Spacer(1, 12), Paragraph("Padrón de personas y bases", styles["Heading2"])]
            pdf_data = [["Nombres", "Apellidos", "DNI", "Bases activas"]]
            for _, row in df_personas.iterrows():
                pdf_data.append([str(row.get("Nombres", "")), str(row.get("Apellidos", "")), str(row.get("DNI", "")), str(row.get("Bases", ""))])
            if len(pdf_data) == 1:
                pdf_data.append(["Sin registros", "", "", ""])
            tabla = Table(pdf_data, repeatRows=1, colWidths=[120, 120, 75, 360])
            tabla.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.lightgrey), ("GRID", (0,0), (-1,-1), 0.3, colors.grey), ("VALIGN", (0,0), (-1,-1), "TOP"), ("FONTSIZE", (0,0), (-1,-1), 7), ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4)]))
            story.append(tabla)
            doc.build(story)
            st.download_button("Descargar informe general (PDF)", data=pdf_buffer.getvalue(), file_name="registro_general_bases.pdf", mime="application/pdf")
        except Exception as e:
            error_supabase("No se pudieron preparar los archivos. Verifica el SQL y las dependencias.", e)

    if st.button("Cerrar sesión de administrador"):
        limpiar_sesion()
        st.rerun()

# ============================================================
# PANEL DEL SECRETARIO GENERAL DE BASE
# ============================================================
if st.session_state.base_id is not None:
    base_id = st.session_state.base_id
    # Refresh active state to ensure deactivated bases cannot keep operating.
    try:
        verif = supabase.table("bases_campana").select("activo").eq("id", base_id).limit(1).execute().data
        if not verif or not verif[0].get("activo", True):
            st.error("Esta base está desactivada. La sesión se cerró y sus datos se conservaron.")
            limpiar_sesion()
            st.stop()
    except Exception:
        st.error("No se pudo verificar el estado de la base. Por seguridad, vuelve a iniciar sesión.")
        limpiar_sesion()
        st.stop()

    st.success(f'Sesión: {st.session_state.base_nombre} · {st.session_state.base_provincia} / {st.session_state.base_distrito}')
    st.subheader("Integrantes de tu base")
    st.caption("El cargo se guarda tal como lo escribas y es propio de esta base. La misma persona puede pertenecer a otras bases con otro cargo.")
    with st.expander("Agregar integrante", expanded=False):
        with st.form("form_integrante"):
            nombres = st.text_input("Nombres")
            apellidos = st.text_input("Apellidos")
            dni = st.text_input("DNI (8 dígitos)")
            celular = st.text_input("Celular (opcional)")
            cargo_seleccionado = st.selectbox("Cargo o condición", CARGOS)
            cargo_otro = st.text_input("Especifica el cargo o condición", disabled=cargo_seleccionado != "Otro")
            consentimiento = st.checkbox("Confirmo que la persona fue informada sobre el uso de sus datos y autorizó su registro.")
            guardar = st.form_submit_button("Guardar integrante")
        if guardar:
            cargo_final = cargo_otro.strip() if cargo_seleccionado == "Otro" else cargo_seleccionado
            if not nombres.strip() or not apellidos.strip():
                st.warning("Completa nombres y apellidos.")
            elif not re.fullmatch(r"\d{8}", dni.strip()):
                st.warning("El DNI debe contener exactamente 8 dígitos.")
            elif celular.strip() and not re.fullmatch(r"\+?\d{9,15}", celular.strip()):
                st.warning("Si ingresas celular, usa entre 9 y 15 dígitos; puedes incluir + al inicio.")
            elif cargo_seleccionado == "Otro" and not cargo_final:
                st.warning("Especifica el cargo o condición.")
            elif not consentimiento:
                st.warning("Confirma que la persona fue informada y autorizó el registro.")
            else:
                try:
                    existentes = supabase.table("integrantes_base").select("id,dni").eq("base_id", base_id).eq("dni", dni.strip()).limit(1).execute().data
                    if existentes:
                        st.error("Este DNI ya está registrado en esta base. Puedes consultar su registro; no se creará un duplicado.")
                    else:
                        supabase.table("integrantes_base").insert({"base_id": base_id, "nombres": nombres.strip(), "apellidos": apellidos.strip(), "dni": dni.strip(), "celular": celular.strip(), "cargo": cargo_final.strip()}).execute()
                        st.success("Integrante registrado en esta base.")
                        st.rerun()
                except Exception as e:
                    error_supabase("No se pudo guardar el integrante.", e)
    try:
        filas = cargar_integrantes(base_id)
        st.metric("Registros de integrantes de esta base", len(filas))
        busqueda = st.text_input("Buscar por nombre o DNI", key="buscar_base")
        filtrados = [f for f in filas if busqueda.strip().lower() in (nombre_completo(f) + " " + str(f.get("dni", ""))).lower()]
        if filtrados:
            st.dataframe(df_integrantes(filtrados, {str(base_id): st.session_state.base_nombre}), use_container_width=True, hide_index=True)
            st.download_button("Descargar integrantes de mi base (Excel)", data=excel_bytes(df_integrantes(filas, {str(base_id): st.session_state.base_nombre}), "Integrantes"), file_name="integrantes_mi_base.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.info("No hay integrantes que coincidan con la búsqueda.")
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
    st.write("Los nombres, DNI y teléfonos son datos personales. Recógelos solo con una finalidad informada, limita el acceso a usuarios autorizados y comparte los informes solo con personas autorizadas.")
