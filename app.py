import streamlit as st
from supabase import create_client, Client
import hashlib

# ==========================================
# 1. CONFIGURACIÓN Y DISEÑO
# ==========================================
st.set_page_config(page_title="Registro de Bases - Campaña", page_icon="🗳️")

# Ocultar menús de Streamlit
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. CONEXIÓN A SUPABASE
# ==========================================
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# Función para encriptar contraseñas
def encriptar_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ==========================================
# 3. CONTROL DE SESIÓN (Memoria de la app)
# ==========================================
if "logueado" not in st.session_state:
    st.session_state.logueado = False
if "es_admin" not in st.session_state:
    st.session_state.es_admin = False
if "nombre_usuario" not in st.session_state:
    st.session_state.nombre_usuario = ""

# ==========================================
# 4. INTERFAZ PRINCIPAL
# ==========================================
st.sidebar.title("🗳️ Menú")
opcion = st.sidebar.radio("Navegación", ["Iniciar Sesión", "Registrar mi Base", "Panel de Administrador"])

# --- CERRAR SESIÓN (Si está logueado) ---
if st.session_state.logueado:
    st.sidebar.success(f"Conectado como: {st.session_state.nombre_usuario}")
    if st.sidebar.button("Cerrar Sesión"):
        st.session_state.logueado = False
        st.session_state.es_admin = False
        st.session_state.nombre_usuario = ""
        st.rerun()

# ==========================================
# 5. VISTAS DE LA APLICACIÓN
# ==========================================

# ------------------------------------------
# VISTA 1: REGISTRO DE BASES
# ------------------------------------------
if opcion == "Registrar mi Base":
    st.title("📝 Registro de Bases de Apoyo")
    st.write("Ingresa los datos para registrar tu base en la campaña.")
    
    with st.form("formulario_registro"):
        nombre_base = st.text_input("Nombre de la Base (Ej. Base 1 - Villa El Salvador)")
        distrito = st.text_input("Distrito")
        coordenadas = st.text_input("Link de Google Maps o Coordenadas (Opcional)")
        
        st.subheader("Credenciales de Acceso")
        usuario = st.text_input("Crea un nombre de usuario (sin espacios)").strip()
        password = st.text_input("Crea una contraseña", type="password")
        
        boton_registro = st.form_submit_button("Registrar Base")

        if boton_registro:
            if not nombre_base or not usuario or not password:
                st.warning("⚠️ El nombre de la base, usuario y contraseña son obligatorios.")
            else:
                try:
                    pass_encriptada = encriptar_password(password)
                    
                    # Guardamos en la nube (Supabase)
                    supabase.table("bases_apoyo").insert({
                        "nombre_base": nombre_base,
                        "usuario": usuario,
                        "password": pass_encriptada,
                        "distrito": distrito,
                        "coordenadas": coordenadas
                    }).execute()
                    
                    st.success(f"✅ ¡La base '{nombre_base}' se ha registrado con éxito!")
                    st.balloons()
                except Exception as e:
                    st.error(f"❌ Error: Es posible que el usuario '{usuario}' ya esté en uso.")

# ------------------------------------------
# VISTA 2: INICIAR SESIÓN
# ------------------------------------------
elif opcion == "Iniciar Sesión":
    st.title("🔑 Iniciar Sesión")
    st.write("Ingresa tus credenciales para acceder a tu panel.")
    
    with st.form("formulario_login"):
        usuario_login = st.text_input("Usuario").strip()
        password_login = st.text_input("Contraseña", type="password")
        boton_login = st.form_submit_button("Ingresar")
        
        if boton_login:
            pass_encriptada = encriptar_password(password_login)
            
            # Buscamos en la base de datos si coinciden
            respuesta = supabase.table("bases_apoyo").select("*").eq("usuario", usuario_login).eq("password", pass_encriptada).execute()
            
            if len(respuesta.data) > 0:
                st.session_state.logueado = True
                st.session_state.nombre_usuario = respuesta.data[0]["nombre_base"]
                st.success("✅ ¡Bienvenido!")
                st.rerun()
            else:
                st.error("❌ Usuario o contraseña incorrectos.")

# ------------------------------------------
# VISTA 3: PANEL DE ADMINISTRADOR
# ------------------------------------------
elif opcion == "Panel de Administrador":
    st.title("👑 Panel de Administrador")
    
    # Si no es admin, le pedimos la clave secreta
    if not st.session_state.es_admin:
        st.write("Área restringida. Ingresa la clave de administrador.")
        clave_admin = st.text_input("Clave de Administrador:", type="password")
        
        if st.button("Acceder"):
            # AQUÍ PUEDES CAMBIAR TU CLAVE DE ADMINISTRADOR
            if clave_admin == "campaña2026": 
                st.session_state.es_admin = True
                st.rerun()
            else:
                st.error("❌ Clave incorrecta.")
    
    # Si ya es admin, mostramos la tabla
    else:
        st.success("Bienvenido, Administrador General.")
        
        # Descargar todos los datos
        respuesta = supabase.table("bases_apoyo").select("*").order("fecha_registro", desc=True).execute()
        
        if len(respuesta.data) > 0:
            st.subheader(f"Total de Bases Registradas: {len(respuesta.data)}")
            
            # Formatear los datos para mostrarlos bonito
            datos_tabla = []
            for fila in respuesta.data:
                datos_tabla.append({
                    "Base": fila["nombre_base"],
                    "Usuario": fila["usuario"],
                    "Distrito": fila["distrito"],
                    "Coordenadas": fila["coordenadas"],
                    "Fecha": fila["fecha_registro"][:10] # Solo la fecha (YYYY-MM-DD)
                })
            
            # Mostrar la tabla
            st.dataframe(datos_tabla, use_container_width=True)
        else:
            st.info("Aún no hay bases registradas en el sistema.")
