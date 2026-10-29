import streamlit as st
from supabase import create_client
import hashlib
import secrets
import hmac
import re
import io
import pandas as pd
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

st.set_page_config(
    page_title="Registro de Bases y Comandos",
    page_icon="🗳️",
    layout="wide",
)

st.markdown("""
<style>
header, [data-testid="stHeader"], #MainMenu, .stDeployButton, footer,
[data-testid="stToolbar"], [data-testid="stDecoration"] {
    visibility: hidden !important;
    display: none !important;
}
.block-container {padding-top: 1rem !important;}
</style>
""", unsafe_allow_html=True)

# ============================================================
# CONEXIÓN SUPABASE
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
        "Achaya", "Arapa", "Asillo", "Azángaro", "Caminaca", "Chupa",
        "José Domingo Choquehuanca", "Muñani", "Potoni", "Samán",
        "San Antón", "San José", "San Juan de Salinas",
        "Santiago de Pupuja", "Tirapata"
    ],
    "Carabaya": [
        "Ajoyani", "Ayapata", "Coasa", "Corani", "Crucero", "Ituata",
        "Macusani", "Ollachea", "San Gabán", "Usicayos"
    ],
    "Chucuito": [
        "Desaguadero", "Huacullani", "Juli", "Kelluyo",
        "Pisacoma", "Pomata", "Zepita"
    ],
    "El Collao": ["Capazo", "Conduriri", "Ilave", "Pilcuyo", "Santa Rosa"],
    "Huancané": [
        "Cojata", "Huancané", "Huatasani", "Inchupalla", "Pusi",
        "Rosaspata", "Taraco", "Vilque Chico"
    ],
    "Lampa": [
        "Cabanilla", "Calapuja", "Lampa", "Nicasio", "Ocuviri", "Palca",
        "Paratía", "Pucará", "Santa Lucía", "Vilavila"
    ],
    "Melgar": [
        "Antauta", "Ayaviri", "Cupi", "Llalli", "Macari", "Nuñoa",
        "Orurillo", "Santa Rosa", "Umachiri"
    ],
    "Moho": ["Conima", "Huayrapata", "Moho", "Tilali"],
    "Puno": [
        "Acora", "Amantaní", "Atuncolla", "Capachica", "Chucuito",
        "Coata", "Huata", "Mañazo", "Paucarcolla", "Pichacani",
        "Platería", "Puno", "San Antonio", "Tiquillaca", "Vilque"
    ],
    "San Antonio de Putina": [
        "Ananea", "Pedro Vilca Apaza", "Putina", "Quilcapuncu", "Sina"
    ],
    "San Román": ["Cabana", "Cabanillas", "Caracoto", "Juliaca"],
    "Sandia": [
        "Alto Inambari", "Cuyocuyo", "Limbani", "Patambuco", "Phara",
        "Quiaca", "San Juan del Oro", "San Pedro de Putina Punco",
        "Sandia", "Yanahuaya"
    ],
    "Yunguyo": [
        "Anapia", "Copani", "Cuturapi", "Ollaraya", "Tinicachi",
        "Unicachi", "Yunguyo"
    ],
}
PROVINCIAS = sorted(DISTRITOS_PUNO.keys())

# LISTA DE CARGOS
CARGOS = [
    "SECRETARIO(a) GENERAL",
    "SECRETARIO(a) DE ORGANIZACIÓN Y MOVILIZACION",
    "SECRETARIO(a) DE PRENSA Y PROPAGANDA",
    "SECRETARIO(a) DE LA MUJER",
    "SECRETARIO(a) DE JUVENTUDES",
    "SECRETARIO(a) DE ECONOMIA",
    "SECRETARIO(a) DE SERIGRAFIADO",
    "SECRETARIO(a) DE PERIFONEO Y VOLANTEO",
    "SECRETARIO(a) DE ASESORIA ELECTORAL Y DEFENSA DEL VOTO",
    "SECRETARIO(a) DE INTERVENCION GRAFICA TERRITORIAL",
    "SECRETARIO(A) GENERAL DE BASE",
    "MILITANTE", 
    "Otro",
    
]
META_POR_BASE = 100
FILAS_POR_PAGINA = 1000

# ============================================================
# CONTRASEÑAS Y SESIÓN
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
    claves = (
        "base_id", "base_nombre", "base_provincia", "base_distrito", "base_direccion", "base_cargo",
        "es_admin", "mostrar_registro", "mostrar_integrante",
        "admin_autenticado", "persona_asistencia_encontrada",
    )
    for clave in claves:
        st.session_state.pop(clave, None)
    st.session_state.base_id = None
    st.session_state.base_nombre = ""
    st.session_state.base_provincia = ""
    st.session_state.base_distrito = ""
    st.session_state.base_direccion = ""
    st.session_state.base_cargo = ""
    st.session_state.es_admin = False
    st.session_state.admin_autenticado = False

