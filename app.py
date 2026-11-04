import streamlit as st
from supabase import create_client
import hashlib
import secrets
import hmac
import base64
import re
import io
import os
import uuid
import time
import logging
import json
import copy
import zipfile
from functools import lru_cache
import unicodedata
from concurrent.futures import ThreadPoolExecutor
import textwrap
from datetime import date, datetime, timezone
from urllib.parse import quote, unquote

import pandas as pd
import requests
import qrcode
import altair as alt
from PIL import Image, ImageDraw, ImageFont, ImageOps

st.set_page_config(
    page_title="Registro de Bases y Comandos",
    page_icon="\U0001f5f3\ufe0f",
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
# CONFIGURACION Y CONEXION
# ---------------------------------------------------------------------
@st.cache_resource
def conectar_supabase():
    url = st.secrets["SUPABASE_URL"].strip()
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
# GEOGRAFIA PUNO
# ---------------------------------------------------------------------
DISTRITOS_PUNO = {
    "Az\u00e1ngaro": ["Achaya", "Arapa", "Asillo", "Az\u00e1ngaro", "Caminaca", "Chupa", "Jos\u00e9 Domingo Choquehuanca", "Mu\u00f1ani", "Potoni", "Sam\u00e1n", "San Ant\u00f3n", "San Jos\u00e9", "San Juan de Salinas", "Santiago de Pupuja", "Tirapata"],
    "Carabaya": ["Ajoyani", "Ayapata", "Coasa", "Corani", "Crucero", "Ituata", "Macusani", "Ollachea", "San Gab\u00e1n", "Usicayos"],
    "Chucuito": ["Desaguadero", "Huacullani", "Juli", "Kelluyo", "Pisacoma", "Pomata", "Zepita"],
    "El Collao": ["Capazo", "Ilave", "Pilcuyo", "Santa Rosa"],
    "Huancan\u00e9": ["Cojata", "Huancan\u00e9", "Huatasani", "Inchupalla", "Pusi", "Rosaspata", "Taraco", "Vilque Chico"],
    "Lampa": ["Cabanilla", "Calapuja", "Lampa", "Nicasio", "Ocuviri", "Palca", "Parat\u00eda", "Pucar\u00e1", "Santa Luc\u00eda", "Vilavila"],
    "Melgar": ["Antauta", "Ayaviri", "Cupi", "Llalli", "Macari", "Nu\u00f1oa", "Orurillo", "Santa Rosa", "Umachiri"],
    "Moho": ["Conima", "Huayrapata", "Moho", "Tilali"],
    "Puno": ["Acora", "Amantan\u00ed", "Atuncolla", "Capachica", "Chucuito", "Coata", "Huata", "Ma\u00f1azo", "Paucarcolla", "Pichacani", "Plater\u00eda", "Puno", "San Antonio", "Tiquillaca", "Vilque"],
    "San Antonio de Putina": ["Ananea", "Pedro Vilca Apaza", "Putina", "Quilcapuncu", "Sina"],
    "San Rom\u00e1n": ["Cabana", "Cabanillas", "Caracoto", "Juliaca"],
    "Sandia": ["Alto Inambari", "Cuyocuyo", "Limbani", "Patambuco", "Phara", "Quiaca", "San Juan del Oro", "San Pedro de Putina Punco", "Sandia", "Yanahuaya"],
    "Yunguyo": ["Anapia", "Copani", "Cuturapi", "Ollaraya", "Tinicachi", "Unicachi", "Yunguyo"],
}
PROVINCIAS = sorted(DISTRITOS_PUNO.keys())
CARGOS = ["Militante", "Coordinador de base", "Secretario de organizaci\u00f3n",
          "Secretario de econom\u00eda", "Secretario de actas", "Fiscal", "Otro"]

# ---------------------------------------------------------------------
# SEGURIDAD Y SESION
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

def _clave_hmac() -> bytes:
    secreto = str(st.secrets.get("CLAVE_HMAC", "")).strip()
    if not secreto:
        secreto = "persona_key:" + str(st.secrets["SUPABASE_KEY"])
    return secreto.encode("utf-8")

def clave_persona(dni) -> str:
    return hmac.new(_clave_hmac(), str(dni).strip().encode("utf-8"), hashlib.sha256).hexdigest()

def clave_persona_legacy(dni) -> str:
    return hash_texto(str(dni).strip())

def token_credencial(dni, cred_id) -> str:
    mac = hmac.new(_clave_hmac(), f"token:{str(dni).strip()}:{cred_id}".encode("utf-8"),
                   hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")

def token_reproducible(dni, cred) -> bool:
    try:
        calculado = hash_texto(token_credencial(dni, cred["id"]))
        return hmac.compare_digest(calculado, str(cred.get("token_hash", "")))
    except Exception:
        return False

def admin_valido(usuario: str, password: str) -> bool:
    esperado_usuario = str(st.secrets.get("ADMIN_USER", "")).strip()
    esperado_hash = str(st.secrets.get("ADMIN_PASSWORD_HASH", "")).strip()
    esperado_password = str(st.secrets.get("ADMIN_PASSWORD", ""))
    if not esperado_usuario or not hmac.compare_digest(usuario.strip().encode(), esperado_usuario.encode()):
        return False
    if esperado_hash:
        return verificar_password(password, esperado_hash)
    return bool(esperado_password) and hmac.compare_digest(password.encode(), esperado_password.encode())

MAX_INTENTOS = 5
VENTANA_SEG = 15 * 60
HASH_FICTICIO = "0" * 32 + "$" + "0" * 64

@st.cache_resource
def _registro_intentos():
    return {}

def segundos_bloqueo(clave: str) -> int:
    ahora = time.time()
    registro = _registro_intentos()
    recientes = [t for t in registro.get(clave, []) if ahora - t < VENTANA_SEG]
    registro[clave] = recientes
    if len(recientes) >= MAX_INTENTOS:
        return int(VENTANA_SEG - (ahora - recientes[0]))
    return 0

def registrar_fallo(clave: str):
    _registro_intentos().setdefault(clave, []).append(time.time())

def limpiar_fallos(clave: str):
    _registro_intentos().pop(clave, None)

def limpiar_sesion():
    for clave in list(st.session_state.keys()):
        if clave.startswith(("base_", "admin_", "mostrar_", "credencial_", "lote_")):
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
def traer_todo(construir, tam=1000):
    filas, ini = [], 0
    while True:
        bloque = construir().range(ini, ini + tam - 1).execute().data or []
        filas.extend(bloque)
        if len(bloque) < tam:
            return filas
        ini += tam

def cargar_bases():
    return traer_todo(lambda: supabase.table("bases_campana")
                      .select("id,nombre_base,provincia,distrito,usuario,fecha_registro")
                      .order("nombre_base").order("id"))

def cargar_integrantes(base_id=None):
    def construir():
        q = (supabase.table("integrantes_base")
             .select("id,base_id,nombres,apellidos,dni,celular,cargo,fecha_registro,foto_url")
             .order("apellidos").order("id"))
        if base_id is not None:
            q = q.eq("base_id", base_id)
        return q
    return traer_todo(construir)

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
            "Cargo / condici\u00f3n": f.get("cargo") or "",
            "Fecha de registro": str(f.get("fecha_registro", ""))[:10],
        }
        if incluir_base:
            item["Base ID"] = f.get("base_id", "")
        filas_salida.append(item)
    return pd.DataFrame(filas_salida)

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

def nombre_archivo_seguro(texto):
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_-]+", "_", t).strip("_")[:60] or "sin_nombre"

def ubicacion_texto(base):
    return " / ".join(x for x in (base.get("provincia"), base.get("distrito")) if x)

def excel_multihoja(hojas, titulo=None):
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    archivo = io.BytesIO()
    fila_ini = 2 if titulo else 0
    with pd.ExcelWriter(archivo, engine="openpyxl") as writer:
        for nombre, df in hojas.items():
            nombre = re.sub(r"[\[\]\*\?/\\:]", "-", nombre)[:31]
            df.to_excel(writer, index=False, sheet_name=nombre, startrow=fila_ini)
            ws = writer.sheets[nombre]
            enc = fila_ini + 1
            ncols = max(1, len(df.columns))
            if titulo:
                ws["A1"] = titulo
                ws["A1"].font = Font(bold=True, size=14, color="163B65")
            for c in range(1, ncols + 1):
                celda = ws.cell(row=enc, column=c)
                celda.font = Font(bold=True, color="FFFFFF")
                celda.fill = PatternFill("solid", fgColor="163B65")
                celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.freeze_panes = f"A{enc + 1}"
            if len(df) > 0:
                ws.auto_filter.ref = f"A{enc}:{get_column_letter(ncols)}{enc + len(df)}"
            for i, col in enumerate(df.columns, start=1):
                largo = max([len(str(col))] + [len(str(v)) for v in df[col].head(500)])
                ws.column_dimensions[get_column_letter(i)].width = min(max(12, largo + 3), 50)
            for fila in ws.iter_rows(min_row=enc + 1):
                for celda in fila:
                    if isinstance(celda.value, str):
                        if celda.value.startswith("="):
                            celda.data_type = "s"
                        celda.number_format = "@"
    archivo.seek(0)
    return archivo.getvalue()

def excel_bytes(df, hoja="Registros", titulo=None):
    return excel_multihoja({hoja: df}, titulo)

COLUMNAS_DETALLE = ["N.\u00ba", "Base", "Provincia", "Distrito", "Apellidos", "Nombres",
                    "DNI", "Celular", "Cargo / condici\u00f3n", "Fecha de registro"]

def dataframe_detallado(filas, mapa_bases):
    def orden(f):
        b = mapa_bases.get(f.get("base_id"), {})
        return (str(b.get("nombre_base", "")).lower(), str(f.get("apellidos", "")).lower(),
                str(f.get("nombres", "")).lower())
    salida = []
    for i, f in enumerate(sorted(filas, key=orden), start=1):
        b = mapa_bases.get(f.get("base_id"), {})
        salida.append({
            "N.\u00ba": i, "Base": b.get("nombre_base", ""), "Provincia": b.get("provincia") or "",
            "Distrito": b.get("distrito") or "", "Apellidos": f.get("apellidos", ""),
            "Nombres": f.get("nombres", ""), "DNI": f.get("dni", ""),
            "Celular": f.get("celular", ""), "Cargo / condici\u00f3n": f.get("cargo") or "",
            "Fecha de registro": str(f.get("fecha_registro", ""))[:10],
        })
    return pd.DataFrame(salida, columns=COLUMNAS_DETALLE)

