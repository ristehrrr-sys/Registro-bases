import streamlit as st
from supabase import create_client

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