defaults = {
    "base_id": None,
    "base_nombre": "",
    "base_provincia": "",
    "base_distrito": "",
    "base_direccion": "",
    "base_cargo": "",
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
def ejecutar_todas_las_filas(tabla, columnas, ordenar_por=None, filtros=None):
    filas = []
    inicio = 0
    while True:
        q = supabase.table(tabla).select(columnas)
        for metodo, columna, valor in (filtros or []):
            q = getattr(q, metodo)(columna, valor)
        if ordenar_por:
            columna, descendente = ordenar_por
            q = q.order(columna, desc=descendente)
        pagina = q.range(inicio, inicio + FILAS_POR_PAGINA - 1).execute().data or []
        filas.extend(pagina)
        if len(pagina) < FILAS_POR_PAGINA:
            break
        inicio += FILAS_POR_PAGINA
    return filas

def cargar_bases(solo_activas=False):
    filtros = [("eq", "activo", True)] if solo_activas else []
    return ejecutar_todas_las_filas(
        "bases_campana",
        "id,nombre_base,provincia,distrito,direccion,usuario,cargo,fecha_registro,activo",
        ordenar_por=("nombre_base", False),
        filtros=filtros,
    )

def cargar_integrantes(base_id=None, solo_bases_activas=False):
    filtros = [("eq", "base_id", base_id)] if base_id is not None else []
    filas = ejecutar_todas_las_filas(
        "integrantes_base",
        "id,base_id,nombres,apellidos,dni,celular,cargo,fecha_registro",
        ordenar_por=("apellidos", False),
        filtros=filtros,
    )
    if solo_bases_activas:
        activos = {str(b["id"]) for b in cargar_bases(solo_activas=True)}
        filas = [f for f in filas if str(f.get("base_id")) in activos]
    return filas

def nombre_completo(fila):
    return f'{fila.get("nombres", "")} {fila.get("apellidos", "")}'.strip()

def dni_normalizado(valor):
    return str(valor or "").strip()

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
        "Base": b.get("nombre_base", ""),
        "Cargo": b.get("cargo", ""),
        "Dirección": b.get("direccion", ""),
        "Provincia": b.get("provincia", ""),
        "Distrito": b.get("distrito", ""),
        "Usuario": b.get("usuario", ""),
        "Estado": "Activa" if b.get("activo", True) else "Desactivada",
        "Fecha de registro": str(b.get("fecha_registro", ""))[:10],
    } for b in filas])

def df_integrantes(filas, mapa_bases=None):
    mapa_bases = mapa_bases or {}
    return pd.DataFrame([{
        "Base": mapa_bases.get(str(f.get("base_id")), str(f.get("base_id", ""))),
        "Nombres": f.get("nombres", ""),
        "Apellidos": f.get("apellidos", ""),
        "DNI": f.get("dni", ""),
        "Celular": f.get("celular", ""),
        "Cargo / condición en esta base": f.get("cargo") or "",
        "Fecha de registro": str(f.get("fecha_registro", ""))[:10],
    } for f in filas])

def error_supabase(mensaje, error=None):
    st.error(mensaje)
    st.caption(
        "Comprueba que ejecutaste el SQL de actualización y que los Secrets "
        "de Supabase son correctos."
    )
    if error:
        st.caption(str(error))

def cargar_reuniones_generales():
    return ejecutar_todas_las_filas(
        "reuniones_generales", "id,fecha,tema,creada_en",
        ordenar_por=("fecha", True)
    )

def cargar_asistencias_generales(reunion_id):
    return ejecutar_todas_las_filas(
        "asistencias_generales",
        "id,reunion_id,dni,nombres,apellidos,celular,bases_texto,registrado_en",
        ordenar_por=("apellidos", False),
        filtros=[("eq", "reunion_id", reunion_id)],
    )

def persona_por_dni(filas, dni, mapa_bases):
    coincidencias = [f for f in filas if dni_normalizado(f.get("dni")) == dni]
    if not coincidencias:
        return None, []
    principal = coincidencias[0]
    bases = []
    for f in coincidencias:
        nombre = mapa_bases.get(str(f.get("base_id")), "Base desconocida")
        if nombre not in bases:
            bases.append(nombre)
    return principal, bases

def fecha_hora_peru(valor):
    if not valor:
        return "", ""
    try:
        texto = str(valor).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(texto)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(ZoneInfo("America/Lima"))
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        texto = str(valor)
        return texto[:10], texto[11:19] if len(texto) >= 19 else ""

# ============================================================
# ENCABEZADO Y ACCESO
# ============================================================
st.title("🗳️ Registro de Bases y Comandos")
st.caption("Gestión de bases, integrantes, reuniones y asistencia general")

if st.session_state.base_id is None and not st.session_state.admin_autenticado:
    st.subheader("Acceso al sistema")
    modo = st.radio(
        "Tipo de acceso",
        ["Secretario general de base", "Administrador"],
        horizontal=True,
    )
    if modo == "Secretario general de base":
        with st.form("inicio_sesion_base"):
            usuario_login = st.text_input("Usuario").strip()
            password_login = st.text_input("Contraseña", type="password")
            entrar = st.form_submit_button("Ingresar", use_container_width=True)
        if entrar:
            try:
                resultado = supabase.table("bases_campana").select(
                    "id,nombre_base,provincia,distrito,direccion,usuario,cargo,password_hash,activo"
                ).eq("usuario", usuario_login).eq("activo", True).limit(1).execute()
                if resultado.data and verificar_password(
                    password_login, resultado.data[0].get("password_hash", "")
                ):
                    cuenta = resultado.data[0]
                    st.session_state.base_id = cuenta["id"]
                    st.session_state.base_nombre = cuenta["nombre_base"]
                    st.session_state.base_provincia = cuenta.get("provincia") or ""
                    st.session_state.base_distrito = cuenta.get("distrito") or ""
                    st.session_state.base_direccion = cuenta.get("direccion") or ""
                    st.session_state.base_cargo = cuenta.get("cargo") or ""
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos, o la base está desactivada.")
            except Exception as e:
                error_supabase("No se pudo comprobar el acceso.", e)
    else:
        with st.form("inicio_sesion_admin"):
            usuario_admin = st.text_input("Usuario administrador")
            password_admin = st.text_input("Contraseña de administrador", type="password")
            entrar_admin = st.form_submit_button(
                "Ingresar como administrador", use_container_width=True
            )
        if entrar_admin and credenciales_admin_validas(usuario_admin.strip(), password_admin):
            st.session_state.admin_autenticado = True
            st.session_state.es_admin = True
            st.rerun()

try:
    todas_bases_global = cargar_bases()
    mapa_bases_global = {
        str(b["id"]): b.get("nombre_base", "") for b in todas_bases_global
    }
except Exception:
    todas_bases_global = []
    mapa_bases_global = {}

