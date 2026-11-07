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
    "OTRO"
]

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
    st.session_state.base_direccion = ""
    st.session_state.admin_autenticado = False
    st.session_state.es_admin = False