def pdf_lista(titulo, subtitulo, miembros, con_firma=False):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from xml.sax.saxutils import escape
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.8*cm, title=titulo)
    est = getSampleStyleSheet()
    t_titulo = ParagraphStyle("t", parent=est["Title"], fontSize=15, leading=18, alignment=0,
                              textColor=colors.HexColor("#163B65"))
    t_sub = ParagraphStyle("s", parent=est["Normal"], fontSize=9.5, leading=12,
                           textColor=colors.HexColor("#444444"))
    t_celda = ParagraphStyle("c", parent=est["Normal"], fontSize=8.5, leading=10)
    t_enc = ParagraphStyle("e", parent=t_celda, textColor=colors.white, fontName="Helvetica-Bold")

    def p(texto, estilo=t_celda):
        return Paragraph(escape(str(texto if texto is not None else "")), estilo)

    ordenados = sorted(miembros, key=lambda m: (str(m.get("apellidos", "")).lower(),
                                                str(m.get("nombres", "")).lower()))
    if con_firma:
        cabecera = ["N.\u00ba", "Apellidos y nombres", "DNI", "Cargo", "Firma"]
        anchos = [1.0*cm, 6.2*cm, 2.2*cm, 3.6*cm, 5.0*cm]
    else:
        cabecera = ["N.\u00ba", "Apellidos y nombres", "DNI", "Celular", "Cargo"]
        anchos = [1.0*cm, 6.6*cm, 2.2*cm, 2.8*cm, 5.4*cm]
    filas = [[p(h, t_enc) for h in cabecera]]
    for i, m in enumerate(ordenados, start=1):
        nombre = f'{m.get("apellidos", "")}, {m.get("nombres", "")}'.strip(", ")
        if con_firma:
            filas.append([p(i), p(nombre), p(m.get("dni")), p(m.get("cargo") or ""), ""])
        else:
            filas.append([p(i), p(nombre), p(m.get("dni")), p(m.get("celular")), p(m.get("cargo") or "")])
    alturas = ([None] + [0.95*cm] * len(ordenados)) if con_firma else None
    tabla = Table(filas, colWidths=anchos, rowHeights=alturas, repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163B65")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if not con_firma:
        estilo.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FB")]))
    tabla.setStyle(TableStyle(estilo))
    elementos = [p(titulo, t_titulo)]
    if subtitulo:
        elementos.append(p(subtitulo, t_sub))
    elementos.append(p(f"Total: {len(ordenados)} integrantes \u00b7 {date.today().strftime('%d/%m/%Y')}", t_sub))
    elementos += [Spacer(1, 0.4*cm), tabla]

    def pie(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(1.5*cm, 0.9*cm, "Documento con datos personales: uso interno.")
        canvas.drawRightString(A4[0] - 1.5*cm, 0.9*cm, f"P\u00e1gina {doc_.page}")
        canvas.restoreState()

    doc.build(elementos, onFirstPage=pie, onLaterPages=pie)
    return buf.getvalue()

def botones_lista(base, miembros, clave):
    nombre = base.get("nombre_base", "base")
    archivo = nombre_archivo_seguro(nombre)
    ubic = ubicacion_texto(base)
    titulo = f"Lista de integrantes \u2014 {nombre}"
    df = dataframe_detallado(miembros, {base.get("id"): base})
    c1, c2, c3 = st.columns(3)
    c1.download_button("Descargar Excel",
                       excel_bytes(df, "Integrantes", titulo=f"{titulo} \u00b7 {ubic}" if ubic else titulo),
                       f"integrantes_{archivo}.xlsx", MIME_XLSX, key=f"xl_{clave}")
    try:
        c2.download_button("Descargar PDF (lista)", pdf_lista(titulo, ubic, miembros),
                           f"lista_{archivo}.pdf", "application/pdf", key=f"pdf_{clave}")
        c3.download_button("PDF para firmas / asistencia",
                           pdf_lista(titulo, ubic, miembros, con_firma=True),
                           f"firmas_{archivo}.pdf", "application/pdf", key=f"pdff_{clave}")
    except ImportError:
        st.caption("Los PDF requieren instalar reportlab (agr\u00e9galo a requirements.txt).")
    except Exception as e:
        logger.warning("PDF de lista no disponible: %r", e)
        st.caption("El PDF no est\u00e1 disponible en este momento.")
    st.caption("Estos archivos contienen datos personales (DNI y celular). Man\u00e9jalos con cuidado.")

logger = logging.getLogger("registro_bases")

def error_supabase(mensaje, error=None):
    ref = uuid.uuid4().hex[:8]
    logger.error("[%s] %s | %r", ref, mensaje, error)
    st.error(f"{mensaje} (ref. {ref})")
    if error and st.session_state.get("es_admin"):
        st.caption(f"Detalle t\u00e9cnico (solo visible para el administrador): {str(error)[:500]}")
    st.caption("Si el problema contin\u00faa, comunica la referencia al administrador.")

def subir_archivo(bucket, path, contenido, content_type):
    supabase.storage.from_(bucket).upload(
        path=path, file=contenido,
        file_options={"content-type": content_type, "upsert": "true"}
    )
    return supabase.storage.from_(bucket).get_public_url(path)

MAX_IMG_BYTES = 8 * 1024 * 1024

def ext_imagen(archivo) -> str:
    return "png" if getattr(archivo, "type", "") == "image/png" else "jpg"

def procesar_foto(archivo, lado_max=900) -> bytes:
    try:
        im = Image.open(io.BytesIO(archivo.getvalue()))
        im.load()
    except Exception:
        raise ValueError("La fotograf\u00eda no es una imagen v\u00e1lida.")
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((lado_max, lado_max))
    salida = io.BytesIO()
    im.save(salida, format="JPEG", quality=88, optimize=True)
    return salida.getvalue()

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

def guardar_plantilla(nombre, frontal, posterior=None, activa=True, diseno=None):
    pid = str(uuid.uuid4())
    frontal_path = f"{pid}/frontal.{ext_imagen(frontal)}"
    frontal_type = frontal.type or "image/png"
    subir_archivo(BUCKET_PLANTILLAS, frontal_path, frontal.getvalue(), frontal_type)
    posterior_path = None
    if posterior is not None:
        posterior_path = f"{pid}/posterior.{ext_imagen(posterior)}"
        subir_archivo(BUCKET_PLANTILLAS, posterior_path, posterior.getvalue(),
                      posterior.type or "image/png")
    if activa:
        supabase.table("plantillas_credenciales").update({"activa": False}).neq("id", pid).execute()
    supabase.table("plantillas_credenciales").insert({
        "id": pid, "nombre": nombre.strip(), "frontal_path": frontal_path,
        "posterior_path": posterior_path, "activa": activa
    }).execute()
    if diseno:
        guardar_diseno(pid, diseno)
    return pid

def activar_plantilla(pid):
    supabase.table("plantillas_credenciales").update({"activa": False}).neq("id", pid).execute()
    supabase.table("plantillas_credenciales").update({"activa": True}).eq("id", pid).execute()

# ---------------------------------------------------------------------
# CREDENCIALES QR
# ---------------------------------------------------------------------
def credencial_de_dni(dni):
    claves = list({clave_persona(dni), clave_persona_legacy(dni)})
    filas = (supabase.table("credenciales")
             .select("id,integrante_id,estado,emitida_en,token_hash").in_("persona_key", claves)
             .limit(1).execute().data or [])
    return filas[0] if filas else None

def escribir_credencial(existente_id, fila):
    if existente_id:
        try:
            supabase.table("credenciales").update(fila).eq("id", existente_id).execute()
            return
        except Exception as e:
            logger.warning("No se pudo actualizar la credencial %s; se reemplaza: %r", existente_id, e)
            supabase.table("credenciales").delete().eq("id", existente_id).execute()
    supabase.table("credenciales").insert(fila).execute()

def emitir_credencial(integrante, plantilla_id, cred_id, token):
    dni = str(integrante["dni"]).strip()
    existente = credencial_de_dni(dni)
    fila = {
        "id": cred_id,
        "integrante_id": integrante["id"],
        "persona_key": clave_persona(dni),
        "token_hash": hash_texto(token),
        "estado": "vigente",
        "plantilla_id": plantilla_id,
        "emitida_en": datetime.now(timezone.utc).isoformat()
    }
    escribir_credencial(existente["id"] if existente else None, fila)

def datos_bases_por_dni(dni):
    regs = (supabase.table("integrantes_base").select("base_id")
            .eq("dni", dni).execute().data or [])
    ids = list({x["base_id"] for x in regs})
    if not ids:
        return []
    return (supabase.table("bases_campana").select("id,nombre_base,provincia,distrito")
            .in_("id", ids).execute().data or [])

def generar_clave(n=12):
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    while True:
        clave = "".join(secrets.choice(alfabeto) for _ in range(n))
        if re.search(r"[A-Za-z]", clave) and re.search(r"\d", clave):
            return clave

def ruta_de_foto(url):
    if not url:
        return None
    marca = f"/{BUCKET_FOTOS}/"
    if marca not in str(url):
        return None
    return unquote(str(url).split(marca, 1)[1].split("?", 1)[0]) or None

def borrar_fotos(urls):
    rutas = [r for r in (ruta_de_foto(u) for u in urls) if r]
    if rutas:
        try:
            supabase.storage.from_(BUCKET_FOTOS).remove(rutas)
        except Exception as e:
            logger.warning("No se pudieron borrar fotos: %r", e)

def liberar_credencial(integrante):
    dni = str(integrante["dni"]).strip()
    cred = credencial_de_dni(dni)
    if not cred or cred.get("integrante_id") != integrante["id"]:
        return
    otros = (supabase.table("integrantes_base").select("id").eq("dni", dni)
             .neq("id", integrante["id"]).limit(1).execute().data or [])
    if otros:
        supabase.table("credenciales").update({"integrante_id": otros[0]["id"]}).eq("id", cred["id"]).execute()
    else:
        supabase.table("credenciales").delete().eq("id", cred["id"]).execute()

def eliminar_integrantes(integrantes):
    if not integrantes:
        return
    ids = [i["id"] for i in integrantes]
    ids_set = set(ids)
    dni_de = {i["id"]: str(i.get("dni", "")).strip() for i in integrantes}
    conservados = {}
    dnis = [d for d in set(dni_de.values()) if d]
    for k in range(0, len(dnis), 50):
        filas = (supabase.table("integrantes_base").select("id,dni")
                 .in_("dni", dnis[k:k + 50]).execute().data or [])
        for f in filas:
            if f["id"] not in ids_set:
                conservados.setdefault(str(f["dni"]).strip(), f["id"])
    for k in range(0, len(ids), 100):
        creds = (supabase.table("credenciales").select("id,integrante_id")
                 .in_("integrante_id", ids[k:k + 100]).execute().data or [])
        for c in creds:
            destino = conservados.get(dni_de.get(c["integrante_id"]))
            if destino:
                supabase.table("credenciales").update({"integrante_id": destino}).eq("id", c["id"]).execute()
            else:
                supabase.table("credenciales").delete().eq("id", c["id"]).execute()
    for k in range(0, len(ids), 100):
        lote = ids[k:k + 100]
        supabase.table("asistencias").delete().in_("integrante_id", lote).execute()
        supabase.table("integrantes_base").delete().in_("id", lote).execute()
    borrar_fotos([i.get("foto_url") for i in integrantes])

def guardar_edicion_integrante(orig, datos, foto=None, quitar_foto=False):
    datos = dict(datos)
    foto_vieja = orig.get("foto_url")
    if foto is not None:
        path = f'{datos["base_id"]}/{uuid.uuid4().hex}.jpg'
        datos["foto_url"] = subir_archivo(BUCKET_FOTOS, path, procesar_foto(foto), "image/jpeg")
    elif quitar_foto:
        datos["foto_url"] = None
    supabase.table("integrantes_base").update(datos).eq("id", orig["id"]).execute()
    if datos["dni"] != str(orig["dni"]).strip():
        liberar_credencial(orig)
    if foto is not None or quitar_foto:
        borrar_fotos([foto_vieja])

def obtener_credencial(token):
    token_hash = hash_texto(token)
    filas = (supabase.table("credenciales")
             .select("id,integrante_id,persona_key,estado,plantilla_id,emitida_en")
             .eq("token_hash", token_hash).limit(1).execute().data or [])
    return filas[0] if filas else None

def descargar_bytes(url):
    r = requests.get(url, timeout=25)
    r.raise_for_status()
    return r.content

@st.cache_data(ttl=600, show_spinner=False)
def bytes_plantilla(path):
    return descargar_bytes(url_plantilla(path))

def imagen_plantilla(path):
    im = Image.open(io.BytesIO(bytes_plantilla(path)))
    im.load()
    return im.convert("RGBA")

def precargar_fotos(urls, max_hilos=8):
    def bajar(u):
        try:
            im = Image.open(io.BytesIO(descargar_bytes(u)))
            im.load()
            im = im.convert("RGB")
            im.thumbnail((600, 600))
            return u, im
        except Exception:
            return u, None
    with ThreadPoolExecutor(max_workers=max_hilos) as ex:
        return dict(ex.map(bajar, urls))

def mapa_estados_credenciales():
    filas = traer_todo(lambda: supabase.table("credenciales")
                       .select("id,persona_key,estado,token_hash").order("id"))
    return {f["persona_key"]: f for f in filas}

def plantilla_activa():
    activas = [p for p in listar_plantillas() if p.get("activa")]
    if activas:
        return activas[0]
    return {"id": None, "nombre": "Plantilla predeterminada",
            "frontal_path": None, "posterior_path": None}

def _png(imagen):
    b = io.BytesIO()
    imagen.save(b, format="PNG")
    return b.getvalue()

def generar_lote(personas, plantilla, dni_bases, progreso=None, existentes=None):
    fotos = precargar_fotos(list({p["foto_url"] for p in personas if p.get("foto_url")}))
    resultados, errores = [], []
    for i, p in enumerate(personas, start=1):
        try:
            dni_p = str(p["dni"]).strip()
            if existentes is not None:
                cred = existentes[dni_p]
                if not token_reproducible(dni_p, cred):
                    raise ValueError("credencial emitida con una versi\u00f3n anterior")
                cred_id = cred["id"]
            else:
                cred_id = str(uuid.uuid4())
            token = token_credencial(dni_p, cred_id)
            url_qr = f"{APP_PUBLIC_URL}/?verificar={quote(token)}"
            info = dni_bases.get(dni_p, [])
            principal = next((b for b in info if b["id"] == p.get("base_id")), info[0] if info else {})
            datos = dict(p)
            datos["nombre_base"] = ", ".join(b["nombre_base"] for b in info)
            datos["provincia"] = principal.get("provincia") or ""
            datos["distrito"] = principal.get("distrito") or ""
            foto = fotos.get(p.get("foto_url"))
            frente = _png(componer_credencial(datos, plantilla, url_qr, "frontal", foto_img=foto))
            reverso = None
            if plantilla.get("posterior_path"):
                reverso = _png(componer_credencial(datos, plantilla, url_qr, "posterior", foto_img=foto))
            resultados.append({"persona": p, "token": token, "cred_id": cred_id,
                               "frente_png": frente, "reverso_png": reverso})
        except Exception as e:
            logger.warning("Credencial no generada (integrante %s): %r", p.get("id"), e)
            errores.append(p)
        if progreso:
            progreso(i, len(personas))
    return resultados, errores

def guardar_credenciales_lote(resultados, plantilla_id):
    ahora = datetime.now(timezone.utc).isoformat()
    por_dni = {str(r["persona"]["dni"]).strip(): r for r in resultados}
    claves = {}
    for d in por_dni:
        claves[clave_persona(d)] = d
        claves[clave_persona_legacy(d)] = d
    lista = list(claves.keys())
    existentes = {}
    for i in range(0, len(lista), 40):
        filas = (supabase.table("credenciales").select("id,persona_key")
                 .in_("persona_key", lista[i:i + 40]).execute().data or [])
        for f in filas:
            existentes[claves[f["persona_key"]]] = f["id"]
    nuevos = []
    for dni, r in por_dni.items():
        fila = {"id": r["cred_id"], "integrante_id": r["persona"]["id"], "persona_key": clave_persona(dni),
                "token_hash": hash_texto(r["token"]), "estado": "vigente",
                "plantilla_id": plantilla_id, "emitida_en": ahora}
        if dni in existentes:
            escribir_credencial(existentes[dni], fila)
        else:
            nuevos.append(fila)
    for i in range(0, len(nuevos), 100):
        supabase.table("credenciales").insert(nuevos[i:i + 100]).execute()

def zip_credenciales(resultados):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for i, r in enumerate(resultados, start=1):
            p = r["persona"]
            nombre = (f'{i:03d}_{nombre_archivo_seguro(p.get("apellidos", ""))}_'
                      f'{nombre_archivo_seguro(p.get("nombres", ""))}_{nombre_archivo_seguro(p["dni"])}')
            z.writestr(nombre + "_frente.png", r["frente_png"])
            if r.get("reverso_png"):
                z.writestr(nombre + "_reverso.png", r["reverso_png"])
    return buf.getvalue()

def pdf_credenciales(resultados, hoja_a4=False):
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.lib.pagesizes import A4
    mm = 2.83465
    cw, ch = 85.6 * mm, 54 * mm
    buf = io.BytesIO()
    if not hoja_a4:
        c = canvas.Canvas(buf, pagesize=(cw, ch))
        for r in resultados:
            for clave in ("frente_png", "reverso_png"):
                png = r.get(clave)
                if not png:
                    continue
                w_im, h_im = Image.open(io.BytesIO(png)).size
                pw = (85.6 if w_im >= h_im else 54) * mm
                ph = pw * h_im / w_im
                c.setPageSize((pw, ph))
                c.drawImage(ImageReader(io.BytesIO(png)), 0, 0, width=pw, height=ph)
                c.showPage()
        c.save()
        return buf.getvalue()
    pw_a4, ph_a4 = A4
    cols, filas = 2, 4
    gap = 5 * mm
    x0 = (pw_a4 - (cols * cw + (cols - 1) * gap)) / 2
    alto_total = filas * ch + (filas - 1) * gap
    y_top = ph_a4 - (ph_a4 - alto_total) / 2
    c = canvas.Canvas(buf, pagesize=A4)

    def dibujar(imagenes, espejo):
        por_pagina = cols * filas
        for ini in range(0, len(imagenes), por_pagina):
            for k, png in enumerate(imagenes[ini:ini + por_pagina]):
                fila, col = divmod(k, cols)
                if espejo:
                    col = cols - 1 - col
                x = x0 + col * (cw + gap)
                y = y_top - (fila + 1) * ch - fila * gap
                c.drawImage(ImageReader(io.BytesIO(png)), x, y, width=cw, height=ch,
                            preserveAspectRatio=True, anchor="c")
                c.setStrokeColorRGB(0.7, 0.7, 0.7)
                c.setLineWidth(0.3)
                c.rect(x, y, cw, ch)
            c.showPage()

    dibujar([r["frente_png"] for r in resultados], False)
    reversos = [r["reverso_png"] for r in resultados if r.get("reverso_png")]
    if reversos:
        dibujar(reversos, True)
    c.save()
    return buf.getvalue()

def crear_qr(url):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")

@lru_cache(maxsize=128)
def cargar_fuente(tamano, negrita=False):
    def ruta(carpeta, normal, bold):
        return f"{carpeta}/{bold if negrita else normal}"
    candidatos = [
        ruta("/usr/share/fonts/truetype/dejavu", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
        ruta("/usr/share/fonts/truetype/liberation", "LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
        ruta("/usr/share/fonts/truetype/liberation2", "LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
        ruta("/usr/share/fonts/truetype/freefont", "FreeSans.ttf", "FreeSansBold.ttf"),
        ruta("/usr/share/fonts/truetype/noto", "NotoSans-Regular.ttf", "NotoSans-Bold.ttf"),
        ruta("/usr/share/fonts/opentype/noto", "NotoSans-Regular.ttf", "NotoSans-Bold.ttf"),
        "DejaVuSans-Bold.ttf" if negrita else "DejaVuSans.ttf",
        "LiberationSans-Bold.ttf" if negrita else "LiberationSans-Regular.ttf",
        "arialbd.ttf" if negrita else "arial.ttf",
    ]
    try:
        import matplotlib
        base = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        candidatos.append(os.path.join(base, "DejaVuSans-Bold.ttf" if negrita else "DejaVuSans.ttf"))
    except Exception:
        pass
    for r in candidatos:
        try:
            return ImageFont.truetype(r, tamano)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=tamano)
    except Exception:
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

DISENOS_PREDEFINIDOS = {
    "Marcos y l\u00edneas (ejemplo Puno)": {
        "version": 1,
        "foto": {"x": 0.0410, "y": 0.3037, "w": 0.2201, "h": 0.3750},
        "qr": {"x": 0.8268, "y": 0.5381, "w": 0.1458, "h": 0.1992},
        "texto": {
            "color": "#111111", "tamano": 0.033, "negrita": True, "margen": 0.010,
            "campos": [
                {"campo": "nombres",   "x": 0.4557, "y": 0.4229, "ancho": 0.2975},
                {"campo": "apellidos", "x": 0.4557, "y": 0.4785, "ancho": 0.2975},
                {"campo": "dni",       "x": 0.4557, "y": 0.5322, "ancho": 0.2975},
                {"campo": "cargo",     "x": 0.4557, "y": 0.5879, "ancho": 0.2975},
                {"campo": "base",      "x": 0.4557, "y": 0.6406, "ancho": 0.2975},
                {"campo": "provincia", "x": 0.4557, "y": 0.6924, "ancho": 0.2975},
                {"campo": "distrito",  "x": 0.4557, "y": 0.7383, "ancho": 0.2975},
            ],
        },
    },
}

DISENO_POR_DEFECTO = "Marcos y l\u00edneas (ejemplo Puno)"

@st.cache_data(ttl=300, show_spinner=False)
def cargar_diseno(plantilla_id):
    if not plantilla_id:
        return None
    try:
        datos = supabase.storage.from_(BUCKET_PLANTILLAS).download(f"{plantilla_id}/diseno.json")
        return json.loads(datos.decode("utf-8")) or None
    except Exception:
        return None

def guardar_diseno(plantilla_id, diseno):
    ruta = f"{plantilla_id}/diseno.json"
    if not diseno:
        try:
            supabase.storage.from_(BUCKET_PLANTILLAS).remove([ruta])
        except Exception:
            pass
    else:
        contenido = json.dumps(diseno, ensure_ascii=False).encode("utf-8")
        try:
            subir_archivo(BUCKET_PLANTILLAS, ruta, contenido, "application/json")
        except Exception:
            subir_archivo(BUCKET_PLANTILLAS, ruta, contenido, "text/plain")
    cargar_diseno.clear()

def escribir_en_linea(draw, texto, x, y_base, ancho_max, tam, color, negrita=True):
    t = tam
    fuente = cargar_fuente(t, negrita)
    minimo = max(10, int(tam * 0.55))
    while t > minimo and draw.textbbox((0, 0), texto, font=fuente)[2] > ancho_max:
        t -= 1
        fuente = cargar_fuente(t, negrita)
    if draw.textbbox((0, 0), texto, font=fuente)[2] > ancho_max:
        while len(texto) > 1 and draw.textbbox((0, 0), texto + "\u2026", font=fuente)[2] > ancho_max:
            texto = texto[:-1]
        texto = texto.rstrip() + "\u2026"
    try:
        draw.text((x, y_base), texto, fill=color, font=fuente, anchor="ls")
    except Exception:
        alto = draw.textbbox((0, 0), texto, font=fuente)[3]
        draw.text((x, y_base - alto), texto, fill=color, font=fuente)

def aplicar_diseno(lienzo, integrante, qr_url, diseno, foto_img=None):
    w, h = lienzo.size
    draw = ImageDraw.Draw(lienzo)
    f = diseno.get("foto")
    if f:
        fx, fy = int(f["x"] * w), int(f["y"] * h)
        fw, fh = max(1, int(f["w"] * w)), max(1, int(f["h"] * h))
        foto = None
        try:
            if foto_img is not None:
                foto = foto_img.convert("RGB")
            elif integrante.get("foto_url"):
                foto = descargar_imagen(integrante["foto_url"]).convert("RGB")
        except Exception:
            foto = None
        if foto is not None:
            lienzo.paste(ImageOps.fit(foto, (fw, fh), centering=(0.5, 0.35)), (fx, fy))
    q = diseno.get("qr")
    if q:
        bx, by = int(q["x"] * w), int(q["y"] * h)
        bw, bh = max(1, int(q["w"] * w)), max(1, int(q["h"] * h))
        lado_qr = min(bw, bh)
        qr = crear_qr(qr_url).resize((lado_qr, lado_qr))
        lienzo.alpha_composite(qr.convert("RGBA"), (bx + (bw - lado_qr) // 2, by + (bh - lado_qr) // 2))
    t = diseno.get("texto") or {}
    color = t.get("color", "#111111")
    tam = max(10, int(float(t.get("tamano", 0.033)) * h))
    margen = int(float(t.get("margen", 0.006)) * h)
    valores = {
        "nombres": integrante.get("nombres"), "apellidos": integrante.get("apellidos"),
        "nombre_completo": nombre_completo(integrante), "dni": integrante.get("dni"),
        "cargo": integrante.get("cargo") or "Sin cargo", "base": integrante.get("nombre_base"),
        "provincia": integrante.get("provincia"), "distrito": integrante.get("distrito"),
    }
    for c in t.get("campos", []):
        texto = str(valores.get(c.get("campo")) or "").strip()
        if texto:
            escribir_en_linea(draw, texto, int(c["x"] * w), int(c["y"] * h) - margen,
                              max(10, int(c["ancho"] * w)), tam, color, t.get("negrita", True))
    return lienzo.convert("RGB")

def foto_demo():
    im = Image.new("RGB", (400, 500), "#9DB7D5")
    d = ImageDraw.Draw(im)
    d.ellipse((130, 90, 270, 260), fill="#D9A877")
    d.ellipse((60, 290, 340, 640), fill="#35506E")
    return im

def eliminar_plantilla(p):
    pid = p["id"]
    supabase.table("credenciales").update({"plantilla_id": None}).eq("plantilla_id", pid).execute()
    supabase.table("plantillas_credenciales").delete().eq("id", pid).execute()
    rutas = [r for r in (p.get("frontal_path"), p.get("posterior_path"), f"{pid}/diseno.json") if r]
    try:
        supabase.storage.from_(BUCKET_PLANTILLAS).remove(rutas)
    except Exception as e:
        logger.warning("No se pudieron borrar los archivos de la plantilla %s: %r", pid, e)
    cargar_diseno.clear()
    bytes_plantilla.clear()

def bloque_eliminar(p):
    aviso = ("Se borrar\u00e1n la plantilla, sus im\u00e1genes y su distribuci\u00f3n. Las credenciales ya emitidas "
             "y sus QR siguen funcionando, pero no podr\u00e1s volver a generarlas con este dise\u00f1o.")
    if p.get("activa"):
        aviso += " Esta es la plantilla activa: mientras no actives otra, se usar\u00e1 el dise\u00f1o predeterminado."
    st.warning(f'\u00bfEliminar la plantilla \u00ab{p["nombre"]}\u00bb? ' + aviso)
    k1, k2 = st.columns(2)
    if k1.button("S\u00ed, eliminar", key=f"del_si_{p['id']}", type="primary"):
        try:
            eliminar_plantilla(p)
            st.session_state.pop(f"mostrar_del_{p['id']}", None)
            st.session_state["mostrar_msg_plantilla"] = f'Plantilla \u00ab{p["nombre"]}\u00bb eliminada.'
            st.rerun()
        except Exception as e:
            error_supabase("No se pudo eliminar la plantilla.", e)
    if k2.button("Cancelar", key=f"del_no_{p['id']}"):
        st.session_state.pop(f"mostrar_del_{p['id']}", None)
        st.rerun()

DISENO_AUTO = "Autom\u00e1tico (distribuci\u00f3n est\u00e1ndar)"
DISENO_JSON = "Personalizado (avanzado)"

def editor_diseno(p):
    actual = cargar_diseno(p["id"])
    opciones = [DISENO_AUTO] + list(DISENOS_PREDEFINIDOS.keys()) + [DISENO_JSON]
    if actual is None:
        indice = opciones.index(DISENO_POR_DEFECTO)
        st.caption("Esta plantilla a\u00fan no tiene una distribuci\u00f3n guardada: se est\u00e1 usando "
                   f"\u00ab{DISENO_POR_DEFECTO}\u00bb. Pulsa \u00abGuardar distribuci\u00f3n\u00bb para fijarla.")
    elif actual.get("modo") == "auto":
        indice = 0
    else:
        indice = len(opciones) - 1
        for i, nombre in enumerate(DISENOS_PREDEFINIDOS, start=1):
            if DISENOS_PREDEFINIDOS[nombre] == actual:
                indice = i
    sel = st.selectbox("Distribuci\u00f3n", opciones, index=indice, key=f"dis_sel_{p['id']}")
    if sel == DISENO_AUTO:
        diseno = {"modo": "auto"}
    elif sel in DISENOS_PREDEFINIDOS:
        diseno = copy.deepcopy(DISENOS_PREDEFINIDOS[sel])
    else:
        base_json = actual if (actual and "modo" not in actual) else next(iter(DISENOS_PREDEFINIDOS.values()))
        texto = st.text_area("Dise\u00f1o (JSON, medidas entre 0 y 1)",
                             value=json.dumps(base_json, indent=1, ensure_ascii=False),
                             height=320, key=f"dis_json_{p['id']}")
        try:
            diseno = json.loads(texto)
        except ValueError:
            st.error("El JSON no es v\u00e1lido.")
            return
    c1, c2 = st.columns(2)
    if c1.button("Vista previa", key=f"dis_prev_{p['id']}"):
        muestra = {"nombres": "Juan Carlos", "apellidos": "Quispe Mamani", "dni": "12345678",
                   "cargo": "Coordinador de base", "nombre_base": "Base Los Andes Juliaca",
                   "provincia": "San Rom\u00e1n", "distrito": "Juliaca"}
        try:
            img = componer_credencial(muestra, dict(p, diseno=diseno), "https://ejemplo.pe/?verificar=demo",
                                      "frontal", foto_img=foto_demo())
            st.image(img, caption="Vista previa con datos de ejemplo")
        except Exception as e:
            error_supabase("No se pudo generar la vista previa.", e)
    if c2.button("Guardar distribuci\u00f3n", key=f"dis_guardar_{p['id']}"):
        try:
            guardar_diseno(p["id"], diseno)
            st.success("Distribuci\u00f3n guardada. Se usar\u00e1 en las pr\u00f3ximas credenciales.")
        except Exception as e:
            error_supabase("No se pudo guardar la distribuci\u00f3n.", e)

def componer_credencial(integrante, plantilla, qr_url, lado="frontal", foto_img=None):
    path = plantilla.get("frontal_path") if lado == "frontal" else plantilla.get("posterior_path")
    if path:
        lienzo = imagen_plantilla(path)
    else:
        lienzo = Image.new("RGBA", (1011, 638), "#F4F7FB")
        d = ImageDraw.Draw(lienzo)
        d.rounded_rectangle((8, 8, 1003, 630), radius=28, outline="#163B65", width=12)
        d.rectangle((12, 12, 999, 125), fill="#163B65")
        d.text((45, 35), "CREDENCIAL DE IDENTIFICACI\u00d3N", fill="white",
               font=cargar_fuente(38, True))
        d.text((45, 82), "REGISTRO DE BASES Y COMANDOS", fill="#E7EEF7",
               font=cargar_fuente(20))
    lienzo = ImageOps.exif_transpose(lienzo).convert("RGBA")
    w, h = lienzo.size
    draw = ImageDraw.Draw(lienzo)
    diseno = None
    if lado == "frontal":
        diseno = plantilla["diseno"] if "diseno" in plantilla else cargar_diseno(plantilla.get("id"))
        if diseno is None and plantilla.get("frontal_path"):
            diseno = DISENOS_PREDEFINIDOS[DISENO_POR_DEFECTO]
        elif diseno and diseno.get("modo") == "auto":
            diseno = None

    if lado == "posterior":
        draw.text((int(w*.06), int(h*.18)), "VERIFICACI\u00d3N DE CREDENCIAL",
                  fill="#17324D", font=cargar_fuente(max(18, int(h*.045)), True))
        draw.text((int(w*.06), int(h*.30)),
                  "Escanea el c\u00f3digo QR para consultar su vigencia.",
                  fill="#202020", font=cargar_fuente(max(14, int(h*.027))))
        qr = crear_qr(qr_url)
        qsize = int(min(w, h) * .48)
        qr = qr.resize((qsize, qsize))
        lienzo.alpha_composite(qr.convert("RGBA"), (int(w*.66), int(h*.28)))
        return lienzo.convert("RGB")

    if diseno:
        return aplicar_diseno(lienzo, integrante, qr_url, diseno, foto_img)

    margen = int(w * .055)
    foto_size = int(min(w, h) * .36)
    foto_x, foto_y = margen, int(h * .29)
    foto_url = integrante.get("foto_url")
    if foto_url or foto_img is not None:
        try:
            foto = (foto_img if foto_img is not None else descargar_imagen(foto_url)).convert("RGB")
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
        f"Ubicaci\u00f3n: {integrante.get('provincia') or ''} / {integrante.get('distrito') or ''}",
    ]
    for campo in campos:
        for linea in ajustar_texto(draw, campo, fuente, ancho_texto)[:2]:
            draw.text((texto_x, y), linea, fill="#222222", font=fuente)
            y += int(h*.052)
    return lienzo.convert("RGB")

# ---------------------------------------------------------------------
# VERIFICACI\u00d3N P\u00daBLICA DEL QR
# ---------------------------------------------------------------------
st.title("\U0001f5f3\ufe0f Registro de Bases y Comandos")
token_qr = st.query_params.get("verificar")
if token_qr:
    st.subheader("Verificaci\u00f3n de credencial")
    try:
        cred = obtener_credencial(str(token_qr))
        if not cred:
            st.error("C\u00f3digo no v\u00e1lido o credencial no encontrada.")
        elif cred["estado"] != "vigente":
            st.warning("Esta credencial no est\u00e1 vigente.")
        else:
            fila = (supabase.table("integrantes_base")
                    .select("nombres,apellidos,cargo,base_id,dni,foto_url")
                    .eq("id", cred["integrante_id"]).limit(1).execute().data or [])
            if not fila:
                st.warning("No se encontr\u00f3 el registro asociado.")
            else:
                persona = fila[0]
                nombres_bases = [b["nombre_base"] for b in datos_bases_por_dni(persona["dni"])]
                st.success("Credencial vigente")
                if persona.get("foto_url"):
                    try:
                        st.image(persona["foto_url"], width=220, caption="Fotograf\u00eda registrada")
                    except Exception:
                        pass
                st.write(f"**Integrante:** {nombre_completo(persona)}")
                st.write(f"**Cargo:** {persona.get('cargo') or 'Sin cargo'}")
                st.write(f"**Bases:** {', '.join(nombres_bases) if nombres_bases else 'No especificadas'}")
                st.caption(f"Emitida el {str(cred.get('emitida_en', ''))[:10]}. "
                           "Por privacidad, esta consulta p\u00fablica no muestra el DNI ni el tel\u00e9fono.")
    except Exception as e:
        error_supabase("No se pudo verificar la credencial.", e)
    st.stop()

st.caption("Gesti\u00f3n de bases, integrantes, reuniones, asistencia y credenciales verificables.")

# ---------------------------------------------------------------------
# ACCESO
# ---------------------------------------------------------------------
if st.session_state.base_id is None and not st.session_state.admin_autenticado:
    st.subheader("Acceso al sistema")
    modo = st.radio("Tipo de acceso", ["Responsable de base", "Administrador"], horizontal=True)
    if modo == "Responsable de base":
        with st.form("login_base"):
            usuario_login = st.text_input("Usuario").strip()
            password_login = st.text_input("Contrase\u00f1a", type="password")
            entrar = st.form_submit_button("Ingresar", use_container_width=True)
        clave_rl = "base:" + usuario_login.lower()
        espera = segundos_bloqueo(clave_rl) if entrar else 0
        if entrar and espera:
            st.error(f"Demasiados intentos fallidos. Intenta de nuevo en {espera // 60 + 1} minuto(s).")
        elif entrar:
            try:
                r = (supabase.table("bases_campana")
                     .select("id,nombre_base,provincia,distrito,usuario,password_hash")
                     .eq("usuario", usuario_login).limit(1).execute())
                hash_guardado = r.data[0].get("password_hash", "") if r.data else HASH_FICTICIO
                if verificar_password(password_login, hash_guardado) and r.data:
                    limpiar_fallos(clave_rl)
                    b = r.data[0]
                    st.session_state.base_id = b["id"]
                    st.session_state.base_nombre = b["nombre_base"]
                    st.session_state.base_provincia = b.get("provincia") or ""
                    st.session_state.base_distrito = b.get("distrito") or ""
                    st.rerun()
                else:
                    registrar_fallo(clave_rl)
                    st.error("Usuario o contrase\u00f1a incorrectos.")
            except Exception as e:
                error_supabase("No se pudo comprobar el acceso.", e)
    else:
        with st.form("login_admin"):
            u = st.text_input("Usuario administrador")
            p = st.text_input("Contrase\u00f1a de administrador", type="password")
            entrar_admin = st.form_submit_button("Ingresar como administrador", use_container_width=True)
        if entrar_admin:
            espera = segundos_bloqueo("admin")
            if espera:
                st.error(f"Demasiados intentos fallidos. Intenta de nuevo en {espera // 60 + 1} minuto(s).")
            elif admin_valido(u, p):
                limpiar_fallos("admin")
                st.session_state.admin_autenticado = True
                st.session_state.es_admin = True
                st.rerun()
            else:
                registrar_fallo("admin")
                st.error("Credenciales incorrectas o Secrets de administrador no configurados.")

# ---------------------------------------------------------------------
# PANEL ADMINISTRADOR
# ---------------------------------------------------------------------
if st.session_state.admin_autenticado and st.session_state.es_admin:
    st.success("Sesi\u00f3n de administrador")
    if not str(st.secrets.get("ADMIN_PASSWORD_HASH", "")).strip():
        st.warning("Est\u00e1s usando ADMIN_PASSWORD en texto plano. Conviene reemplazarlo por ADMIN_PASSWORD_HASH en Secrets.")
    tabs = st.tabs(["Resumen", "Crear base", "Bases e integrantes", "Administrar bases",
                    "Reuniones y asistencia", "Exportar",
                    "Credenciales QR", "Credenciales en lote", "Credenciales generadas", "Plantillas"])

    with tabs[0]:
        try:
            bases = cargar_bases()
            integrantes = cargar_integrantes()
            
            # --- MÉTRICAS PRINCIPALES ---
            st.subheader("📊 Panel de Control")
            c1, c2, c3 = st.columns(3)
            c1.metric("Bases registradas", len(bases))
            c2.metric("Integrantes registrados", len(integrantes))
            
            try:
                creds = traer_todo(lambda: supabase.table("credenciales").select("id,estado").order("id"))
                vigentes = sum(1 for c in creds if c.get("estado") == "vigente")
                c3.metric("Credenciales vigentes", vigentes)
            except Exception:
                c3.metric("Credenciales vigentes", "N/A")

            if bases:
                # --- GRÁFICO DE BARRAS: BASES POR PROVINCIA ---
                st.divider()
                df_bases = pd.DataFrame([{
                    "Provincia": b.get("provincia") or "Sin asignar",
                } for b in bases])
                
                st.write("**Bases por Provincia**")
                st.bar_chart(df_bases["Provincia"].value_counts(), color="#163B65")

                # --- GRÁFICO CIRCULAR: INTEGRANTES POR CARGO ---
                if integrantes:
                    st.divider()
                    df_integrantes = pd.DataFrame([{
                        "Cargo": f.get("cargo") or "Sin cargo",
                    } for f in integrantes])
                    conteo_cargos = df_integrantes["Cargo"].value_counts().reset_index()
                    conteo_cargos.columns = ["Cargo", "Cantidad"]
                    
                    chart = alt.Chart(conteo_cargos).mark_arc(innerRadius=50).encode(
                        theta=alt.Theta(field="Cantidad", type="quantitative"),
                        color=alt.Color(field="Cargo", type="nominal"),
                        tooltip=["Cargo", "Cantidad"]
                    ).properties(title="Distribución de Integrantes por Cargo", height=300)
                    st.altair_chart(chart, use_container_width=True)

                    # --- GRÁFICO DE LÍNEAS: REGISTROS POR DÍA ---
                    st.divider()
                    df_fechas = pd.DataFrame([{
                        "Fecha": str(f.get("fecha_registro", ""))[:10],
                    } for f in integrantes if f.get("fecha_registro")])
                    if not df_fechas.empty:
                        registros_por_dia = df_fechas["Fecha"].value_counts().sort_index().tail(7)
                        st.write("**Registros nuevos (últimos 7 días)**")
                        st.line_chart(registros_por_dia, color="#2E7D32")

                # --- TABLAS DE DETALLE ---
                st.divider()
                st.write("**Detalle de Bases**")
                df_tabla = pd.DataFrame([{
                    "Base": b.get("nombre_base", ""),
                    "Provincia": b.get("provincia") or "Sin asignar",
                    "Distrito": b.get("distrito") or "Sin asignar",
                    "Usuario": b.get("usuario", "")
                } for b in bases])
                st.dataframe(df_tabla, use_container_width=True, hide_index=True)
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
            password = st.text_input("Contrase\u00f1a inicial (m\u00ednimo 10 caracteres, con letras y n\u00fameros)", type="password")
            confirmar = st.text_input("Confirmar contrase\u00f1a", type="password")
            acepta = st.checkbox("Confirmo que estoy autorizado para crear esta cuenta.")
            crear = st.form_submit_button("Crear base")
        if crear:
            if not nombre.strip() or provincia not in DISTRITOS_PUNO or distrito not in ds:
                st.warning("Completa el nombre, la provincia y el distrito.")
            elif not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", usuario):
                st.warning("El usuario debe tener de 3 a 40 caracteres v\u00e1lidos.")
            elif not (10 <= len(password) <= 64 and re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
                st.warning("La contrase\u00f1a debe tener de 10 a 64 caracteres, con al menos una letra y un n\u00famero.")
            elif password != confirmar:
                st.warning("Las contrase\u00f1as no coinciden.")
            elif not acepta:
                st.warning("Confirma la autorizaci\u00f3n.")
            else:
                try:
                    existe = supabase.table("bases_campana").select("id").eq("usuario", usuario).limit(1).execute()
                    if existe.data:
                        st.error("Ese usuario ya est\u00e1 ocupado.")
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
                mapa = {f'{b["nombre_base"]} \u2014 {b.get("provincia") or ""}/{b.get("distrito") or ""} (ID {b["id"]})': b for b in bases}
                label = st.selectbox("Seleccionar base", list(mapa.keys()))
                bsel = mapa[label]
                miembros = cargar_integrantes(bsel["id"])
                st.write(f'**Integrantes:** {len(miembros)}')
                buscar = st.text_input("Buscar por nombre, apellido o DNI", key="buscar_admin")
                filtrados = [f for f in miembros if buscar.lower().strip() in
                             (nombre_completo(f) + " " + str(f.get("dni", ""))).lower()]
                if filtrados:
                    st.dataframe(dataframe_integrantes(filtrados), use_container_width=True, hide_index=True)
                    botones_lista(bsel, filtrados, "adm")
                else:
                    st.info("No hay coincidencias.")
            else:
                st.info("No hay bases registradas.")
        except Exception as e:
            error_supabase("No se pudieron consultar las bases e integrantes.", e)

    with tabs[3]:
        st.subheader("Administrar bases")
        st.caption("Corrige datos, restablece contrase\u00f1as y elimina bases o integrantes.")
        try:
            msg_adm = st.session_state.pop("mostrar_msg_admin", None)
            if msg_adm:
                st.success(msg_adm)
            bases_adm = cargar_bases()
            if not bases_adm:
                st.info("Primero crea una base.")
            else:
                mapa_adm = {f'{b["nombre_base"]} \u2014 {b.get("provincia") or "sin provincia"} / {b.get("distrito") or "sin distrito"} (ID {b["id"]})': b
                            for b in bases_adm}
                bad = mapa_adm[st.selectbox("Base", list(mapa_adm.keys()), key="admin_adm_base")]
                bid = bad["id"]
                miembros = cargar_integrantes(bid)

                st.markdown("**Datos de la base**")
                nb = st.text_input("Nombre de la base o comando", value=bad["nombre_base"], key=f"admin_nb_{bid}")
                provs = ["Seleccionar provincia"] + PROVINCIAS
                pv = st.selectbox("Provincia", provs, key=f"admin_pv_{bid}",
                                  index=provs.index(bad["provincia"]) if bad.get("provincia") in PROVINCIAS else 0)
                dss = sorted(DISTRITOS_PUNO.get(pv, []))
                dops = ["Seleccionar distrito"] + dss
                ds = st.selectbox("Distrito", dops, key=f"admin_ds_{bid}_{pv}", disabled=not dss,
                                  index=dops.index(bad["distrito"]) if bad.get("distrito") in dss else 0)
                us = st.text_input("Usuario de la base", value=bad["usuario"], key=f"admin_us_{bid}").strip()
                if st.button("Guardar datos de la base", key=f"admin_gb_{bid}"):
                    if not nb.strip() or pv not in DISTRITOS_PUNO or ds not in dss:
                        st.warning("Completa el nombre, la provincia y el distrito.")
                    elif not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", us):
                        st.warning("El usuario debe tener de 3 a 40 caracteres v\u00e1lidos.")
                    elif (supabase.table("bases_campana").select("id").eq("usuario", us)
                          .neq("id", bid).limit(1).execute().data):
                        st.error("Ese usuario ya est\u00e1 ocupado por otra base.")
                    else:
                        supabase.table("bases_campana").update({
                            "nombre_base": nb.strip(), "provincia": pv, "distrito": ds, "usuario": us
                        }).eq("id", bid).execute()
                        st.session_state["mostrar_msg_admin"] = "Datos de la base actualizados."
                        st.rerun()

                st.divider()
                st.markdown("**Contrase\u00f1a del secretario general**")
                st.caption(f'Usuario: {bad["usuario"]}. \u00dasalo si perdieron la contrase\u00f1a; la anterior deja de funcionar.')
                if st.button("Generar contrase\u00f1a nueva", type="primary", key=f"admin_pw_{bid}"):
                    nueva = generar_clave()
                    supabase.table("bases_campana").update({"password_hash": crear_hash(nueva)}).eq("id", bid).execute()
                    limpiar_fallos("base:" + str(bad["usuario"]).lower())
                    st.success("Contrase\u00f1a restablecida. Entr\u00e9gasela al secretario general.")
                    st.code(nueva, language=None)
                    st.caption("C\u00f3piala ahora: no se vuelve a mostrar. Si la pierdes, genera otra.")
                with st.expander("Elegir yo la contrase\u00f1a"):
                    pa = st.text_input("Contrase\u00f1a nueva (m\u00ednimo 10 caracteres, con letras y n\u00fameros)",
                                       type="password", key=f"admin_pa_{bid}")
                    pb = st.text_input("Confirmar contrase\u00f1a", type="password", key=f"admin_pb_{bid}")
                    if st.button("Guardar contrase\u00f1a", key=f"admin_pg_{bid}"):
                        if not (10 <= len(pa) <= 64 and re.search(r"[A-Za-z]", pa) and re.search(r"\d", pa)):
                            st.warning("La contrase\u00f1a debe tener de 10 a 64 caracteres, con al menos una letra y un n\u00famero.")
                        elif pa != pb:
                            st.warning("Las contrase\u00f1as no coinciden.")
                        else:
                            supabase.table("bases_campana").update({"password_hash": crear_hash(pa)}).eq("id", bid).execute()
                            limpiar_fallos("base:" + str(bad["usuario"]).lower())
                            st.success("Contrase\u00f1a actualizada. La anterior ya no funciona.")

                st.divider()
                st.markdown(f"**Integrantes de la base** ({len(miembros)})")
                if not miembros:
                    st.info("Esta base no tiene integrantes.")
                else:
                    bq = st.text_input("Buscar por nombre o DNI", key=f"admin_bq_{bid}").strip().lower()
                    filtrados_adm = [f for f in miembros
                                     if bq in (nombre_completo(f) + " " + str(f.get("dni", ""))).lower()]
                    if not filtrados_adm:
                        st.info("No hay coincidencias.")
                    else:
                        etiquetas = {f'{f.get("apellidos", "")}, {f.get("nombres", "")} (DNI {f.get("dni", "")})': f
                                     for f in filtrados_adm}
                        m = etiquetas[st.selectbox("Integrante", list(etiquetas.keys()), key=f"admin_im_{bid}")]
                        mid = m["id"]
                        if m.get("foto_url"):
                            st.image(m["foto_url"], width=110)
                        if credencial_de_dni(m["dni"]):
                            st.caption("Esta persona tiene credencial. Si cambias el DNI, se elimina y hay que generar una nueva.")
                        destinos = {f'{b["nombre_base"]} (ID {b["id"]})': b["id"] for b in bases_adm}
                        cargo_act = m.get("cargo") or ""
                        with st.form(f"admin_form_ed_{mid}"):
                            e_nom = st.text_input("Nombres", value=m.get("nombres", ""), key=f"admin_en_{mid}")
                            e_ape = st.text_input("Apellidos", value=m.get("apellidos", ""), key=f"admin_ea_{mid}")
                            e_dni = st.text_input("DNI (8 d\u00edgitos)", value=str(m.get("dni", "")), key=f"admin_ed_{mid}")
                            e_cel = st.text_input("Celular (9 a 15 d\u00edgitos)", value=str(m.get("celular", "")),
                                                  key=f"admin_ec_{mid}")
                            e_csel = st.selectbox("Cargo o condici\u00f3n", CARGOS, key=f"admin_cs_{mid}",
                                                  index=CARGOS.index(cargo_act) if cargo_act in CARGOS else len(CARGOS) - 1)
                            e_otro = st.text_input("Si elegiste \u00abOtro\u00bb, especifica el cargo", key=f"admin_co_{mid}",
                                                   value="" if cargo_act in CARGOS else cargo_act)
                            e_base = st.selectbox("Base del integrante (c\u00e1mbiala para moverlo)", list(destinos.keys()),
                                                  index=list(destinos.values()).index(m["base_id"]) if m["base_id"] in destinos.values() else 0,
                                                  key=f"admin_eb_{mid}")
                            e_foto = st.file_uploader("Cambiar fotograf\u00eda (opcional)", type=["jpg", "jpeg", "png"],
                                                      key=f"admin_ef_{mid}")
                            e_quitar = st.checkbox("Quitar la fotograf\u00eda actual", key=f"admin_eq_{mid}")
                            guardar_ed = st.form_submit_button("Guardar cambios")
                        if guardar_ed:
                            cargo_final = e_otro.strip() if e_csel == "Otro" else e_csel
                            dni_n = e_dni.strip()
                            destino_id = destinos[e_base]
                            if not e_nom.strip() or not e_ape.strip():
                                st.warning("Completa nombres y apellidos.")
                            elif not re.fullmatch(r"\d{8}", dni_n):
                                st.warning("El DNI debe tener 8 d\u00edgitos.")
                            elif not re.fullmatch(r"\+?\d{9,15}", e_cel.strip()):
                                st.warning("Celular inv\u00e1lido.")
                            elif e_csel == "Otro" and not cargo_final:
                                st.warning("Especifica el cargo.")
                            elif e_foto is not None and e_foto.size > MAX_IMG_BYTES:
                                st.warning("La fotograf\u00eda debe pesar menos de 8 MB.")
                            elif (supabase.table("integrantes_base").select("id").eq("base_id", destino_id)
                                  .eq("dni", dni_n).neq("id", mid).limit(1).execute().data):
                                st.error("Ese DNI ya est\u00e1 registrado en esa base.")
                            else:
                                try:
                                    guardar_edicion_integrante(m, {
                                        "nombres": e_nom.strip(), "apellidos": e_ape.strip(), "dni": dni_n,
                                        "celular": e_cel.strip(), "cargo": cargo_final, "base_id": destino_id,
                                    }, e_foto, e_quitar)
                                    st.session_state["mostrar_msg_admin"] = "Datos del integrante actualizados."
                                    st.rerun()
                                except ValueError as ve:
                                    st.warning(str(ve))
                        with st.expander("Eliminar a este integrante"):
                            st.warning("Se eliminan sus datos, su fotograf\u00eda y su asistencia registrada. Si tiene credencial "
                                       "y no est\u00e1 registrado en otra base, esa credencial tambi\u00e9n se elimina. No se puede deshacer.")
                            ok_del = st.checkbox("Confirmo que quiero eliminar a esta persona", key=f"admin_delok_{mid}")
                            if st.button("Eliminar integrante", key=f"admin_delbtn_{mid}", disabled=not ok_del):
                                eliminar_integrantes([m])
                                st.session_state["mostrar_msg_admin"] = "Integrante eliminado."
                                st.rerun()

                st.divider()
                with st.expander("Eliminar esta base"):
                    st.warning(f'Se eliminan la base, sus {len(miembros)} integrantes, sus fotograf\u00edas y las credenciales '
                               'ligadas a ellos. No se puede deshacer.')
                    conf = st.text_input("Escribe el nombre exacto de la base para confirmar", key=f"admin_delb_{bid}")
                    if st.button("Eliminar base", type="primary", key=f"admin_delbtn_b_{bid}",
                                 disabled=conf.strip() != str(bad["nombre_base"]).strip()):
                        eliminar_integrantes(miembros)
                        supabase.table("bases_campana").delete().eq("id", bid).execute()
                        st.session_state["mostrar_msg_admin"] = "Base eliminada."
                        st.rerun()
        except Exception as e:
            error_supabase("No se pudo completar la acci\u00f3n de administraci\u00f3n.", e)

    with tabs[4]:
        st.subheader("Reuniones y asistencia")
        with st.form("crear_reunion"):
            nr = st.text_input("Nombre de la reuni\u00f3n")
            fr = st.date_input("Fecha de la reuni\u00f3n", value=date.today())
            lr = st.text_input("Lugar (opcional)")
            crear_r = st.form_submit_button("Crear reuni\u00f3n")
        if crear_r:
            if not nr.strip():
                st.warning("Escribe el nombre de la reuni\u00f3n.")
            else:
                try:
                    supabase.table("reuniones").insert({
                        "nombre": nr.strip(), "fecha": fr.isoformat(),
                        "lugar": lr.strip() or None
                    }).execute()
                    st.success("Reuni\u00f3n creada.")
                except Exception as e:
                    error_supabase("No se pudo crear la reuni\u00f3n.", e)
        st.divider()
        try:
            reuniones = (supabase.table("reuniones").select("id,nombre,fecha,lugar")
                         .order("fecha", desc=True).execute().data or [])
            bases = cargar_bases()
            if reuniones and bases:
                rm = {f'{r["fecha"]} \u2014 {r["nombre"]} (ID {r["id"]})': r for r in reuniones}
                bm = {f'{b["nombre_base"]} \u2014 {b.get("provincia") or ""}/{b.get("distrito") or ""} (ID {b["id"]})': b for b in bases}
                rsel = rm[st.selectbox("Seleccionar reuni\u00f3n", list(rm.keys()))]
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
                        c1.write(f'**{nombre_completo(m)}** \u00b7 {m.get("cargo") or "Sin cargo"}')
                        ya = estado.get(m["id"], False)
                        if ya:
                            presentes += 1
                            c2.button("\u2713 Presente", key=f"pres_{rsel['id']}_{m['id']}", disabled=True,
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
                st.subheader("Historial de la reuni\u00f3n")
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
                        "Descargar asistencia de esta reuni\u00f3n (Excel)",
                        excel_bytes(historial_df, "Asistencia"),
                        f"asistencia_reunion_{rsel['id']}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.info("Todav\u00eda no se ha marcado a nadie como presente.")
            elif not reuniones:
                st.info("Primero crea una reuni\u00f3n.")
            else:
                st.info("Primero registra una base.")
        except Exception as e:
            error_supabase("No se pudo cargar el m\u00f3dulo de asistencia.", e)

    with tabs[5]:
        st.subheader("Exportar datos")
        try:
            bases = cargar_bases()
            integrantes = cargar_integrantes()
            prov = st.selectbox("Filtrar por provincia", ["Todas"] + PROVINCIAS, key="exp_prov")
            bases_f = [b for b in bases if prov == "Todas" or b.get("provincia") == prov]
            mapa = {b["id"]: b for b in bases_f}
            integ_f = [i for i in integrantes if i.get("base_id") in mapa]
            cuenta = {}
            for i in integ_f:
                cuenta[i["base_id"]] = cuenta.get(i["base_id"], 0) + 1
            if not bases_f:
                st.info("No hay bases para este filtro.")
            else:
                dfb = pd.DataFrame([{
                    "Base": b.get("nombre_base", ""),
                    "Provincia": b.get("provincia") or "",
                    "Distrito": b.get("distrito") or "",
                    "Usuario": b.get("usuario", ""),
                    "Integrantes": cuenta.get(b["id"], 0),
                    "Fecha de creaci\u00f3n": str(b.get("fecha_registro", ""))[:10],
                } for b in bases_f])
                resumen = (dfb.groupby("Provincia", as_index=False)
                           .agg(Bases=("Base", "count"), Integrantes=("Integrantes", "sum")))
                dfi = dataframe_detallado(integ_f, mapa)
                st.write(f"**{len(bases_f)}** bases \u00b7 **{len(integ_f)}** integrantes")
                st.download_button(
                    "Descargar Excel completo (Resumen, Bases e Integrantes)",
                    excel_multihoja({"Resumen": resumen, "Bases": dfb, "Integrantes": dfi},
                                    titulo=f"Registro de bases \u2014 {prov} \u2014 {date.today().strftime('%d/%m/%Y')}"),
                    f"registro_bases_{nombre_archivo_seguro(prov)}.xlsx", MIME_XLSX, key="xl_completo")
                st.divider()
                st.write("**Un Excel y dos PDF por base** (lista y hoja de firmas), en un solo ZIP.")
                if st.button("Preparar ZIP por base", key="zip_bases_btn"):
                    with st.spinner("Preparando archivos\u2026"):
                        por_base = {}
                        for i in integ_f:
                            por_base.setdefault(i["base_id"], []).append(i)
                        buf = io.BytesIO()
                        pdf_ok = True
                        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                            for b in bases_f:
                                ms = por_base.get(b["id"], [])
                                carpeta = f'{nombre_archivo_seguro(b["nombre_base"])}_{b["id"]}'
                                titulo = f'Lista de integrantes \u2014 {b["nombre_base"]}'
                                z.writestr(f"{carpeta}/integrantes.xlsx",
                                           excel_bytes(dataframe_detallado(ms, mapa), "Integrantes", titulo=titulo))
                                if pdf_ok:
                                    try:
                                        z.writestr(f"{carpeta}/lista.pdf",
                                                   pdf_lista(titulo, ubicacion_texto(b), ms))
                                        z.writestr(f"{carpeta}/firmas.pdf",
                                                   pdf_lista(titulo, ubicacion_texto(b), ms, con_firma=True))
                                    except ImportError:
                                        pdf_ok = False
                        st.session_state["mostrar_zip_bases"] = {"prov": prov, "datos": buf.getvalue(),
                                                                 "sin_pdf": not pdf_ok}
                zb = st.session_state.get("mostrar_zip_bases")
                if zb:
                    st.download_button(f'Descargar ZIP por base (provincia: {zb["prov"]})', zb["datos"],
                                       "listas_por_base.zip", "application/zip", key="dl_zip_bases")
                    if zb.get("sin_pdf"):
                        st.caption("El ZIP no incluye PDF porque falta instalar reportlab.")
                st.caption("Los archivos contienen datos personales (DNI y celular). Man\u00e9jalos con cuidado.")
        except Exception as e:
            error_supabase("No se pudieron preparar los archivos.", e)

    with tabs[6]:
        st.subheader("\U0001faaa Generar credenciales QR")
        if not APP_PUBLIC_URL:
            st.warning("Configura APP_PUBLIC_URL en Secrets con la URL p\u00fablica de tu aplicaci\u00f3n para que los QR puedan abrir la verificaci\u00f3n.")
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
                bases_info = datos_bases_por_dni(integrante["dni"])
                principal = next((b for b in bases_info if b["id"] == integrante.get("base_id")),
                                 bases_info[0] if bases_info else {})
                integrante_render = dict(integrante)
                integrante_render["nombre_base"] = ", ".join(b["nombre_base"] for b in bases_info)
                integrante_render["provincia"] = principal.get("provincia") or ""
                integrante_render["distrito"] = principal.get("distrito") or ""
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
                cred_actual = credencial_de_dni(integrante["dni"])
                if cred_actual:
                    st.write(f'**Estado de la credencial:** {cred_actual["estado"]} \u00b7 emitida el {str(cred_actual.get("emitida_en", ""))[:10]}')
                    confirma_borrar = st.checkbox("Confirmo que quiero eliminar esta credencial",
                                                  key=f'credencial_conf_{integrante["dni"]}')
                    if st.button("Eliminar credencial", key="eliminar_cred", disabled=not confirma_borrar):
                        supabase.table("credenciales").delete().eq("id", cred_actual["id"]).execute()
                        st.session_state.pop("credencial_generada", None)
                        st.session_state.pop("credencial_reverso", None)
                        st.success("Credencial eliminada. Su QR ya no es v\u00e1lido. Puedes generar una nueva cuando quieras.")
                if st.button("Generar / renovar credencial", type="primary"):
                    if not APP_PUBLIC_URL:
                        st.error("No se puede emitir un QR funcional hasta configurar APP_PUBLIC_URL.")
                    else:
                        token = secrets.token_urlsafe(32)
                        url_qr = f"{APP_PUBLIC_URL}/?verificar={quote(token)}"
                        frente = componer_credencial(integrante_render, plantilla, url_qr, "frontal")
                        buffer = io.BytesIO()
                        frente.save(buffer, format="PNG")
                        reverso_bytes = None
                        if plantilla.get("posterior_path"):
                            reverso = componer_credencial(integrante_render, plantilla, url_qr, "posterior")
                            rb = io.BytesIO()
                            reverso.save(rb, format="PNG")
                            reverso_bytes = rb.getvalue()
                        emitir_credencial(integrante, plantilla.get("id"), token)
                        st.session_state["credencial_generada"] = buffer.getvalue()
                        st.session_state["credencial_dni"] = str(integrante["dni"])
                        st.session_state["credencial_nombre"] = re.sub(r"[^A-Za-z0-9_-]", "_", str(integrante["dni"]))
                        if reverso_bytes:
                            st.session_state["credencial_reverso"] = reverso_bytes
                        else:
                            st.session_state.pop("credencial_reverso", None)
                        st.success("Credencial generada. Escanea el QR para probar la verificaci\u00f3n.")
                if (st.session_state.get("credencial_generada")
                        and st.session_state.get("credencial_dni") == str(integrante["dni"])):
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
                        img = Image.open(io.BytesIO(st.session_state["credencial_generada"])).convert("RGB")
                        pw = (85.6 if img.width >= img.height else 54) * 2.83465
                        ph = pw * img.height / img.width
                        c = canvas.Canvas(pdf, pagesize=(pw, ph))
                        c.drawImage(ImageReader(img), 0, 0, width=pw, height=ph)
                        c.showPage()
                        if st.session_state.get("credencial_reverso"):
                            img2 = Image.open(io.BytesIO(st.session_state["credencial_reverso"])).convert("RGB")
                            ph2 = pw * img2.height / img2.width
                            c.setPageSize((pw, ph2))
                            c.drawImage(ImageReader(img2), 0, 0, width=pw, height=ph2)
                            c.showPage()
                        c.save()
                        st.download_button("Descargar credencial (PDF)", pdf.getvalue(),
                                           f"credencial_{nombre_archivo}.pdf", "application/pdf")
                    except Exception as e:
                        logger.warning("PDF no disponible: %r", e)
                        st.caption("El PDF no est\u00e1 disponible en este momento. Puedes usar las im\u00e1genes PNG.")
            else:
                st.info("Todav\u00eda no hay integrantes registrados.")
        except Exception as e:
            error_supabase("No se pudo preparar la credencial.", e)

    with tabs[7]:
        st.subheader("\U0001faaa Credenciales en lote")
        st.caption("Genera varias credenciales a la vez y desc\u00e1rgalas en ZIP o en PDF listo para imprimir.")
        f_zip = "ZIP con im\u00e1genes PNG"
        f_pdf = "PDF (una credencial por p\u00e1gina)"
        f_a4 = "PDF A4 para imprimir (8 por hoja)"
        if not APP_PUBLIC_URL:
            st.warning("Configura APP_PUBLIC_URL en Secrets para que los QR abran la verificaci\u00f3n.")
        else:
            try:
                bases = cargar_bases()
                todos = cargar_integrantes()
                if not bases or not todos:
                    st.info("Primero registra bases e integrantes.")
                else:
                    mapa_bases = {b["id"]: b for b in bases}
                    dni_bases = {}
                    for f in todos:
                        d = str(f.get("dni", "")).strip()
                        b = mapa_bases.get(f.get("base_id"))
                        if d and b:
                            dni_bases.setdefault(d, []).append(b)
                    opciones = {"Todas las bases": None}
                    for b in bases:
                        opciones[f'{b["nombre_base"]} \u2014 {b.get("provincia") or ""}/{b.get("distrito") or ""} (ID {b["id"]})'] = b["id"]
                    c1, c2 = st.columns(2)
                    sel = c1.selectbox("Base", list(opciones.keys()), key="lote_base")
                    solo_nuevas = c2.checkbox("Solo personas que a\u00fan no tienen credencial",
                                              value=True, key="lote_solo_nuevas")
                    id_base = opciones[sel]
                    unicos = {}
                    for f in todos:
                        d = str(f.get("dni", "")).strip()
                        if d and d not in unicos and (id_base is None or f["base_id"] == id_base):
                            unicos[d] = f
                    personas = sorted(unicos.values(), key=lambda x: (str(x.get("apellidos", "")).lower(),
                                                                       str(x.get("nombres", "")).lower()))
                    estados_cred = mapa_estados_credenciales()
                    estados = {}
                    for p in personas:
                        d = str(p["dni"]).strip()
                        estados[d] = (estados_cred.get(clave_persona(d))
                                      or estados_cred.get(clave_persona_legacy(d)) or "sin credencial")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Personas", len(personas))
                    m2.metric("Sin credencial", sum(1 for v in estados.values() if v == "sin credencial"))
                    m3.metric("Vigentes", sum(1 for v in estados.values() if v == "vigente"))
                    m4.metric("Revocadas", sum(1 for v in estados.values() if v == "revocada"))
                    if solo_nuevas:
                        cola = [p for p in personas if estados[str(p["dni"]).strip()] == "sin credencial"]
                    else:
                        cola = personas
                    if not cola:
                        st.info("No hay personas pendientes con este filtro.")
                    else:
                        tam = st.selectbox("Credenciales por tanda", [25, 50, 100], index=1, key="lote_tam")
                        n_tandas = -(-len(cola) // tam)
                        if solo_nuevas or n_tandas == 1:
                            tanda = 1
                        else:
                            tanda = st.number_input("Tanda", min_value=1, max_value=n_tandas,
                                                    value=1, step=1, key="lote_tanda")
                        lote = cola[(tanda - 1) * tam: tanda * tam]
                        extra = f", tanda {tanda} de {n_tandas}" if (not solo_nuevas and n_tandas > 1) else ""
                        st.write(f"Se generar\u00e1n **{len(lote)}** credenciales ({len(cola)} pendientes en total{extra}).")
                        formatos = st.multiselect("Formatos de descarga", [f_zip, f_pdf, f_a4],
                                                  default=[f_zip, f_a4], key="lote_formatos")
                        confirmar = True
                        if not solo_nuevas:
                            confirmar = st.checkbox(
                                "Entiendo que al renovar, los QR anteriores de estas personas dejar\u00e1n de funcionar.",
                                key="lote_confirmar")
                        plantilla = plantilla_activa()
                        st.caption(f'Plantilla: {plantilla["nombre"]}')
                        if st.button(f"Generar {len(lote)} credenciales", type="primary",
                                     disabled=not (confirmar and formatos), key="lote_generar"):
                            barra = st.progress(0.0, text="Preparando\u2026")

                            def avance(i, total):
                                barra.progress(i / total, text=f"Generando credencial {i} de {total}\u2026")

                            resultados, errores = generar_lote(lote, plantilla, dni_bases, avance)
                            if resultados:
                                barra.progress(1.0, text="Guardando en la base de datos\u2026")
                                guardar_credenciales_lote(resultados, plantilla.get("id"))
                                archivos = {"sello": datetime.now().strftime("%Y%m%d_%H%M"),
                                            "n": len(resultados),
                                            "errores": [nombre_completo(p) for p in errores]}
                                if f_zip in formatos:
                                    archivos["zip"] = zip_credenciales(resultados)
                                try:
                                    if f_pdf in formatos:
                                        archivos["pdf"] = pdf_credenciales(resultados)
                                    if f_a4 in formatos:
                                        archivos["a4"] = pdf_credenciales(resultados, hoja_a4=True)
                                except ImportError:
                                    archivos["sin_pdf"] = True
                                st.session_state["lote_archivos"] = archivos
                            else:
                                st.session_state.pop("lote_archivos", None)
                                st.error("No se pudo generar ninguna credencial.")
                            barra.empty()
                    archivos = st.session_state.get("lote_archivos")
                    if archivos:
                        st.success(f'{archivos["n"]} credenciales generadas y registradas.')
                        if archivos["errores"]:
                            st.warning("No se pudieron generar: " + ", ".join(archivos["errores"]))
                        st.caption("Desc\u00e1rgalas ahora: por seguridad el sistema no guarda el QR, solo su huella. "
                                   "Si las pierdes, habr\u00e1 que renovarlas.")
                        d1, d2, d3 = st.columns(3)
                        if archivos.get("zip"):
                            d1.download_button("Descargar ZIP (PNG)", archivos["zip"],
                                               f'credenciales_{archivos["sello"]}.zip', "application/zip",
                                               key="dl_lote_zip")
                        if archivos.get("pdf"):
                            d2.download_button("Descargar PDF", archivos["pdf"],
                                               f'credenciales_{archivos["sello"]}.pdf', "application/pdf",
                                               key="dl_lote_pdf")
                        if archivos.get("a4"):
                            d3.download_button("Descargar PDF A4 (imprimir)", archivos["a4"],
                                               f'credenciales_A4_{archivos["sello"]}.pdf', "application/pdf",
                                               key="dl_lote_a4")
                        if archivos.get("sin_pdf"):
                            st.caption("Los PDF requieren instalar reportlab (agr\u00e9galo a requirements.txt).")
            except Exception as e:
                error_supabase("No se pudo completar la generaci\u00f3n en lote.", e)

    with tabs[8]:
        st.subheader("\U0001f4cb Credenciales generadas")
        st.caption("Todas las credenciales emitidas. Marca las que quieras eliminar; las que no marques se conservan.")
        try:
            msg_cred = st.session_state.pop("mostrar_msg_cred", None)
            if msg_cred:
                st.success(msg_cred)
            creds = traer_todo(lambda: supabase.table("credenciales")
                               .select("id,integrante_id,estado,emitida_en")
                               .order("emitida_en", desc=True).order("id"))
            if not creds:
                st.info("A\u00fan no hay credenciales generadas.")
            else:
                integrantes_all = cargar_integrantes()
                nombres_base = {b["id"]: b["nombre_base"] for b in cargar_bases()}
                mapa_i = {i["id"]: i for i in integrantes_all}
                bases_de_dni = {}
                for i in integrantes_all:
                    d = str(i.get("dni", "")).strip()
                    nb = nombres_base.get(i["base_id"])
                    if d and nb and nb not in bases_de_dni.setdefault(d, []):
                        bases_de_dni[d].append(nb)
                filas = []
                for c in creds:
                    i = mapa_i.get(c["integrante_id"])
                    d = str(i.get("dni", "")).strip() if i else ""
                    filas.append({
                        "ID": c["id"],
                        "Integrante": nombre_completo(i) if i else "(integrante eliminado)",
                        "DNI": d,
                        "Base": ", ".join(bases_de_dni.get(d, [])),
                        "Estado": c.get("estado", ""),
                        "Emitida": str(c.get("emitida_en", ""))[:16].replace("T", " "),
                    })
                f1, f2 = st.columns(2)
                buscar = f1.text_input("Buscar por nombre o DNI", key="lote_cred_buscar").strip().lower()
                base_f = f2.selectbox("Base", ["Todas"] + sorted(set(nombres_base.values())),
                                      key="lote_cred_base")
                vistas = [f for f in filas
                          if (not buscar or buscar in f["Integrante"].lower() or buscar in f["DNI"])
                          and (base_f == "Todas" or base_f in bases_de_dni.get(f["DNI"], []))]
                st.write(f"**{len(vistas)}** de {len(filas)} credenciales \u00b7 "
                         f"vigentes: {sum(1 for f in filas if f['Estado'] == 'vigente')}")
                if not vistas:
                    st.info("No hay credenciales con ese filtro.")
                else:
                    limite = 300
                    if len(vistas) > limite:
                        st.caption(f"Se muestran las primeras {limite}. Usa el buscador o el filtro de base para ver las dem\u00e1s.")
                    mostradas = vistas[:limite]
                    n = st.session_state.get("lote_borrado_n", 0)
                    todas = st.checkbox("Marcar todas las que se muestran", key=f"lote_marcar_{n}")
                    df = pd.DataFrame(mostradas)
                    df.insert(0, "Eliminar", todas)
                    editado = st.data_editor(
                        df, hide_index=True, use_container_width=True,
                        disabled=[c for c in df.columns if c != "Eliminar"],
                        column_config={"Eliminar": st.column_config.CheckboxColumn("Eliminar"), "ID": None},
                        key=f"lote_editor_{n}_{todas}_{abs(hash((buscar, base_f)))}")
                    marcadas = editado.loc[editado["Eliminar"], "ID"].tolist()
                    st.write(f"Marcadas para eliminar: **{len(marcadas)}** \u00b7 las dem\u00e1s se conservan.")
                    ok = st.checkbox("Confirmo que quiero eliminar las credenciales marcadas. Sus QR dejar\u00e1n de funcionar.",
                                     key=f"lote_confirma_borrado_{n}")
                    if st.button("Eliminar credenciales marcadas", type="primary",
                                 disabled=not (marcadas and ok), key=f"lote_btn_borrar_{n}"):
                        for k in range(0, len(marcadas), 100):
                            supabase.table("credenciales").delete().in_("id", marcadas[k:k + 100]).execute()
                        st.session_state["lote_borrado_n"] = n + 1
                        st.session_state["mostrar_msg_cred"] = f"{len(marcadas)} credenciales eliminadas."
                        st.rerun()
                    st.download_button("Descargar esta lista (Excel)",
                                       excel_bytes(pd.DataFrame(vistas).drop(columns=["ID"]), "Credenciales",
                                                   titulo="Credenciales generadas"),
                                       "credenciales_generadas.xlsx", MIME_XLSX, key="dl_creds_xlsx")
        except Exception as e:
            error_supabase("No se pudo cargar la lista de credenciales.", e)

    with tabs[9]:
        st.subheader("\U0001f3a8 Administrar plantillas")
        st.info("Puedes subir una imagen ya dise\u00f1ada o usar la plantilla predeterminada. La imagen se utiliza como fondo; el sistema a\u00f1ade los datos y el QR.")
        with st.form("form_plantilla", clear_on_submit=True):
            nombre_plantilla = st.text_input("Nombre de la plantilla")
            frontal = st.file_uploader("Imagen frontal (PNG o JPG)", type=["png", "jpg", "jpeg"])
            posterior = st.file_uploader("Imagen posterior (opcional)", type=["png", "jpg", "jpeg"])
            distribucion = st.selectbox("Distribuci\u00f3n de datos, foto y QR",
                                        [DISENO_AUTO] + list(DISENOS_PREDEFINIDOS.keys()), index=1)
            activar_al_guardar = st.checkbox("Activar esta plantilla al guardar", value=True)
            guardar_plantilla_btn = st.form_submit_button("Guardar plantilla")
        if guardar_plantilla_btn:
            if not nombre_plantilla.strip() or frontal is None:
                st.warning("Escribe un nombre y selecciona la imagen frontal.")
            elif frontal.size > MAX_IMG_BYTES or (posterior is not None and posterior.size > MAX_IMG_BYTES):
                st.warning("Cada imagen debe pesar menos de 8 MB.")
            else:
                try:
                    im = Image.open(io.BytesIO(frontal.getvalue()))
                    if im.width < 400 or im.height < 250:
                        st.warning("La imagen es peque\u00f1a. Se recomienda al menos 1011 \u00d7 638 p\u00edxeles.")
                    guardar_plantilla(nombre_plantilla, frontal, posterior, activar_al_guardar,
                                      copy.deepcopy(DISENOS_PREDEFINIDOS.get(distribucion) or {"modo": "auto"}))
                    st.success("Plantilla guardada correctamente.")
                    st.rerun()
                except Exception as e:
                    error_supabase("No se pudo guardar la plantilla. Revisa el bucket y la tabla de Supabase.", e)
        st.divider()
        try:
            mensaje_plantilla = st.session_state.pop("mostrar_msg_plantilla", None)
            if mensaje_plantilla:
                st.success(mensaje_plantilla)
            plantillas = listar_plantillas()
            if plantillas:
                for p in plantillas:
                    c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
                    c1.write(f'**{p["nombre"]}**' + (" \u00b7 Activa" if p.get("activa") else ""))
                    if c2.button("Vista previa", key=f"prev_{p['id']}"):
                        st.image(url_plantilla(p["frontal_path"]), caption=p["nombre"])
                    if c3.button("Activar", key=f"act_{p['id']}", disabled=bool(p.get("activa"))):
                        activar_plantilla(p["id"])
                        st.success("Plantilla activada.")
                        st.rerun()
                    if c4.button("Eliminar", key=f"del_{p['id']}"):
                        st.session_state[f"mostrar_del_{p['id']}"] = True
                    if st.session_state.get(f"mostrar_del_{p['id']}"):
                        bloque_eliminar(p)
                    with st.expander(f'Distribuci\u00f3n de datos, foto y QR \u2014 {p["nombre"]}'):
                        editor_diseno(p)
            else:
                st.info("A\u00fan no hay plantillas guardadas. Se usar\u00e1 el dise\u00f1o predeterminado.")
        except Exception as e:
            error_supabase("No se pudieron cargar las plantillas.", e)

    if st.button("Cerrar sesi\u00f3n de administrador"):
        limpiar_sesion()
        st.rerun()

# ---------------------------------------------------------------------
# PANEL RESPONSABLE DE BASE
# ---------------------------------------------------------------------
if st.session_state.base_id is not None:
    base_id = st.session_state.base_id
    st.success(f'Sesi\u00f3n: {st.session_state.base_nombre} \u00b7 {st.session_state.base_provincia} / {st.session_state.base_distrito}')
    st.subheader("Integrantes de tu base")
    with st.expander("Agregar integrante", expanded=False):
        with st.form("form_integrante", clear_on_submit=True):
            nombres = st.text_input("Nombres")
            apellidos = st.text_input("Apellidos")
            dni = st.text_input("DNI (8 d\u00edgitos)")
            celular = st.text_input("Celular (9 a 15 d\u00edgitos)")
            foto = st.file_uploader("Fotograf\u00eda del integrante (opcional)", type=["jpg", "jpeg", "png"])
            cargo_sel = st.selectbox("Cargo o condici\u00f3n", CARGOS)
            cargo_otro = st.text_input("Especifica el cargo") if cargo_sel == "Otro" else ""
            consentimiento = st.checkbox("Confirmo que la persona fue informada y autoriz\u00f3 el registro de sus datos y fotograf\u00eda, "
                "y que su nombre, cargo y fotograf\u00eda se mostrar\u00e1n al escanear su credencial.")
            guardar = st.form_submit_button("Guardar integrante")
        if guardar:
            cargo_final = cargo_otro.strip() if cargo_sel == "Otro" else cargo_sel
            if not nombres.strip() or not apellidos.strip():
                st.warning("Completa nombres y apellidos.")
            elif not re.fullmatch(r"\d{8}", dni.strip()):
                st.warning("El DNI debe tener 8 d\u00edgitos.")
            elif not re.fullmatch(r"\+?\d{9,15}", celular.strip()):
                st.warning("Celular inv\u00e1lido.")
            elif cargo_sel == "Otro" and not cargo_final:
                st.warning("Especifica el cargo.")
            elif not consentimiento:
                st.warning("Confirma que existe autorizaci\u00f3n.")
            elif foto is not None and foto.size > MAX_IMG_BYTES:
                st.warning("La fotograf\u00eda debe pesar menos de 8 MB.")
            else:
                try:
                    duplicado = (supabase.table("integrantes_base").select("id")
                                 .eq("base_id", base_id).eq("dni", dni.strip()).limit(1).execute().data or [])
                    if duplicado:
                        st.error("Ese DNI ya est\u00e1 registrado en esta base.")
                    else:
                        url_foto = None
                        if foto is not None:
                            datos_foto = procesar_foto(foto)
                            path = f"{base_id}/{uuid.uuid4().hex}.jpg"
                            url_foto = subir_archivo(BUCKET_FOTOS, path, datos_foto, "image/jpeg")
                        supabase.table("integrantes_base").insert({
                            "base_id": base_id, "nombres": nombres.strip(),
                            "apellidos": apellidos.strip(), "dni": dni.strip(),
                            "celular": celular.strip(), "cargo": cargo_final,
                            "foto_url": url_foto
                        }).execute()
                        st.success("Integrante registrado.")
                        st.rerun()
                except ValueError as ve:
                    st.warning(str(ve))
                except Exception as e:
                    error_supabase("No se pudo guardar el integrante.", e)
    try:
        filas = cargar_integrantes(base_id)
        st.metric("Total de integrantes", len(filas))
        if filas:
            st.dataframe(dataframe_integrantes(filas), use_container_width=True, hide_index=True)
            botones_lista({"id": base_id, "nombre_base": st.session_state.base_nombre,
                           "provincia": st.session_state.base_provincia,
                           "distrito": st.session_state.base_distrito}, filas, "mi_base")
        else:
            st.info("Todav\u00eda no hay integrantes registrados.")
    except Exception as e:
        error_supabase("No se pudo cargar la lista.", e)

    if st.button("Cerrar sesi\u00f3n de base"):
        limpiar_sesion()
        st.rerun()

st.divider()
with st.expander("Aviso de privacidad"):
    st.write(
        "Los datos de identificaci\u00f3n, fotograf\u00edas y afiliaci\u00f3n o participaci\u00f3n organizativa "
        "son datos personales que requieren protecci\u00f3n reforzada. Informa a cada persona "
        "sobre la finalidad, qui\u00e9n accede, cu\u00e1nto tiempo se conservar\u00e1n y c\u00f3mo solicitar "
        "correcci\u00f3n o eliminaci\u00f3n. No registres a nadie sin autorizaci\u00f3n documentada. "
        "La consulta p\u00fablica del QR muestra \u00fanicamente nombre, cargo, bases y fotograf\u00eda, y nunca el DNI ni el tel\u00e9fono."
    )