# ============================================================
# PANEL ADMINISTRADOR
# ============================================================
if st.session_state.admin_autenticado and st.session_state.es_admin:
    st.success("Sesión de administrador")
    tabs = st.tabs([
        "Resumen", "Crear base", "Administrar bases", "Todas las personas",
        "Avance de militantes", "Asistencia general", "Exportar"
    ])

    with tabs[0]:
        try:
            bases = cargar_bases()
            activas = [b for b in bases if b.get("activo", True)]
            filas = cargar_integrantes(solo_bases_activas=True)
            personas_unicas = {
                dni_normalizado(f.get("dni")) for f in filas
                if dni_normalizado(f.get("dni"))
            }
            c1, c2, c3 = st.columns(3)
            c1.metric("Bases activas", len(activas))
            c2.metric("Registros de pertenencia", len(filas))
            c3.metric("Personas únicas en bases activas", len(personas_unicas))
            st.caption(
                "Una persona registrada en varias bases cuenta una sola vez "
                "en el total de personas únicas."
            )
            st.subheader("Bases activas")
            st.dataframe(df_bases(activas), use_container_width=True, hide_index=True)
        except Exception as e:
            error_supabase("No se pudo cargar el resumen.", e)

    with tabs[1]:
        st.subheader("Crear base y cuenta de usuario")
        st.caption("Selecciona primero la provincia; la lista de distritos se actualizará automáticamente.")
        nombre = st.text_input("Nombre de la base o comando", key="crear_nombre_base")
        
        # NUEVO CAMPO: SELECCIONAR EL CARGO DEL USUARIO A CREAR
        cargo_cuenta = st.selectbox("Cargo de la cuenta a crear", CARGOS, key="crear_cargo_usuario")
        
        provincia = st.selectbox(
            "Provincia", ["Seleccionar provincia"] + PROVINCIAS,
            key="crear_provincia_base"
        )
        distritos = DISTRITOS_PUNO.get(provincia, [])
        if distritos:
            distrito = st.selectbox(
                "Distrito", ["Seleccionar distrito"] + sorted(distritos),
                key=f"crear_distrito_{provincia}"
            )
        else:
            distrito = "Seleccionar distrito"
            st.selectbox(
                "Distrito", ["Selecciona primero una provincia"],
                disabled=True, key="crear_distrito_vacio"
            )
        # CAMPO DIRECCIÓN
        direccion = st.text_input("Dirección de la base", key="crear_direccion_base").strip()
        
        usuario = st.text_input("Usuario del secretario general", key="crear_usuario_base").strip()
        mostrar_clave_nueva = st.checkbox("👁️ Mostrar contraseña inicial", key="mostrar_clave_inicial")
        
        password = st.text_input(
            "Contraseña inicial (8 a 12 caracteres)",
            type="default" if mostrar_clave_nueva else "password",
            key="crear_password_base"
        )
        confirmar = st.text_input(
            "Confirmar contraseña",
            type="default" if mostrar_clave_nueva else "password",
            key="crear_confirmar_password_base"
        )
        acepta = st.checkbox(
            "Confirmo que estoy autorizado para crear esta cuenta.",
            key="crear_acepta_base"
        )
        crear = st.button("Crear base", key="crear_base_admin_btn")
        if crear:
            if not nombre.strip() or provincia not in DISTRITOS_PUNO or distrito not in distritos or not direccion:
                st.warning("Completa nombre, provincia, distrito y dirección.")
            elif not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", usuario):
                st.warning("El usuario debe tener de 3 a 40 caracteres: letras, números, punto, guion o guion bajo.")
            elif not 8 <= len(password) <= 12:
                st.warning("La contraseña debe tener entre 8 y 12 caracteres.")
            elif password != confirmar:
                st.warning("Las contraseñas no coinciden.")
            elif not acepta:
                st.warning("Confirma la autorización antes de crear la cuenta.")
            else:
                try:
                    existe = supabase.table("bases_campana").select("id").eq(
                        "usuario", usuario
                    ).limit(1).execute().data
                    if existe:
                        st.error("Ese usuario ya está ocupado.")
                    else:
                        supabase.table("bases_campana").insert({
                            "nombre_base": nombre.strip(),
                            "provincia": provincia,
                            "distrito": distrito,
                            "direccion": direccion,
                            "usuario": usuario,
                            "cargo": cargo_cuenta, # SE GUARDA EL CARGO
                            "password_hash": crear_hash(password),
                            "activo": True,
                        }).execute()
                        st.success("Base y cuenta creada correctamente. Entrega las credenciales de forma privada.")
                except Exception as e:
                    error_supabase("No se pudo crear la base. Verifica el SQL aplicado.", e)

    with tabs[2]:
        st.subheader("Administrar bases")
        st.caption("Las bases desactivadas desaparecen de las listas operativas, pero sus datos se conservan.")
        try:
            bases = cargar_bases()
            if bases:
                buscar_base_admin = st.text_input(
                    "Buscar base por nombre, usuario, provincia o distrito",
                    key="buscar_base_admin"
                )
                df_admin_bases = df_bases(bases)
                if buscar_base_admin.strip():
                    mask = df_admin_bases.astype(str).apply(
                        lambda col: col.str.contains(
                            buscar_base_admin.strip(), case=False, na=False
                        )
                    ).any(axis=1)
                    df_admin_bases = df_admin_bases[mask]
                st.dataframe(df_admin_bases, use_container_width=True, hide_index=True)

                opciones = {
                    f'{b.get("nombre_base")} · {b.get("usuario")} · '
                    f'{"Activa" if b.get("activo", True) else "Desactivada"}': b
                    for b in bases
                }
                seleccion = st.selectbox("Selecciona una base", list(opciones), key="base_admin_sel")
                elegida = opciones[seleccion]
                activa = bool(elegida.get("activo", True))
                
                integrantes_base_actual = cargar_integrantes(elegida["id"])
                st.write(f'**Integrantes asociados:** {len(integrantes_base_actual)}')

                # --- CORREGIR DATOS DE UN INTEGRANTE (ADMIN) ---
                with st.expander("✏️ Corregir datos de un integrante de esta base", expanded=False):
                    if integrantes_base_actual:
                        opciones_editar = {
                            f"{f.get('apellidos','')}, {f.get('nombres','')} - DNI: {f.get('dni','')}": f
                            for f in integrantes_base_actual
                        }
                        seleccion_editar = st.selectbox(
                            "Selecciona el integrante a corregir",
                            list(opciones_editar.keys()),
                            key=f"select_editar_integrante_admin_{elegida['id']}"
                        )
                        
                        if seleccion_editar:
                            integrante_sel = opciones_editar[seleccion_editar]
                            
                            edit_nombres = st.text_input("Nombres", value=integrante_sel.get("nombres", ""), key=f"edit_nom_{integrante_sel['id']}")
                            edit_apellidos = st.text_input("Apellidos", value=integrante_sel.get("apellidos", ""), key=f"edit_ape_{integrante_sel['id']}")
                            edit_dni = st.text_input("DNI (8 dígitos)", value=integrante_sel.get("dni", ""), key=f"edit_dni_{integrante_sel['id']}")
                            edit_celular = st.text_input("Celular", value=integrante_sel.get("celular", "") or "", key=f"edit_cel_{integrante_sel['id']}")
                            
                            cargo_actual = integrante_sel.get("cargo", "")
                            if cargo_actual in CARGOS:
                                idx_cargo = CARGOS.index(cargo_actual)
                                edit_cargo_sel = st.selectbox("Cargo o condición", CARGOS, index=idx_cargo, key=f"edit_cargo_sel_{integrante_sel['id']}")
                                edit_cargo_otro = st.text_input("Especifica el cargo", value="", disabled=True, key=f"edit_cargo_otro_{integrante_sel['id']}")
                            else:
                                idx_cargo = CARGOS.index("Otro")
                                edit_cargo_sel = st.selectbox("Cargo o condición", CARGOS, index=idx_cargo, key=f"edit_cargo_sel_{integrante_sel['id']}")
                                edit_cargo_otro = st.text_input("Especifica el cargo", value=cargo_actual, key=f"edit_cargo_otro_{integrante_sel['id']}")
                            
                            if st.button("Guardar correcciones del integrante", type="primary", key=f"guardar_edit_int_admin_{integrante_sel['id']}"):
                                cargo_final_edit = edit_cargo_otro.strip() if edit_cargo_sel == "Otro" else edit_cargo_sel
                                
                                if not edit_nombres.strip() or not edit_apellidos.strip():
                                    st.warning("Completa nombres y apellidos.")
                                elif not re.fullmatch(r"\d{8}", edit_dni.strip()):
                                    st.warning("El DNI debe contener exactamente 8 dígitos.")
                                elif edit_celular.strip() and not re.fullmatch(r"\+?\d{9,15}", edit_celular.strip()):
                                    st.warning("Si ingresas celular, usa entre 9 y 15 dígitos; puedes incluir + al inicio.")
                                elif edit_cargo_sel == "Otro" and not cargo_final_edit:
                                    st.warning("Especifica el cargo o condición.")
                                else:
                                    existentes = supabase.table("integrantes_base").select("id").eq("base_id", elegida["id"]).eq("dni", edit_dni.strip()).neq("id", integrante_sel["id"]).limit(1).execute().data
                                    if existentes:
                                        st.error("Ese DNI ya está registrado por otra persona en esta base.")
                                    else:
                                        try:
                                            supabase.table("integrantes_base").update({
                                                "nombres": edit_nombres.strip(),
                                                "apellidos": edit_apellidos.strip(),
                                                "dni": edit_dni.strip(),
                                                "celular": edit_celular.strip(),
                                                "cargo": cargo_final_edit,
                                            }).eq("id", integrante_sel["id"]).execute()
                                            st.success("Datos del integrante actualizados correctamente.")
                                            st.rerun()
                                        except Exception as e:
                                            error_supabase("No se pudieron actualizar los datos del integrante.", e)
                    else:
                        st.info("Esta base no tiene integrantes registrados para editar.")

                # --- EDITAR DATOS DE LA BASE (ADMIN) ---
                with st.expander("✏️ Editar datos de esta base", expanded=False):
                    edit_nombre = st.text_input("Nombre de la base", value=elegida.get("nombre_base", ""), key=f"edit_nombre_{elegida['id']}")
                    
                    # NUEVO: Editar el cargo de la cuenta principal de la base
                    cargo_actual_base = elegida.get("cargo", "")
                    idx_cargo_base = CARGOS.index(cargo_actual_base) if cargo_actual_base in CARGOS else 0
                    edit_cargo_base = st.selectbox("Cargo del usuario de esta base", CARGOS, index=idx_cargo_base, key=f"edit_cargo_base_{elegida['id']}")
                    
                    prov_actual = elegida.get("provincia", "")
                    prov_index = PROVINCIAS.index(prov_actual) + 1 if prov_actual in PROVINCIAS else 0
                    edit_provincia = st.selectbox(
                        "Provincia", ["Seleccionar provincia"] + PROVINCIAS, index=prov_index, key=f"edit_prov_{elegida['id']}"
                    )
                    
                    distritos_edit = DISTRITOS_PUNO.get(edit_provincia, [])
                    dist_actual = elegida.get("distrito", "")
                    dist_index = sorted(distritos_edit).index(dist_actual) + 1 if dist_actual in distritos_edit else 0
                    
                    if distritos_edit:
                        edit_distrito = st.selectbox(
                            "Distrito", ["Seleccionar distrito"] + sorted(distritos_edit), index=dist_index, key=f"edit_dist_{elegida['id']}"
                        )
                    else:
                        edit_distrito = st.selectbox(
                            "Distrito", ["Selecciona primero una provincia"], disabled=True, key=f"edit_dist_vacio_{elegida['id']}"
                        )
                        
                    edit_direccion = st.text_input("Dirección", value=elegida.get("direccion") or "", key=f"edit_dir_{elegida['id']}")
                    
                    if st.button("Guardar cambios", type="primary", key=f"guardar_edit_{elegida['id']}"):
                        if not edit_nombre.strip() or edit_provincia not in DISTRITOS_PUNO or edit_distrito not in distritos_edit:
                            st.warning("Completa nombre, provincia y distrito correctamente.")
                        else:
                            try:
                                supabase.table("bases_campana").update({
                                    "nombre_base": edit_nombre.strip(),
                                    "cargo": edit_cargo_base,
                                    "provincia": edit_provincia,
                                    "distrito": edit_distrito,
                                    "direccion": edit_direccion.strip()
                                }).eq("id", elegida["id"]).execute()
                                st.success("Datos de la base actualizados correctamente.")
                                st.rerun()
                            except Exception as e:
                                error_supabase("No se pudieron actualizar los datos.", e)

                st.markdown("#### Usuario y recuperación de contraseña")
                st.write(f'**Usuario:** `{elegida.get("usuario", "")}`')
                st.caption("La contraseña anterior no se puede mostrar porque solo se guarda su hash. Si se perdió, genera una contraseña temporal.")
                clave_state = f"clave_temporal_{elegida['id']}"
                ver_state = f"ver_clave_temporal_{elegida['id']}"
                confirmar_reset = st.checkbox(
                    f'Confirmo restablecer la contraseña de «{elegida["nombre_base"]}»',
                    key=f"confirmar_reset_{elegida['id']}"
                )
                if st.button(
                    "Generar nueva contraseña temporal",
                    key=f"reset_password_{elegida['id']}",
                    disabled=not confirmar_reset
                ):
                    nueva_clave = secrets.token_urlsafe(9)
                    try:
                        supabase.table("bases_campana").update(
                            {"password_hash": crear_hash(nueva_clave)}
                        ).eq("id", elegida["id"]).execute()
                        st.session_state[clave_state] = nueva_clave
                        st.session_state[ver_state] = False
                        st.success("Contraseña restablecida. Copia la nueva clave y entrégala al secretario de forma privada.")
                    except Exception as e:
                        error_supabase("No se pudo restablecer la contraseña.", e)
                if clave_state in st.session_state:
                    st.checkbox("👁️ Mostrar contraseña temporal", key=ver_state)
                    st.code(
                        st.session_state[clave_state]
                        if st.session_state.get(ver_state, False)
                        else "••••••••••••"
                    )
                    if st.button(
                        "Ocultar y retirar clave de esta pantalla",
                        key=f"ocultar_clave_{elegida['id']}"
                    ):
                        st.session_state.pop(clave_state, None)
                        st.session_state.pop(ver_state, None)
                        st.rerun()
                if activa:
                    confirmar_estado = st.checkbox(
                        f'Confirmo desactivar «{elegida["nombre_base"]}»',
                        key=f'desact_{elegida["id"]}'
                    )
                    if st.button("Desactivar base", disabled=not confirmar_estado, key=f"desactivar_{elegida['id']}"):
                        supabase.table("bases_campana").update(
                            {"activo": False}
                        ).eq("id", elegida["id"]).execute()
                        st.success("Base desactivada. Los datos se conservaron.")
                        st.rerun()
                else:
                    confirmar_estado = st.checkbox(
                        f'Confirmo reactivar «{elegida["nombre_base"]}»',
                        key=f'react_{elegida["id"]}'
                    )
                    if st.button("Reactivar base", disabled=not confirmar_estado, key=f"reactivar_{elegida['id']}"):
                        supabase.table("bases_campana").update(
                            {"activo": True}
                        ).eq("id", elegida["id"]).execute()
                        st.success("Base reactivada.")
                        st.rerun()

                # --- ZONA DE PELIGRO: ELIMINAR BASE ---
                st.divider()
                st.markdown("#### 🚨 Zona de peligro")
                st.caption("Eliminar una base borrará **todos** sus integrantes asociados de forma permanente. Esta acción no se puede deshacer.")
                
                confirmar_check = st.checkbox(
                    f'Confirmo que quiero ELIMINAR permanentemente la base «{elegida["nombre_base"]}»',
                    key=f'eliminar_check_{elegida["id"]}'
                )
                
                confirmar_final_key = f"confirmar_eliminar_final_{elegida['id']}"
                
                if st.button("Solicitar eliminación de base", type="primary", disabled=not confirmar_check, key=f"eliminar_btn_{elegida['id']}"):
                    st.session_state[confirmar_final_key] = True
                
                if st.session_state.get(confirmar_final_key, False):
                    st.error(f"⚠️ ¿REALMENTE DESEAS ELIMINAR LA BASE «{elegida['nombre_base']}» Y TODOS SUS INTEGRANTES? ESTA ACCIÓN ES IRREVERSIBLE.")
                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        if st.button("SÍ, ELIMINAR DEFINITIVAMENTE", type="primary", key=f"si_eliminar_{elegida['id']}"):
                            try:
                                supabase.table("integrantes_base").delete().eq("base_id", elegida["id"]).execute()
                                supabase.table("bases_campana").delete().eq("id", elegida["id"]).execute()
                                st.session_state[confirmar_final_key] = False
                                st.success(f"La base «{elegida['nombre_base']}» y todos sus integrantes han sido eliminados.")
                                st.rerun()
                            except Exception as e:
                                error_supabase("No se pudo eliminar la base. Verifica si tiene otros datos vinculados.", e)
                    with col_btn2:
                        if st.button("Cancelar", key=f"cancelar_eliminar_{elegida['id']}"):
                            st.session_state[confirmar_final_key] = False
                            st.rerun()

            else:
                st.info("No hay bases registradas.")
        except Exception as e:
            error_supabase("No se pudieron administrar las bases.", e)

    with tabs[3]:
        st.subheader("Personas y pertenencias a bases activas")
        try:
            filas = cargar_integrantes(solo_bases_activas=True)
            buscar = st.text_input("Buscar por nombre, DNI o base", key="buscar_todas_personas")
            df = df_integrantes(filas, mapa_bases_global)
            if not df.empty:
                if buscar.strip():
                    mask = df.astype(str).apply(
                        lambda col: col.str.contains(buscar.strip(), case=False, na=False)
                    ).any(axis=1)
                    df = df[mask]
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No hay integrantes en bases activas.")
        except Exception as e:
            error_supabase("No se pudo cargar el padrón.", e)

    with tabs[4]:
        st.subheader("Avance de integración de militantes")
        st.caption("Meta establecida: 100 integrantes registrados por base activa.")
        try:
            bases_activas = cargar_bases(solo_activas=True)
            todos_integrantes = cargar_integrantes(solo_bases_activas=True)
            dnis_por_base = {}
            registros_por_base = {}
            for persona in todos_integrantes:
                bid = str(persona.get("base_id"))
                dni = dni_normalizado(persona.get("dni"))
                registros_por_base[bid] = registros_por_base.get(bid, 0) + 1
                if dni:
                    dnis_por_base.setdefault(bid, set()).add(dni)
                else:
                    dnis_por_base.setdefault(bid, set()).add(
                        f"sin-dni-registro-{persona.get('id')}"
                    )

            datos_avance = []
            for base in bases_activas:
                bid = str(base["id"])
                cantidad = len(dnis_por_base.get(bid, set()))
                faltantes = max(0, META_POR_BASE - cantidad)
                porcentaje = cantidad / META_POR_BASE * 100
                datos_avance.append({
                    "Base": base.get("nombre_base", ""),
                    "Provincia": base.get("provincia", ""),
                    "Distrito": base.get("distrito", ""),
                    "Militantes registrados": cantidad,
                    "Meta": META_POR_BASE,
                    "Faltantes": faltantes,
                    "Avance (%)": round(porcentaje, 1),
                })

            df_avance = pd.DataFrame(datos_avance)
            if not df_avance.empty:
                total_bases = len(df_avance)
                total_registros = int(df_avance["Militantes registrados"].sum())
                meta_total = total_bases * META_POR_BASE
                faltantes_total = int(df_avance["Faltantes"].sum())
                avance_general = total_registros / meta_total * 100 if meta_total else 0
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Bases activas", total_bases)
                c2.metric("Integrantes registrados", total_registros)
                c3.metric("Meta total", meta_total)
                c4.metric("Avance general", f"{avance_general:.1f}%")
                st.progress(min(max(avance_general / 100, 0), 1))
                st.caption(
                    f"Faltan {faltantes_total} registros para completar la meta acumulada. "
                    "El avance por base se limita visualmente al 100 %, aunque la tabla muestra "
                    "el porcentaje real si una base supera la meta."
                )
                st.markdown("#### Detalle por base")
                df_ordenado = df_avance.sort_values(
                    ["Avance (%)", "Base"], ascending=[False, True]
                )
                st.dataframe(df_ordenado, use_container_width=True, hide_index=True)
                st.markdown("#### Comparación visual")
                df_grafico = df_ordenado.set_index("Base")[["Militantes registrados"]]
                st.bar_chart(df_grafico)
                st.download_button(
                    "Descargar avance por base (Excel)",
                    data=excel_bytes(df_ordenado, "Avance por base"),
                    file_name="avance_militantes_por_base.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                st.info("No hay bases activas para calcular el avance.")
        except Exception as e:
            error_supabase("No se pudo calcular el avance de militantes.", e)

    with tabs[5]:
        st.subheader("Control de asistencia general")
        st.caption(
            "Cada DNI se registra una sola vez por reunión. La lista de asistencia "
            "mostrará únicamente la fecha y la hora del registro."
        )
        try:
            with st.form("crear_reunion_general"):
                fecha_reunion = st.date_input("Fecha de la reunión", value=date.today())
                tema_reunion = st.text_input("Tema o motivo de la reunión")
                crear_reunion = st.form_submit_button("Crear reunión general")
            if crear_reunion:
                if not tema_reunion.strip():
                    st.warning("Escribe el tema o motivo de la reunión.")
                else:
                    supabase.table("reuniones_generales").insert({
                        "fecha": str(fecha_reunion),
                        "tema": tema_reunion.strip()
                    }).execute()
                    st.success("Reunión creada.")
                    st.rerun()

            reuniones = cargar_reuniones_generales()
            if reuniones:
                mapa_reuniones = {
                    f'{r["fecha"]} · {r["tema"]} · ID {r["id"]}': r for r in reuniones
                }
                reunion_label = st.selectbox(
                    "Reunión", list(mapa_reuniones), key="reunion_general_sel"
                )
                reunion = mapa_reuniones[reunion_label]
                presentes = cargar_asistencias_generales(reunion["id"])
                st.metric(
                    "Personas únicas presentes",
                    len({dni_normalizado(a.get("dni")) for a in presentes if dni_normalizado(a.get("dni"))})
                )
                with st.form("registrar_asistencia_general"):
                    dni_buscar = st.text_input("DNI que dicta la persona (8 dígitos)").strip()
                    registrar = st.form_submit_button("Buscar persona")
                if registrar:
                    if not re.fullmatch(r"\d{8}", dni_buscar):
                        st.warning("El DNI debe tener exactamente 8 dígitos.")
                    else:
                        miembros_activos = cargar_integrantes(solo_bases_activas=True)
                        principal, bases_persona = persona_por_dni(
                            miembros_activos, dni_buscar, mapa_bases_global
                        )
                        if principal is None:
                            st.warning("No se encontró ese DNI en ninguna base activa. Pide al secretario que revise su registro.")
                        else:
                            st.session_state["persona_asistencia_encontrada"] = {
                                "dni": dni_buscar,
                                "nombres": principal.get("nombres", ""),
                                "apellidos": principal.get("apellidos", ""),
                                "celular": principal.get("celular", ""),
                                "bases": bases_persona,
                                "reunion_id": reunion["id"],
                            }
                encontrado = st.session_state.get("persona_asistencia_encontrada")
                if encontrado and str(encontrado.get("reunion_id")) == str(reunion["id"]):
                    st.write(f'**Persona:** {encontrado["nombres"]} {encontrado["apellidos"]}')
                    st.write(f'**DNI:** {encontrado["dni"]}')
                    st.write("**Bases activas:** " + (", ".join(encontrado["bases"]) or "Ninguna"))
                    if any(dni_normalizado(a.get("dni")) == encontrado["dni"] for a in presentes):
                        st.info("Esta persona ya figura presente en esta reunión.")
                    elif st.button(
                        "Confirmar y registrar asistencia",
                        key=f'confirmar_asistencia_{encontrado["dni"]}_{reunion["id"]}'
                    ):
                        try:
                            supabase.table("asistencias_generales").insert({
                                "reunion_id": reunion["id"],
                                "dni": encontrado["dni"],
                                "nombres": encontrado["nombres"],
                                "apellidos": encontrado["apellidos"],
                                "celular": encontrado["celular"],
                                "bases_texto": ", ".join(encontrado["bases"]),
                            }).execute()
                            st.session_state.pop("persona_asistencia_encontrada", None)
                            st.success("Asistencia registrada una sola vez.")
                            st.rerun()
                        except Exception as e:
                            error_supabase("No se pudo registrar la asistencia. Puede que ya esté registrada.", e)

                st.divider()
                st.subheader("Lista de asistencia")
                presentes = cargar_asistencias_generales(reunion["id"])
                filas_fecha_hora = []
                for asistencia in presentes:
                    fecha_reg, hora_reg = fecha_hora_peru(asistencia.get("registrado_en"))
                    filas_fecha_hora.append({"Fecha": fecha_reg, "Hora": hora_reg})
                df_asist = pd.DataFrame(filas_fecha_hora, columns=["Fecha", "Hora"])
                if not df_asist.empty:
                    st.dataframe(df_asist, use_container_width=True, hide_index=True)
                    st.download_button(
                        "Descargar asistencia (Excel: fecha y hora)",
                        data=excel_bytes(df_asist, "Asistencia"),
                        file_name=f'asistencia_general_{reunion["id"]}.xlsx',
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                else:
                    st.info("Todavía no hay asistentes registrados en esta reunión.")
            else:
                st.info("Crea una reunión general para comenzar a pasar lista.")
        except Exception as e:
            error_supabase("No se pudo cargar la asistencia general. Ejecuta primero el SQL de actualización.", e)

    with tabs[6]:
        st.subheader("Exportación consolidada")
        st.warning("El archivo contiene datos personales. Compártelo solo con personas autorizadas.")
        try:
            bases = cargar_bases(solo_activas=True)
            ids_activas = {str(b["id"]) for b in bases}
            miembros = [
                f for f in cargar_integrantes()
                if str(f.get("base_id")) in ids_activas
            ]
            mapa = {str(b["id"]): b.get("nombre_base", "") for b in bases}
            df_miembros = df_integrantes(miembros, mapa)

            por_dni = {}
            for f in miembros:
                dni = dni_normalizado(f.get("dni"))
                llave = dni or f'{nombre_completo(f)}|{f.get("celular", "")}'
                if llave not in por_dni:
                    por_dni[llave] = {
                        "Nombres": f.get("nombres", ""),
                        "Apellidos": f.get("apellidos", ""),
                        "DNI": dni,
                        "Celular": f.get("celular", ""),
                        "Bases": [],
                        "Cargos por base": [],
                    }
                bnombre = mapa.get(str(f.get("base_id")), "")
                if bnombre and bnombre not in por_dni[llave]["Bases"]:
                    por_dni[llave]["Bases"].append(bnombre)
                    por_dni[llave]["Cargos por base"].append(
                        f'{bnombre}: {f.get("cargo") or "Sin cargo"}'
                    )
            df_personas = pd.DataFrame([
                {
                    **v,
                    "Bases": "; ".join(v["Bases"]),
                    "Cargos por base": "; ".join(v["Cargos por base"]),
                }
                for v in por_dni.values()
            ])
            reuniones = cargar_reuniones_generales()
            df_reuniones = pd.DataFrame([
                {"Fecha": r.get("fecha"), "Tema": r.get("tema"), "ID reunión": r.get("id")}
                for r in reuniones
            ])
            asistencias = []
            for r in reuniones:
                for a in cargar_asistencias_generales(r["id"]):
                    fecha_reg, hora_reg = fecha_hora_peru(a.get("registrado_en"))
                    asistencias.append({
                        "Fecha de reunión": r.get("fecha"),
                        "Reunión": r.get("tema"),
                        "Fecha de registro": fecha_reg,
                        "Hora de registro": hora_reg,
                    })
            df_asistencias = pd.DataFrame(
                asistencias,
                columns=["Fecha de reunión", "Reunión", "Fecha de registro", "Hora de registro"]
            )
            conteo_base = {}
            for f in miembros:
                nombre_base = mapa.get(str(f.get("base_id")), "")
                if nombre_base:
                    conteo_base[nombre_base] = conteo_base.get(nombre_base, 0) + 1
            df_resumen_asistencia = pd.DataFrame([
                {"Base": nombre_base, "Integrantes registrados": total}
                for nombre_base, total in sorted(conteo_base.items())
            ])
            st.metric("Personas únicas en bases activas", len(df_personas))
            st.download_button(
                "Descargar TODO en un solo Excel",
                data=excel_con_hojas({
                    "Bases activas": df_bases(bases),
                    "Personas únicas": df_personas,
                    "Pertenencias y cargos": df_miembros,
                    "Reuniones generales": df_reuniones,
                    "Asistencias": df_asistencias,
                    "Integrantes por base": df_resumen_asistencia,
                }),
                file_name="registro_general_bases.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            from reportlab.lib import colors
            from reportlab.lib.pagesizes import landscape, A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib.styles import getSampleStyleSheet
            pdf_buffer = io.BytesIO()
            doc = SimpleDocTemplate(
                pdf_buffer, pagesize=landscape(A4), rightMargin=24,
                leftMargin=24, topMargin=24, bottomMargin=24
            )
            styles = getSampleStyleSheet()
            story = [
                Paragraph("Registro de Bases y Comandos — Informe general", styles["Title"]),
                Spacer(1, 10),
                Paragraph(
                    f"Bases activas: {len(bases)} · Personas únicas: {len(df_personas)} · "
                    f"Reuniones generales: {len(reuniones)}",
                    styles["Normal"]
                ),
                Spacer(1, 12),
                Paragraph("Padrón de personas y bases", styles["Heading2"]),
            ]
            pdf_data = [["Nombres", "Apellidos", "DNI", "Bases activas"]]
            for _, row in df_personas.iterrows():
                pdf_data.append([
                    str(row.get("Nombres", "")),
                    str(row.get("Apellidos", "")),
                    str(row.get("DNI", "")),
                    str(row.get("Bases", "")),
                ])
            if len(pdf_data) == 1:
                pdf_data.append(["Sin registros", "", "", ""])
            tabla = Table(pdf_data, repeatRows=1, colWidths=[120, 120, 75, 360])
            tabla.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(tabla)
            doc.build(story)
            st.download_button(
                "Descargar informe general (PDF)",
                data=pdf_buffer.getvalue(),
                file_name="registro_general_bases.pdf",
                mime="application/pdf",
            )
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
    try:
        verif = supabase.table("bases_campana").select(
            "activo"
        ).eq("id", base_id).limit(1).execute().data
        if not verif or not verif[0].get("activo", True):
            st.error("Esta base está desactivada. La sesión se cerró y sus datos se conservaron.")
            limpiar_sesion()
            st.stop()
    except Exception:
        st.error("No se pudo verificar el estado de la base. Por seguridad, vuelve a iniciar sesión.")
        limpiar_sesion()
        st.stop()

    st.success(
        f'Sesión: {st.session_state.base_nombre} · '
        f'{st.session_state.base_provincia} / {st.session_state.base_distrito} · '
        f'Cargo: {st.session_state.base_cargo} · '
        f'Dirección: {st.session_state.base_direccion}'
    )
    
    st.subheader("Integrantes de tu base")
    st.caption(
        "El cargo se guarda tal como lo selecciones o escribas y es propio de esta base. "
        "La misma persona puede pertenecer a otras bases con otro cargo."
    )

    try:
        filas = cargar_integrantes(base_id)
    except Exception as e:
        filas = []
        error_supabase("No se pudo cargar la lista de integrantes.", e)

    # --- AGREGAR INTEGRANTE ---
    with st.expander("Agregar integrante", expanded=False):
        nombres = st.text_input("Nombres", key="nuevo_integrante_nombres")
        apellidos = st.text_input("Apellidos", key="nuevo_integrante_apellidos")
        dni = st.text_input("DNI (8 dígitos)", key="nuevo_integrante_dni")
        celular = st.text_input("Celular (opcional)", key="nuevo_integrante_celular")
        cargo_seleccionado = st.selectbox(
            "Cargo o condición", CARGOS, key="nuevo_integrante_cargo"
        )
        cargo_otro = st.text_input(
            "Especifica el cargo o condición",
            disabled=(cargo_seleccionado != "Otro"),
            key="nuevo_integrante_cargo_otro",
        )
        consentimiento = st.checkbox(
            "Confirmo que la persona fue informada sobre el uso de sus datos y autorizó su registro.",
            key="nuevo_integrante_consentimiento",
        )
        guardar = st.button("Guardar integrante", key="guardar_integrante_btn")

        if guardar:
            cargo_final = (
                cargo_otro.strip()
                if cargo_seleccionado == "Otro"
                else cargo_seleccionado
            )
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
                    existentes = supabase.table("integrantes_base").select(
                        "id,dni"
                    ).eq("base_id", base_id).eq("dni", dni.strip()).limit(1).execute().data
                    if existentes:
                        st.error("Este DNI ya está registrado en esta base. No se creará un duplicado.")
                    else:
                        supabase.table("integrantes_base").insert({
                            "base_id": base_id,
                            "nombres": nombres.strip(),
                            "apellidos": apellidos.strip(),
                            "dni": dni.strip(),
                            "celular": celular.strip(),
                            "cargo": cargo_final,
                        }).execute()
                        st.success("Integrante registrado en esta base.")
                        st.rerun()
                except Exception as e:
                    error_supabase("No se pudo guardar el integrante.", e)

    # --- LISTA DE INTEGRANTES ---
    try:
        st.metric("Registros de integrantes de esta base", len(filas))
        busqueda = st.text_input("Buscar por nombre o DNI", key="buscar_base")
        filtrados = [
            f for f in filas
            if busqueda.strip().lower() in (
                nombre_completo(f) + " " + str(f.get("dni", ""))
            ).lower()
        ]
        if filtrados:
            df_mi_base = df_integrantes(
                filtrados, {str(base_id): st.session_state.base_nombre}
            )
            st.dataframe(df_mi_base, use_container_width=True, hide_index=True)
            st.download_button(
                "Descargar integrantes de mi base (Excel)",
                data=excel_bytes(
                    df_integrantes(filas, {str(base_id): st.session_state.base_nombre}),
                    "Integrantes"
                ),
                file_name="integrantes_mi_base.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
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
    st.write(
        "Los nombres, DNI y teléfonos son datos personales. "
        "Recógelos solo con una finalidad informada, limita el acceso a usuarios autorizados y "
        "comparte los informes solo con personas autorizadas."
    )
