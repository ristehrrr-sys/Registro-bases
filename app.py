import streamlit as st
from supabase import create_client
import hashlib
import secrets
import hmac
import re
import io
import os
import uuid
import textwrap
from datetime import date, datetime, timezone
from urllib.parse import quote

import pandas as pd
import requests
import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageOps

st.set_page_config(
    page_title="Registro de Bases y Comandos",
    page_icon="🗳️",
    layout="wide",
)

st.markdown("""
<style>
header,[data-testid="stHeader"],#MainMenu,.stDeployButton,footer,
[data-testid="stToolbar"],[data-testid="stDecoration"] {visibility:hidden!important;display:none!important}
.block-container {padding-top:1rem!important}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# CONFIGURACIÓN Y CONEXIÓN
# ---------------------------------------------------------------------
@st.cache_resource
def conectar_supabase():
    url = st.secrets["SUPABASE_URL"].strip()
    # En Streamlit Cloud configura SUPABASE_KEY con la clave service_role
    # SOLO en Secrets del servidor. Nunca la publiques en GitHub ni en el navegador.
    key = st.secrets["SUPABASE_KEY"].strip()
    return create_client(url, key)

try:
    supabase = conectar_supabase()
except Exception:
    st.error("No se pudo conectar con Supabase. Revisa SUPABASE_URL y SUPABASE_KEY en Secrets.")
    st.stop()

BUCKET_FOTOS = "fotos_integrantes"
BUCKET_PLANTILLAS = "plantillas_credenciales"
APP_PUBLIC_URL = st.secrets.get("APP_PUBLIC_URL", "").strip().rstrip("/")

# ---------------------------------------------------------------------
# GEOGRAFÍA PUNO
# ---------------------------------------------------------------------
DISTRITOS_PUNO = {
    "Azángaro": ["Achaya", "Arapa", "Asillo", "Azángaro", "Caminaca", "Chupa", "José Domingo Choquehuanca", "Muñani", "Potoni", "Samán", "San Antón", "San José", "San Juan de Salinas", "Santiago de Pupuja", "Tirapata"],
    "Carabaya": ["Ajoyani", "Ayapata", "Coasa", "Corani", "Crucero", "Ituata", "Macusani", "Ollachea", "San Gabán", "Usicayos"],
    "Chucuito": ["Desaguadero", "Huacullani", "Juli", "Kelluyo", "Pisacoma", "Pomata", "Zepita"],
    "El Collao": ["Capazo", "Ilave", "Pilcuyo", "Santa Rosa"],
    "Huancané": ["Cojata", "Huancané", "Huatasani", "Inchupalla", "Pusi", "Rosaspata", "Taraco", "Vilque Chico"],
    "Lampa": ["Cabanilla", "Calapuja", "Lampa", "Nicasio", "Ocuviri", "Palca", "Paratía", "Pucará", "Santa Lucía", "Vilavila"],
    "Melgar": ["Antauta", "Ayaviri", "Cupi", "Llalli", "Macari", "Nuñoa", "Orurillo", "Santa Rosa", "Umachiri"],
    "Moho": ["Conima", "Huayrapata", "Moho", "Tilali"],
    "Puno": ["Acora", "Amantaní", "Atuncolla", "Capachica", "Chucuito", "Coata", "Huata", "Mañazo", "Paucarcolla", "Pichacani", "Platería", "Puno", "San Antonio", "Tiquillaca", "Vilque"],
    "San Antonio de Putina": ["Ananea", "Pedro Vilca Apaza", "Putina", "Quilcapuncu", "Sina"],
    "San Román": ["Cabana", "Cabanillas", "Caracoto", "Juliaca"],
    "Sandia": ["Alto Inambari", "Cuyocuyo", "Limbani", "Patambuco", "Phara", "Quiaca", "San Juan del Oro", "San Pedro de Putina Punco", "Sandia", "Yanahuaya"],
    "Yunguyo": ["Anapia", "Copani", "Cuturapi", "Ollaraya", "Tinicachi", "Unicachi", "Yunguyo"],
}
PROVINCIAS = sorted(DISTRITOS_PUNO.keys())
CARGOS = ["Militante", "Coordinador de base", "Secretario de organización",
          "Secretario de economía", "Secretario de actas", "Fiscal", "Otro"]

# ---------------------------------------------------------------------
# SEGURIDAD Y SESIÓN
# ---------------------------------------------------------------------
def crear_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310000).hex()
    return f"{salt}${digest}"

def verificar_password(password: str, guardada: str) -> bool:
    try:
        salt, digest = guardada.split("$", 1)
        calculado = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310000).hex()
        return hmac.compare_digest(calculado, digest)
    except (ValueError, TypeError, AttributeError):
        return False

def hash_texto(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()

def admin_valido(usuario: str, password: str) -> bool:
    # Compatibilidad con los Secrets de la aplicación anterior:
    # se acepta ADMIN_PASSWORD (texto en Secrets) o ADMIN_PASSWORD_HASH.
    esperado_usuario = str(st.secrets.get("ADMIN_USER", "")).strip()
    esperado_hash = str(st.secrets.get("ADMIN_PASSWORD_HASH", "")).strip()
    esperado_password = str(st.secrets.get("ADMIN_PASSWORD", ""))
    if not esperado_usuario or not hmac.compare_digest(usuario.strip(), esperado_usuario):
        return False
    if esperado_hash:
        return verificar_password(password, esperado_hash)
    return bool(esperado_password) and hmac.compare_digest(password, esperado_password)

def limpiar_sesion():
    for clave in list(st.session_state.keys()):
        if clave.startswith(("base_", "admin_", "mostrar_")):
            del st.session_state[clave]
    st.session_state.base_id = None
    st.session_state.base_nombre = ""
    st.session_state.base_provincia = ""
    st.session_state.base_distrito = ""
    st.session_state.admin_autenticado = False
    st.session_state.es_admin = False

for k, v in {
    "base_id": None, "base_nombre": "", "base_provincia": "",
    "base_distrito": "", "admin_autenticado": False,
    "es_admin": False
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------------------------------------------------------------
# DATOS
# ---------------------------------------------------------------------
def cargar_bases():
    return (supabase.table("bases_campana")
            .select("id,nombre_base,provincia,distrito,usuario,fecha_registro")
            .order("nombre_base").execute().data or [])

def cargar_integrantes(base_id=None):
    q = (supabase.table("integrantes_base")
         .select("id,base_id,nombres,apellidos,dni,celular,cargo,fecha_registro,foto_url")
         .order("apellidos"))
    if base_id is not None:
        q = q.eq("base_id", base_id)
    return q.execute().data or []

def nombre_completo(f):
    return f'{f.get("nombres", "")} {f.get("apellidos", "")}'.strip()

def dataframe_integrantes(filas, incluir_base=False):
    filas_salida = []
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
        filas_salida.append(item)
    return pd.DataFrame(filas_salida)

def excel_bytes(df, hoja="Registros"):
    archivo = io.BytesIO()
    with pd.ExcelWriter(archivo, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=hoja[:31])
    archivo.seek(0)
    return archivo.getvalue()

def error_supabase(mensaje, error=None):
    st.error(mensaje)
    if error:
        st.caption(f"Detalle técnico: {str(error)[:500]}")
    st.caption("Comprueba la conexión, los nombres de tablas/columnas y los permisos de Supabase.")

def subir_archivo(bucket, path, contenido, content_type):
    supabase.storage.from_(bucket).upload(
        path=path, file=contenido,
        file_options={"content-type": content_type, "upsert": "true"}
    )
    return supabase.storage.from_(bucket).get_public_url(path)

def descargar_imagen(url):
    r = requests.get(url, timeout=25)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content))
    im.load()
    return im.convert("RGBA")

# ---------------------------------------------------------------------
# PLANTILLAS
# ---------------------------------------------------------------------
def listar_plantillas():
    return (supabase.table("plantillas_credenciales")
            .select("id,nombre,frontal_path,posterior_path,activa,ancho,alto,created_at")
            .order("created_at", desc=True).execute().data or [])

def url_plantilla(path):
    return supabase.storage.from_(BUCKET_PLANTILLAS).get_public_url(path)

def guardar_plantilla(nombre, frontal, posterior=None, activa=True):
    pid = str(uuid.uuid4())
    frontal_path = f"{pid}/frontal_{frontal.name}"
    frontal_type = frontal.type or "image/png"
    subir_archivo(BUCKET_PLANTILLAS, frontal_path, frontal.getvalue(), frontal_type)
    posterior_path = None
    if posterior is not None:
        posterior_path = f"{pid}/posterior_{posterior.name}"
        subir_archivo(BUCKET_PLANTILLAS, posterior_path, posterior.getvalue(),
                      posterior.type or "image/png")
    if activa:
        supabase.table("plantillas_credenciales").update({"activa": False}).neq("id", pid).execute()
    supabase.table("plantillas_credenciales").insert({
        "id": pid, "nombre": nombre.strip(), "frontal_path": frontal_path,
        "posterior_path": posterior_path, "activa": activa
    }).execute()

def activar_plantilla(pid):
    supabase.table("plantillas_credenciales").update({"activa": False}).neq("id", pid).execute()
    supabase.table("plantillas_credenciales").update({"activa": True}).eq("id", pid).execute()

# ---------------------------------------------------------------------
# CREDENCIALES QR
# ---------------------------------------------------------------------
def emitir_credencial(integrante, plantilla_id):
    # La llave se deriva del DNI y evita emitir varias credenciales para el mismo DNI.
    persona_key = hash_texto(str(integrante["dni"]).strip())
    token = secrets.token_urlsafe(32)
    token_hash = hash_texto(token)
    existente = (supabase.table("credenciales")
                 .select("id").eq("persona_key", persona_key).limit(1).execute().data or [])
    datos = {
        "integrante_id": integrante["id"],
        "persona_key": persona_key,
        "token_hash": token_hash,
        "estado": "vigente",
        "plantilla_id": plantilla_id,
        "emitida_en": datetime.now(timezone.utc).isoformat()
    }
    if existente:
        supabase.table("credenciales").update(datos).eq("id", existente[0]["id"]).execute()
    else:
        supabase.table("credenciales").insert(datos).execute()
    return token

def obtener_credencial(token):
    token_hash = hash_texto(token)
    filas = (supabase.table("credenciales")
             .select("id,integrante_id,persona_key,estado,plantilla_id,emitida_en")
             .eq("token_hash", token_hash).limit(1).execute().data or [])
    return filas[0] if filas else None

def crear_qr(url):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")

def cargar_fuente(tamano, negrita=False):
    candidatos = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if negrita else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if negrita else "DejaVuSans.ttf",
        "arialbd.ttf" if negrita else "arial.ttf",
    ]
    for ruta in candidatos:
        try:
            return ImageFont.truetype(ruta, tamano)
        except Exception:
            pass
    return ImageFont.load_default()

def ajustar_texto(dibujo, texto, fuente, ancho_max):
    texto = str(texto or "")
    palabras = texto.split()
    lineas, actual = [], ""
    for palabra in palabras:
        prueba = (actual + " " + palabra).strip()
        if dibujo.textbbox((0, 0), prueba, font=fuente)[2] <= ancho_max:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas or [""]

def componer_credencial(integrante, plantilla, qr_url, lado="frontal"):
    path = plantilla.get("frontal_path") if lado == "frontal" else plantilla.get("posterior_path")
    if path:
        lienzo = descargar_imagen(url_plantilla(path))
    else:
        # Plantilla predeterminada si no se cargó una imagen.
        lienzo = Image.new("RGBA", (1011, 638), "#F4F7FB")
        d = ImageDraw.Draw(lienzo)
        d.rounded_rectangle((8, 8, 1003, 630), radius=28, outline="#163B65", width=12)
        d.rectangle((12, 12, 999, 125), fill="#163B65")
        d.text((45, 35), "CREDENCIAL DE IDENTIFICACIÓN", fill="white",
               font=cargar_fuente(38, True))
        d.text((45, 82), "REGISTRO DE BASES Y COMANDOS", fill="#E7EEF7",
               font=cargar_fuente(20))
    lienzo = ImageOps.exif_transpose(lienzo).convert("RGBA")
    w, h = lienzo.size
    draw = ImageDraw.Draw(lienzo)

    if lado == "posterior":
        draw.text((int(w*.06), int(h*.18)), "VERIFICACIÓN DE CREDENCIAL",
                  fill="#17324D", font=cargar_fuente(max(18, int(h*.045)), True))
        draw.text((int(w*.06), int(h*.30)),
                  "Escanea el código QR para consultar su vigencia.",
                  fill="#202020", font=cargar_fuente(max(14, int(h*.027))))
        qr = crear_qr(qr_url)
        qsize = int(min(w, h) * .48)
        qr = qr.resize((qsize, qsize))
        lienzo.alpha_composite(qr.convert("RGBA"), (int(w*.66), int(h*.28)))
        return lienzo.convert("RGB")

    # Coordenadas relativas para adaptarse a plantillas horizontales o verticales.
    margen = int(w * .055)
    foto_size = int(min(w, h) * .36)
    foto_x, foto_y = margen, int(h * .29)
    foto_url = integrante.get("foto_url")
    if foto_url:
        try:
            foto = descargar_imagen(foto_url).convert("RGB")
            foto = ImageOps.fit(foto, (foto_size, foto_size))
            lienzo.paste(foto, (foto_x, foto_y))
        except Exception:
            draw.rectangle((foto_x, foto_y, foto_x+foto_size, foto_y+foto_size),
                           outline="#777777", width=3)
    else:
        draw.rectangle((foto_x, foto_y, foto_x+foto_size, foto_y+foto_size),
                       outline="#777777", width=3)
        draw.text((foto_x+8, foto_y+foto_size//2), "SIN FOTO",
                  fill="#555555", font=cargar_fuente(max(12, int(h*.025)), True))

    qr = crear_qr(qr_url)
    qr_size = int(min(w, h) * .25)
    qr = qr.resize((qr_size, qr_size))
    qr_x, qr_y = w - qr_size - margen, h - qr_size - margen
    lienzo.alpha_composite(qr.convert("RGBA"), (qr_x, qr_y))

    texto_x = foto_x + foto_size + int(w*.035)
    ancho_texto = max(100, qr_x - texto_x - int(w*.025))
    tam_nombre = max(16, int(h*.055))
    fuente_nombre = cargar_fuente(tam_nombre, True)
    fuente = cargar_fuente(max(13, int(h*.036)))
    y = int(h*.29)
    for linea in ajustar_texto(draw, nombre_completo(integrante), fuente_nombre, ancho_texto)[:2]:
        draw.text((texto_x, y), linea, fill="#111111", font=fuente_nombre)
        y += int(tam_nombre*1.35)
    y += int(h*.025)
    campos = [
        f"DNI: {integrante.get('dni','')}",
        f"Cargo: {integrante.get('cargo') or 'Sin cargo'}",
        f"Base: {integrante.get('nombre_base') or 'No especificada'}",
        f"Ubicación: {integrante.get('provincia') or ''} / {integrante.get('distrito') or ''}",
    ]
    for campo in campos:
        for linea in ajustar_texto(draw, campo, fuente, ancho_texto)[:2]:
            draw.text((texto_x, y), linea, fill="#222222", font=fuente)
            y += int(h*.052)
    return lienzo.convert("RGB")

# ---------------------------------------------------------------------
# VERIFICACIÓN PÚBLICA DEL QR
# ---------------------------------------------------------------------
st.title("🗳️ Registro de Bases y Comandos")
token_qr = st.query_params.get("verificar")
if token_qr:
    st.subheader("Verificación de credencial")
    try:
        cred = obtener_credencial(str(token_qr))
        if not cred:
            st.error("Código no válido o credencial no encontrada.")
        elif cred["estado"] != "vigente":
            st.warning("Esta credencial no está vigente.")
        else:
            fila = (supabase.table("integrantes_base")
                    .select("nombres,apellidos,cargo,base_id,dni")
                    .eq("id", cred["integrante_id"]).limit(1).execute().data or [])
            if not fila:
                st.warning("No se encontró el registro asociado.")
            else:
                persona = fila[0]
                bases_persona = (supabase.table("integrantes_base")
                                 .select("base_id").eq("dni", persona["dni"]).execute().data or [])
                ids = list({x["base_id"] for x in bases_persona})
                nombres_bases = []
                for bid in ids:
                    b = (supabase.table("bases_campana").select("nombre_base,provincia,distrito")
                         .eq("id", bid).limit(1).execute().data or [])
                    if b:
                        nombres_bases.append(b[0]["nombre_base"])
                st.success("Credencial vigente")
                st.write(f"**Integrante:** {nombre_completo(persona)}")
                st.write(f"**Cargo:** {persona.get('cargo') or 'Sin cargo'}")
                st.write(f"**Bases:** {', '.join(nombres_bases) if nombres_bases else 'No especificadas'}")
                st.caption("Por privacidad, esta consulta pública no muestra el DNI ni el teléfono.")
    except Exception as e:
        error_supabase("No se pudo verificar la credencial.", e)
    st.stop()

st.caption("Gestión de bases, integrantes, reuniones, asistencia y credenciales verificables.")

# ---------------------------------------------------------------------
# ACCESO
# ---------------------------------------------------------------------
if st.session_state.base_id is None and not st.session_state.admin_autenticado:
    st.subheader("Acceso al sistema")
    modo = st.radio("Tipo de acceso", ["Responsable de base", "Administrador"], horizontal=True)
    if modo == "Responsable de base":
        with st.form("login_base"):
            usuario_login = st.text_input("Usuario").strip()
            password_login = st.text_input("Contraseña", type="password")
            entrar = st.form_submit_button("Ingresar", use_container_width=True)
        if entrar:
            try:
                r = (supabase.table("bases_campana")
                     .select("id,nombre_base,provincia,distrito,usuario,password_hash")
                     .eq("usuario", usuario_login).limit(1).execute())
                if r.data and verificar_password(password_login, r.data[0].get("password_hash", "")):
                    b = r.data[0]
                    st.session_state.base_id = b["id"]
                    st.session_state.base_nombre = b["nombre_base"]
                    st.session_state.base_provincia = b.get("provincia") or ""
                    st.session_state.base_distrito = b.get("distrito") or ""
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos.")
            except Exception as e:
                error_supabase("No se pudo comprobar el acceso.", e)
    else:
        with st.form("login_admin"):
            u = st.text_input("Usuario administrador")
            p = st.text_input("Contraseña de administrador", type="password")
            entrar_admin = st.form_submit_button("Ingresar como administrador", use_container_width=True)
        if entrar_admin:
            if admin_valido(u, p):
                st.session_state.admin_autenticado = True
                st.session_state.es_admin = True
                st.rerun()
            else:
                st.error("Credenciales incorrectas o Secrets de administrador no configurados.")

# ---------------------------------------------------------------------
# PANEL ADMINISTRADOR
# ---------------------------------------------------------------------
if st.session_state.admin_autenticado and st.session_state.es_admin:
    st.success("Sesión de administrador")
    tabs = st.tabs(["Resumen", "Crear base", "Bases e integrantes",
                    "Reuniones y asistencia", "Exportar",
                    "Credenciales QR", "Plantillas"])

    with tabs[0]:
        try:
            bases = cargar_bases()
            integrantes = cargar_integrantes()
            c1, c2 = st.columns(2)
            c1.metric("Bases registradas", len(bases))
            c2.metric("Registros de integrantes", len(integrantes))
            if bases:
                df = pd.DataFrame([{
                    "Base": b.get("nombre_base", ""),
                    "Provincia": b.get("provincia") or "Sin asignar",
                    "Distrito": b.get("distrito") or "Sin asignar",
                    "Usuario": b.get("usuario", "")
                } for b in bases])
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.dataframe(df.groupby("Provincia").size().reset_index(name="Cantidad"),
                             use_container_width=True, hide_index=True)
            else:
                st.info("Todavía no hay bases registradas.")
        except Exception as e:
            error_supabase("No se pudo cargar el resumen.", e)

    with tabs[1]:
        st.subheader("Crear una base o comando")
        with st.form("crear_base"):
            nombre = st.text_input("Nombre de la base o comando")
            provincia = st.selectbox("Provincia", ["Seleccionar provincia"] + PROVINCIAS)
            ds = sorted(DISTRITOS_PUNO.get(provincia, []))
            distrito = st.selectbox("Distrito", ["Seleccionar distrito"] + ds,
                                    disabled=not ds)
            usuario = st.text_input("Crear usuario de la base").strip()
            password = st.text_input("Contraseña inicial (8 a 10 caracteres)", type="password")
            confirmar = st.text_input("Confirmar contraseña", type="password")
            acepta = st.checkbox("Confirmo que estoy autorizado para crear esta cuenta.")
            crear = st.form_submit_button("Crear base")
        if crear:
            if not nombre.strip() or provincia not in DISTRITOS_PUNO or distrito not in ds:
                st.warning("Completa el nombre, la provincia y el distrito.")
            elif not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", usuario):
                st.warning("El usuario debe tener de 3 a 40 caracteres válidos.")
            elif not 8 <= len(password) <= 10:
                st.warning("La contraseña debe tener entre 8 y 10 caracteres.")
            elif password != confirmar:
                st.warning("Las contraseñas no coinciden.")
            elif not acepta:
                st.warning("Confirma la autorización.")
            else:
                try:
                    existe = supabase.table("bases_campana").select("id").eq("usuario", usuario).limit(1).execute()
                    if existe.data:
                        st.error("Ese usuario ya está ocupado.")
                    else:
                        supabase.table("bases_campana").insert({
                            "nombre_base": nombre.strip(), "provincia": provincia,
                            "distrito": distrito, "usuario": usuario,
                            "password_hash": crear_hash(password)
                        }).execute()
                        st.success("Base creada correctamente.")
                except Exception as e:
                    error_supabase("No se pudo crear la base.", e)

    with tabs[2]:
        st.subheader("Bases e integrantes")
        try:
            bases = cargar_bases()
            if bases:
                mapa = {f'{b["nombre_base"]} — {b.get("provincia") or ""}/{b.get("distrito") or ""} (ID {b["id"]})': b for b in bases}
                label = st.selectbox("Seleccionar base", list(mapa.keys()))
                bsel = mapa[label]
                miembros = cargar_integrantes(bsel["id"])
                st.write(f'**Integrantes:** {len(miembros)}')
                buscar = st.text_input("Buscar por nombre, apellido o DNI", key="buscar_admin")
                filtrados = [f for f in miembros if buscar.lower().strip() in
                             (nombre_completo(f) + " " + str(f.get("dni", ""))).lower()]
                if filtrados:
                    st.dataframe(dataframe_integrantes(filtrados), use_container_width=True, hide_index=True)
                else:
                    st.info("No hay coincidencias.")
            else:
                st.info("No hay bases registradas.")
        except Exception as e:
            error_supabase("No se pudieron consultar las bases e integrantes.", e)

    with tabs[3]:
        st.subheader("Reuniones y asistencia")
        with st.form("crear_reunion"):
            nr = st.text_input("Nombre de la reunión")
            fr = st.date_input("Fecha de la reunión", value=date.today())
            lr = st.text_input("Lugar (opcional)")
            crear_r = st.form_submit_button("Crear reunión")
        if crear_r:
            if not nr.strip():
                st.warning("Escribe el nombre de la reunión.")
            else:
                try:
                    supabase.table("reuniones").insert({
                        "nombre": nr.strip(), "fecha": fr.isoformat(),
                        "lugar": lr.strip() or None
                    }).execute()
                    st.success("Reunión creada.")
                except Exception as e:
                    error_supabase("No se pudo crear la reunión.", e)
        st.divider()
        try:
            reuniones = (supabase.table("reuniones").select("id,nombre,fecha,lugar")
                         .order("fecha", desc=True).execute().data or [])
            bases = cargar_bases()
            if reuniones and bases:
                rm = {f'{r["fecha"]} — {r["nombre"]} (ID {r["id"]})': r for r in reuniones}
                bm = {f'{b["nombre_base"]} — {b.get("provincia") or ""}/{b.get("distrito") or ""} (ID {b["id"]})': b for b in bases}
                rsel = rm[st.selectbox("Seleccionar reunión", list(rm.keys()))]
                bsel = bm[st.selectbox("Seleccionar base para pasar lista", list(bm.keys()))]
                miembros = cargar_integrantes(bsel["id"])
                asistencia = (supabase.table("asistencias")
                              .select("integrante_id,presente")
                              .eq("reunion_id", rsel["id"]).execute().data or [])
                estado = {a["integrante_id"]: a.get("presente", False) for a in asistencia}
                presentes = 0
                if miembros:
                    for m in miembros:
                        c1, c2 = st.columns([4, 1])
                        c1.write(f'**{nombre_completo(m)}** · {m.get("cargo") or "Sin cargo"}')
                        ya = estado.get(m["id"], False)
                        if ya:
                            presentes += 1
                            c2.button("✓ Presente", key=f"pres_{rsel['id']}_{m['id']}", disabled=True,
                                      use_container_width=True)
                        elif c2.button("Marcar presente", key=f"mar_{rsel['id']}_{m['id']}",
                                       use_container_width=True):
                            supabase.table("asistencias").upsert({
                                "reunion_id": rsel["id"], "integrante_id": m["id"],
                                "presente": True
                            }, on_conflict="reunion_id,integrante_id").execute()
                            st.rerun()
                    st.metric("Presentes registrados en esta base", presentes)
                else:
                    st.info("Esta base no tiene integrantes.")
                st.divider()
                st.subheader("Historial de la reunión")
                historial = (supabase.table("asistencias")
                             .select("integrante_id,presente,integrantes_base(nombres,apellidos,dni,cargo)")
                             .eq("reunion_id", rsel["id"]).eq("presente", True)
                             .execute().data or [])
                if historial:
                    historial_df = pd.DataFrame([{
                        "Integrante": nombre_completo(a.get("integrantes_base") or {}),
                        "DNI": (a.get("integrantes_base") or {}).get("dni", ""),
                        "Cargo": (a.get("integrantes_base") or {}).get("cargo", ""),
                        "Estado": "Presente"
                    } for a in historial])
                    st.dataframe(historial_df, use_container_width=True, hide_index=True)
                    st.download_button(
                        "Descargar asistencia de esta reunión (Excel)",
                        excel_bytes(historial_df, "Asistencia"),
                        f"asistencia_reunion_{rsel['id']}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.info("Todavía no se ha marcado a nadie como presente.")
            elif not reuniones:
                st.info("Primero crea una reunión.")
            else:
                st.info("Primero registra una base.")
        except Exception as e:
            error_supabase("No se pudo cargar el módulo de asistencia.", e)

    with tabs[4]:
        st.subheader("Exportar datos")
        try:
            bases = cargar_bases()
            integrantes = cargar_integrantes()
            c1, c2 = st.columns(2)
            if bases:
                dfb = pd.DataFrame([{
                    "Nombre de base": b.get("nombre_base", ""),
                    "Provincia": b.get("provincia") or "",
                    "Distrito": b.get("distrito") or "",
                    "Usuario": b.get("usuario", ""),
                    "Fecha": str(b.get("fecha_registro", ""))[:10]
                } for b in bases])
                c1.download_button("Descargar bases (Excel)", excel_bytes(dfb, "Bases"),
                                   "bases_campana.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            if integrantes:
                dfi = dataframe_integrantes(integrantes, incluir_base=True)
                c2.download_button("Descargar integrantes (Excel)", excel_bytes(dfi, "Integrantes"),
                                   "integrantes_bases.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            error_supabase("No se pudieron preparar los archivos.", e)

    with tabs[5]:
        st.subheader("🪪 Generar credenciales QR")
        if not APP_PUBLIC_URL:
            st.warning("Configura APP_PUBLIC_URL en Secrets con la URL pública de tu aplicación para que los QR puedan abrir la verificación.")
        try:
            todos = cargar_integrantes()
            unicos = {}
            for f in todos:
                dni = str(f.get("dni", "")).strip()
                if dni:
                    unicos[dni] = f
            if unicos:
                opciones = {f'{nombre_completo(f)} (DNI: {dni})': f for dni, f in unicos.items()}
                seleccion = st.selectbox("Selecciona al integrante", list(opciones.keys()))
                integrante = opciones[seleccion]
                # Recupera las bases asociadas al mismo DNI; no publica DNI en el QR.
                registros = (supabase.table("integrantes_base")
                             .select("base_id").eq("dni", integrante["dni"]).execute().data or [])
                base_ids = list({x["base_id"] for x in registros})
                nombres_bases = []
                for bid in base_ids:
                    bd = supabase.table("bases_campana").select("nombre_base,provincia,distrito").eq("id", bid).limit(1).execute().data or []
                    if bd:
                        nombres_bases.append(bd[0]["nombre_base"])
                integrante_render = dict(integrante)
                integrante_render["nombre_base"] = ", ".join(nombres_bases)
                plantillas = listar_plantillas()
                activas = [p for p in plantillas if p.get("activa")]
                if activas:
                    plantilla = activas[0]
                else:
                    plantilla = {
                        "id": None, "nombre": "Plantilla predeterminada",
                        "frontal_path": None, "posterior_path": None
                    }
                st.write(f'**Integrante:** {nombre_completo(integrante)}')
                st.write(f'**Plantilla:** {plantilla["nombre"]}')
                if st.button("Generar / renovar credencial", type="primary"):
                    if not APP_PUBLIC_URL:
                        st.error("No se puede emitir un QR funcional hasta configurar APP_PUBLIC_URL.")
                    else:
                        token = emitir_credencial(integrante, plantilla.get("id"))
                        url_qr = f"{APP_PUBLIC_URL}/?verificar={quote(token)}"
                        frente = componer_credencial(integrante_render, plantilla, url_qr, "frontal")
                        buffer = io.BytesIO()
                        frente.save(buffer, format="PNG")
                        buffer.seek(0)
                        st.session_state["credencial_generada"] = buffer.getvalue()
                        st.session_state["credencial_nombre"] = re.sub(r"[^A-Za-z0-9_-]", "_", str(integrante["dni"]))
                        st.session_state["credencial_token"] = token
                        if plantilla.get("posterior_path"):
                            reverso = componer_credencial(integrante_render, plantilla, url_qr, "posterior")
                            rb = io.BytesIO()
                            reverso.save(rb, format="PNG")
                            st.session_state["credencial_reverso"] = rb.getvalue()
                        else:
                            st.session_state.pop("credencial_reverso", None)
                        st.success("Credencial generada. Escanea el QR para probar la verificación.")
                if st.session_state.get("credencial_generada"):
                    st.image(st.session_state["credencial_generada"], caption="Vista previa")
                    nombre_archivo = st.session_state.get("credencial_nombre", "credencial")
                    st.download_button("Descargar credencial frontal (PNG)",
                        st.session_state["credencial_generada"], f"credencial_{nombre_archivo}.png", "image/png")
                    if st.session_state.get("credencial_reverso"):
                        st.image(st.session_state["credencial_reverso"], caption="Reverso")
                        st.download_button("Descargar reverso (PNG)",
                            st.session_state["credencial_reverso"], f"credencial_{nombre_archivo}_reverso.png", "image/png")
                    try:
                        from reportlab.pdfgen import canvas
                        from reportlab.lib.utils import ImageReader
                        pdf = io.BytesIO()
                        c = canvas.Canvas(pdf, pagesize=(85.6*2.83465, 54*2.83465))
                        img = Image.open(io.BytesIO(st.session_state["credencial_generada"])).convert("RGB")
                        c.drawImage(ImageReader(img), 0, 0, width=85.6*2.83465, height=54*2.83465)
                        c.showPage()
                        if st.session_state.get("credencial_reverso"):
                            img2 = Image.open(io.BytesIO(st.session_state["credencial_reverso"])).convert("RGB")
                            c.drawImage(ImageReader(img2), 0, 0, width=85.6*2.83465, height=54*2.83465)
                            c.showPage()
                        c.save()
                        st.download_button("Descargar credencial (PDF)", pdf.getvalue(),
                                           f"credencial_{nombre_archivo}.pdf", "application/pdf")
                    except Exception as e:
                        st.caption(f"PDF no disponible: {e}")
            else:
                st.info("Todavía no hay integrantes registrados.")
        except Exception as e:
            error_supabase("No se pudo preparar la credencial.", e)

    with tabs[6]:
        st.subheader("🎨 Administrar plantillas")
        st.info("Puedes subir una imagen ya diseñada o usar la plantilla predeterminada. La imagen se utiliza como fondo; el sistema añade los datos y el QR.")
        with st.form("form_plantilla", clear_on_submit=True):
            nombre_plantilla = st.text_input("Nombre de la plantilla")
            frontal = st.file_uploader("Imagen frontal (PNG o JPG)", type=["png", "jpg", "jpeg"])
            posterior = st.file_uploader("Imagen posterior (opcional)", type=["png", "jpg", "jpeg"])
            activar_al_guardar = st.checkbox("Activar esta plantilla al guardar", value=True)
            guardar_plantilla_btn = st.form_submit_button("Guardar plantilla")
        if guardar_plantilla_btn:
            if not nombre_plantilla.strip() or frontal is None:
                st.warning("Escribe un nombre y selecciona la imagen frontal.")
            else:
                try:
                    im = Image.open(io.BytesIO(frontal.getvalue()))
                    if im.width < 400 or im.height < 250:
                        st.warning("La imagen es pequeña. Se recomienda al menos 1011 × 638 píxeles.")
                    guardar_plantilla(nombre_plantilla, frontal, posterior, activar_al_guardar)
                    st.success("Plantilla guardada correctamente.")
                    st.rerun()
                except Exception as e:
                    error_supabase("No se pudo guardar la plantilla. Revisa el bucket y la tabla de Supabase.", e)
        st.divider()
        try:
            plantillas = listar_plantillas()
            if plantillas:
                for p in plantillas:
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.write(f'**{p["nombre"]}**' + (" · Activa" if p.get("activa") else ""))
                    if c2.button("Vista previa", key=f"prev_{p['id']}"):
                        st.image(url_plantilla(p["frontal_path"]), caption=p["nombre"])
                    if c3.button("Activar", key=f"act_{p['id']}", disabled=bool(p.get("activa"))):
                        activar_plantilla(p["id"])
                        st.success("Plantilla activada.")
                        st.rerun()
            else:
                st.info("Aún no hay plantillas guardadas. Se usará el diseño predeterminado.")
        except Exception as e:
            error_supabase("No se pudieron cargar las plantillas.", e)

    if st.button("Cerrar sesión de administrador"):
        limpiar_sesion()
        st.rerun()

# ---------------------------------------------------------------------
# PANEL RESPONSABLE DE BASE
# ---------------------------------------------------------------------
if st.session_state.base_id is not None:
    base_id = st.session_state.base_id
    st.success(f'Sesión: {st.session_state.base_nombre} · {st.session_state.base_provincia} / {st.session_state.base_distrito}')
    st.subheader("Integrantes de tu base")
    with st.expander("Agregar integrante", expanded=False):
        with st.form("form_integrante", clear_on_submit=True):
            nombres = st.text_input("Nombres")
            apellidos = st.text_input("Apellidos")
            dni = st.text_input("DNI (8 dígitos)")
            celular = st.text_input("Celular (9 a 15 dígitos)")
            foto = st.file_uploader("Fotografía del integrante (opcional)", type=["jpg", "jpeg", "png"])
            cargo_sel = st.selectbox("Cargo o condición", CARGOS)
            cargo_otro = st.text_input("Especifica el cargo") if cargo_sel == "Otro" else ""
            consentimiento = st.checkbox("Confirmo que la persona fue informada y autorizó el registro de sus datos y fotografía.")
            guardar = st.form_submit_button("Guardar integrante")
        if guardar:
            cargo_final = cargo_otro.strip() if cargo_sel == "Otro" else cargo_sel
            if not nombres.strip() or not apellidos.strip():
                st.warning("Completa nombres y apellidos.")
            elif not re.fullmatch(r"\d{8}", dni.strip()):
                st.warning("El DNI debe tener 8 dígitos.")
            elif not re.fullmatch(r"\+?\d{9,15}", celular.strip()):
                st.warning("Celular inválido.")
            elif cargo_sel == "Otro" and not cargo_final:
                st.warning("Especifica el cargo.")
            elif not consentimiento:
                st.warning("Confirma que existe autorización.")
            else:
                try:
                    duplicado = (supabase.table("integrantes_base").select("id")
                                 .eq("base_id", base_id).eq("dni", dni.strip()).limit(1).execute().data or [])
                    if duplicado:
                        st.error("Ese DNI ya está registrado en esta base.")
                    else:
                        url_foto = None
                        if foto is not None:
                            # Se conserva el formato real del archivo.
                            ext = "png" if foto.type == "image/png" else "jpg"
                            path = f"{base_id}/{dni.strip()}_{uuid.uuid4().hex}.{ext}"
                            url_foto = subir_archivo(BUCKET_FOTOS, path, foto.getvalue(),
                                                     foto.type or "image/jpeg")
                        supabase.table("integrantes_base").insert({
                            "base_id": base_id, "nombres": nombres.strip(),
                            "apellidos": apellidos.strip(), "dni": dni.strip(),
                            "celular": celular.strip(), "cargo": cargo_final,
                            "foto_url": url_foto
                        }).execute()
                        st.success("Integrante registrado.")
                        st.rerun()
                except Exception as e:
                    error_supabase("No se pudo guardar el integrante.", e)
    try:
        filas = cargar_integrantes(base_id)
        st.metric("Total de integrantes", len(filas))
        if filas:
            st.dataframe(dataframe_integrantes(filas), use_container_width=True, hide_index=True)
            st.download_button("Descargar integrantes de mi base (Excel)",
                excel_bytes(dataframe_integrantes(filas), "Integrantes"),
                "integrantes_mi_base.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.info("Todavía no hay integrantes registrados.")
    except Exception as e:
        error_supabase("No se pudo cargar la lista.", e)

    if st.button("Cerrar sesión de base"):
        limpiar_sesion()
        st.rerun()

st.divider()
with st.expander("Aviso de privacidad"):
    st.write(
        "Los datos de identificación, fotografías y afiliación o participación organizativa "
        "son datos personales que requieren protección reforzada. Informa a cada persona "
        "sobre la finalidad, quién accede, cuánto tiempo se conservarán y cómo solicitar "
        "corrección o eliminación. No registres a nadie sin autorización documentada. "
        "La consulta pública del QR muestra únicamente datos mínimos y nunca el DNI ni el teléfono."
    )
