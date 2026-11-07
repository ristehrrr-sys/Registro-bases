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
import html as _html
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
from PIL import Image, ImageDraw, ImageFont, ImageOps
 
st.set_page_config(
    page_title="Registro de Bases y Comandos",
    page_icon="\U0001f5f3\ufe0f",
    layout="wide",
)
 
st.markdown("""
<style>
:root{--acc:#2FB067;--card:rgba(127,127,127,.12);--card2:rgba(127,127,127,.22);--line:rgba(127,127,127,.38);--red:#D1242F}
header,[data-testid="stHeader"],#MainMenu,.stDeployButton,footer,
[data-testid="stToolbar"],[data-testid="stDecoration"] {visibility:hidden!important;display:none!important}
.block-container{padding-top:.8rem!important;padding-bottom:170px!important;max-width:980px!important}
/* Barra superior estilo perfil */
.top{display:flex;align-items:center;gap:12px;padding:12px 14px;margin:0 0 12px;border-radius:14px;background:var(--card)}
.av{width:46px;height:46px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;color:#fff;flex:none;background:linear-gradient(160deg,#3ECF8E,#1B7F3B)}
.tt .n{font-weight:800;font-size:1.04rem;line-height:1.2}
.tt .s{font-size:.78rem;opacity:.7;line-height:1.3;margin-top:1px}
.chip{display:inline-flex;align-items:center;gap:8px;padding:5px 12px;border-radius:999px;background:var(--card);font-size:.82rem;font-weight:600;margin:0 0 10px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--acc);box-shadow:0 0 0 3px rgba(47,176,103,.25)}
/* Titulos */
h2,h3{font-weight:700!important;letter-spacing:-.01em!important}
h2{font-size:1.3rem!important}
h3{font-size:1.08rem!important}
hr{margin:1.1rem 0!important;opacity:.3}
/* Botones estilo GitHub: compactos, gris suave, borde fino */
.stButton>button,.stDownloadButton>button,.stFormSubmitButton>button{border:1px solid var(--line)!important;border-radius:8px!important;background:var(--card)!important;font-weight:600!important;font-size:.9rem!important;min-height:2.4rem;padding:.3rem .9rem!important;box-shadow:none!important;transition:background .1s ease}
.stButton>button:hover,.stDownloadButton>button:hover,.stFormSubmitButton>button:hover{background:var(--card2)!important}
.stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"],[data-testid="stBaseButton-primary"],[data-testid="stBaseButton-primaryFormSubmit"]{background:#1F883D!important;border-color:rgba(27,31,36,.15)!important;color:#fff!important;box-shadow:none!important}
.stButton>button[kind="primary"]:hover,[data-testid="stBaseButton-primary"]:hover{background:#1A7F37!important}
@media (max-width:640px){.stButton>button,.stDownloadButton>button,.stFormSubmitButton>button{min-height:2.7rem}}
/* Acciones de borrado en rojo */
[class*="st-key-del_"]:not([class*="st-key-del_no_"]) button,[class*="st-key-eliminar_cred"] button,[class*="st-key-admin_delbtn_"] button{background:transparent!important;color:var(--red)!important;border-color:rgba(209,36,47,.55)!important}
[class*="st-key-del_"]:not([class*="st-key-del_no_"]) button:hover,[class*="st-key-eliminar_cred"] button:hover,[class*="st-key-admin_delbtn_"] button:hover{background:rgba(209,36,47,.12)!important}
[class*="st-key-del_si_"] button,[class*="st-key-admin_delbtn_b_"] button,[class*="st-key-lote_btn_borrar_"] button{background:#CF222E!important;color:#fff!important;border-color:rgba(27,31,36,.15)!important}
/* Navegacion inferior flotante (sobre el boton Manage app de Streamlit Cloud) */
[class*="st-key-nav_admin_panel"]{position:fixed!important;left:50%;transform:translateX(-50%);bottom:calc(54px + env(safe-area-inset-bottom));z-index:1000;width:min(94vw,560px);background:rgba(28,38,51,.97);border-radius:30px;padding:6px 8px;box-shadow:0 10px 30px rgba(0,0,0,.5)}
[class*="st-key-nav_admin_panel"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:2px!important}
[class*="st-key-nav_admin_panel"] [data-testid="stHorizontalBlock"]>div{flex:1 1 0!important;min-width:0!important;width:auto!important}
[class*="st-key-nav_admin_panel"] .stButton,[class*="st-key-nav_admin_panel"] [data-testid="stButton"]{width:100%!important}
[class*="st-key-nav_admin_panel"] button{width:100%!important;display:flex!important;flex-direction:column;align-items:center;justify-content:center;gap:2px;min-height:0!important;padding:7px 2px!important;border:none!important;background:transparent!important;border-radius:22px!important;box-shadow:none!important;color:#B4C2D1!important}
[class*="st-key-nav_admin_panel"] button *{color:inherit!important}
[class*="st-key-nav_admin_panel"] button p{font-size:.68rem!important;font-weight:600!important;margin:0!important;line-height:1.1!important;white-space:nowrap}
[class*="st-key-nav_admin_panel"] button::before{font-size:1.25rem;line-height:1}
[class*="st-key-nav_admin_panel"] button[kind="primary"],[class*="st-key-nav_admin_panel"] [data-testid="stBaseButton-primary"]{background:rgba(47,176,103,.26)!important;color:#6BE79A!important}
[class*="st-key-nav_admin_panel"] [data-testid="stHorizontalBlock"]>div:nth-child(1) button::before{content:"\U0001f465"}
[class*="st-key-nav_admin_panel"] [data-testid="stHorizontalBlock"]>div:nth-child(2) button::before{content:"\U0001f4c5"}
[class*="st-key-nav_admin_panel"] [data-testid="stHorizontalBlock"]>div:nth-child(3) button::before{content:"\U0001f194"}
[class*="st-key-nav_admin_panel"] [data-testid="stHorizontalBlock"]>div:nth-child(4) button::before{content:"\U0001f4e4"}
[class*="st-key-nav_admin_panel"] [data-testid="stHorizontalBlock"]>div:nth-child(5) button::before{content:"\U0001f5bc\ufe0f"}
/* Subsecciones: control segmentado como "Code | Blame" de GitHub */
[class*="st-key-nav_admin_sub_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:2px!important;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:3px}
[class*="st-key-nav_admin_sub_"] [data-testid="stHorizontalBlock"]>div{flex:1 1 0!important;min-width:0!important;width:auto!important}
[class*="st-key-nav_admin_sub_"] .stButton,[class*="st-key-nav_admin_sub_"] [data-testid="stButton"]{width:100%!important}
[class*="st-key-nav_admin_sub_"] button{width:100%!important;min-height:2.3rem!important;border:none!important;background:transparent!important;border-radius:8px!important;box-shadow:none!important;padding:.25rem .2rem!important}
[class*="st-key-nav_admin_sub_"] button p{font-size:.82rem!important;line-height:1.15!important;margin:0!important;white-space:normal;text-align:center}
[class*="st-key-nav_admin_sub_"] button[kind="primary"],[class*="st-key-nav_admin_sub_"] [data-testid="stBaseButton-primary"]{background:var(--card2)!important;color:inherit!important;font-weight:700!important;box-shadow:0 0 0 1px var(--line) inset!important}
/* Tarjetas */
[data-testid="stMetric"]{background:var(--card);border-radius:12px;padding:12px 14px}
[data-testid="stMetricValue"]{font-weight:800}
[data-testid="stForm"]{border:1px solid var(--line)!important;border-radius:12px!important;background:var(--card);padding:1rem!important;max-width:680px}
[data-testid="stExpander"]{border:1px solid var(--line)!important;border-radius:12px!important;background:var(--card);overflow:hidden}
[data-testid="stAlert"]{border-radius:10px!important;border:none!important}
[data-testid="stDataFrame"]{border-radius:10px;overflow:hidden;border:1px solid var(--line)}
[data-baseweb="input"],[data-baseweb="textarea"],[data-baseweb="select"]>div{border-radius:8px!important}
[data-testid="stImage"] img{border-radius:10px}
@media (max-width:640px){.block-container{padding-left:.8rem!important;padding-right:.8rem!important}}
 
/* Navegación desplegable moderna del panel administrativo */
.admin-nav-heading{margin:10px 0 14px;padding:18px 20px;border:1px solid var(--line);border-radius:16px;background:linear-gradient(125deg,rgba(31,136,61,.13),var(--card));}
.admin-nav-kicker{font-size:.68rem;font-weight:800;letter-spacing:.14em;color:#279653;margin-bottom:5px;}
.admin-nav-title{font-size:1.22rem;font-weight:800;letter-spacing:-.025em;line-height:1.25;}
.admin-nav-caption{font-size:.83rem;opacity:.72;margin-top:4px;}
.admin-nav-separator{height:1px;background:var(--line);margin:14px 0 20px;}
[data-testid="stSelectbox"] [data-baseweb="select"]>div{min-height:48px!important;border:1px solid var(--line)!important;border-radius:11px!important;background:var(--card)!important;box-shadow:0 2px 8px rgba(0,0,0,.035)!important;}
[data-testid="stSelectbox"] label{font-weight:700!important;font-size:.84rem!important;}
@media(max-width:640px){.admin-nav-heading{padding:15px 16px}.admin-nav-title{font-size:1.1rem}}
 
</style>
""", unsafe_allow_html=True)
 
# ---------------------------------------------------------------------
# CONFIGURACION Y CONEXION
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
    "MILITANTE",
    "Otro"
]
 
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
    # Recomendado: define CLAVE_HMAC (texto largo y aleatorio) en Secrets.
    # Si no existe, se deriva de SUPABASE_KEY para no romper la app.
    secreto = str(st.secrets.get("CLAVE_HMAC", "")).strip()
    if not secreto:
        secreto = "persona_key:" + str(st.secrets["SUPABASE_KEY"])
    return secreto.encode("utf-8")
 
def clave_persona(dni) -> str:
    # HMAC con clave secreta: no se puede revertir por fuerza bruta sin la clave.
    return hmac.new(_clave_hmac(), str(dni).strip().encode("utf-8"), hashlib.sha256).hexdigest()
 
def clave_persona_legacy(dni) -> str:
    # Formato anterior (SHA-256 sin clave). Solo se usa para encontrar credenciales ya emitidas.
    return hash_texto(str(dni).strip())
 
def token_credencial(dni, cred_id) -> str:
    # El codigo del QR no es aleatorio: se calcula con la clave secreta, el DNI y el id de la
    # credencial. Asi se puede volver a descargar la misma credencial sin guardar el codigo.
    mac = hmac.new(_clave_hmac(), f"token:{str(dni).strip()}:{cred_id}".encode("utf-8"),
                   hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")
 
def token_reproducible(dni, cred) -> bool:
    # True si la credencial se emitio con este sistema (su huella coincide con el codigo calculado).
    try:
        calculado = hash_texto(token_credencial(dni, cred["id"]))
        return hmac.compare_digest(calculado, str(cred.get("token_hash", "")))
    except Exception:
        return False
 
def admin_valido(usuario: str, password: str) -> bool:
    # Compatibilidad con los Secrets de la aplicacion anterior:
    # se acepta ADMIN_PASSWORD (texto en Secrets) o ADMIN_PASSWORD_HASH.
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
# Hash de relleno para que el tiempo de respuesta sea similar si el usuario no existe.
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
 
def _fijar_seccion(estado, valor):
    st.session_state[estado] = valor
 
def selector(opciones, clave):
    # Botones de seccion. El activo es el de tipo "primary". Devuelve la opcion elegida.
    estado = f"{clave}_sel"
    if st.session_state.get(estado) not in opciones:
        st.session_state[estado] = opciones[0]
    try:
        contenedor = st.container(key=f"nav_{clave}")
    except TypeError:                  # Streamlit antiguo, sin claves en contenedores
        contenedor = st.container()
    with contenedor:
        cols = st.columns(len(opciones))
        for n, op in enumerate(opciones):
            cols[n].button(op, key=f"{clave}_btn_{n}", on_click=_fijar_seccion, args=(estado, op),
                           type="primary" if st.session_state[estado] == op else "secondary")
    return st.session_state[estado]
 
def limpiar_sesion():
    for clave in list(st.session_state.keys()):
        if clave.startswith(("base_", "admin_", "mostrar_", "credencial_", "lote_")):
            del st.session_state[clave]
    st.session_state.base_id = None
    st.session_state.base_nombre = ""
    st.session_state.base_provincia = ""
    st.session_state.base_distrito = ""
    st.session_state.base_direccion = ""
    st.session_state.admin_autenticado = False
    st.session_state.es_admin = False
 
for k, v in {
    "base_id": None, "base_nombre": "", "base_provincia": "",
    "base_distrito": "", "base_direccion": "", "admin_autenticado": False,
    "es_admin": False
}.items():
    if k not in st.session_state:
        st.session_state[k] = v
     # Inicialización de estado necesaria al dividir
if "base_id" not in st.session_state:
    st.session_state.base_id = None
if "admin_autenticado" not in st.session_state:
    st.session_state.admin_autenticado = False
if "es_admin" not in st.session_state:
    st.session_state.es_admin = False
