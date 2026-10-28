
import streamlit as st
from supabase import create_client
import hashlib
import secrets
import hmac
import re

st.set_page_config(
    page_title="Registro de Bases y Comandos",
    page_icon="🗳️",
    layout="wide"
)

# ---------- CONEXIÓN ----------
@st.cache_resource
def conectar_supabase():
    url = st.secrets["SUPABASE_URL"].strip()
    key = st.secrets["SUPABASE_KEY"].strip()
    return create_client(url, key)

try:
    supabase = conectar_supabase()
except Exception:
    st.error(
        "No se pudo conectar con la base de datos. "
        "Revisa SUPABASE_URL y SUPABASE_KEY en Streamlit Secrets."
    )
    st.stop()


# ---------- CONTRASEÑAS ----------
def crear_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 310000
    ).hex()
    return f"{salt}${digest}"


def verificar_password(password, guardada):
    try:
        salt, digest = guardada.split("$", 1)
        calculado = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), 310000
        ).hex()
        return hmac.compare_digest(calculado, digest)
    except (ValueError, TypeError):
        return False


# ---------- SESIÓN ----------
if "base_id" not in st.session_state:
    st.session_state.base_id = None

if "base_nombre" not in st.session_state:
    st.session_state.base_nombre = ""

if "es_admin" not in st.session_state:
    st.session_state.es_admin = False


# ---------- ENCABEZADO ----------
st.title("🗳️ Registro de Bases y Comandos")
st.caption("Sistema de registro y administración de integrantes")


# ---------- REGISTRO DE UNA BASE ----------
if st.session_state.base_id is None and not st.session_state.es_admin:

    col1, col2 = st.columns(2)

    with col1:
        if st.button("➕ Agregar base o comando", use_container_width=True):
            st.session_state.mostrar_registro = True

    with col2:
        if st.button("🔑 Iniciar sesión", use_container_width=True):
            st.session_state.mostrar_registro = False

    if st.session_state.get("mostrar_registro", False):
        st.subheader("Registrar una nueva base o comando")

        with st.form("registro_base"):
            nombre = st.text_input("Nombre de la base o comando")
            distrito = st.text_input("Distrito")
            usuario = st.text_input("Crear nombre de usuario").strip()
            password = st.text_input(
                "Crear contraseña", type="password"
            )
            confirmar = st.text_input(
                "Confirmar contraseña", type="password"
            )
            acepta = st.checkbox(
                "Confirmo que estoy autorizado a registrar esta base "
                "y que he leído el aviso de privacidad."
            )
            enviar = st.form_submit_button("Registrar base")

        if enviar:
            if not all([nombre.strip(), distrito.strip(), usuario, password]):
                st.warning("Completa todos los campos.")
            elif not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", usuario):
                st.warning(
                    "El usuario debe tener entre 3 y 40 caracteres "
                    "y solo puede usar letras, números, punto, guion "
                    "o guion bajo."
                )
            elif len(password) < 12:
                st.warning(
                    "Usa una contraseña de al menos 12 caracteres."
                )
            elif password != confirmar:
                st.warning("Las contraseñas no coinciden.")
            elif not acepta:
                st.warning("Debes confirmar la autorización.")
            else:
                try:
                    existe = (
                        supabase.table("bases_campana")
                        .select("id")
                        .eq("usuario", usuario)
                        .limit(1)
                        .execute()
                    )

                    if existe.data:
                        st.error("Ese nombre de usuario ya está ocupado.")
                    else:
                        supabase.table("bases_campana").insert({
                            "nombre_base": nombre.strip(),
                            "distrito": distrito.strip(),
                            "usuario": usuario,
                            "password_hash": crear_hash(password)
                        }).execute()

                        st.success(
                            "Base registrada. Ya puedes iniciar sesión."
                        )
                        st.session_state.mostrar_registro = False

                except Exception:
                    st.error(
                        "No se pudo registrar la base. "
                        "Verifica la conexión y la configuración de Supabase."
                    )

    else:
        st.subheader("Acceso de bases y comandos")

        with st.form("inicio_sesion"):
            usuario_login = st.text_input("Usuario").strip()
            password_login = st.text_input(
                "Contraseña", type="password"
            )
            entrar = st.form_submit_button("Ingresar")

        if entrar:
            try:
                resultado = (
                    supabase.table("bases_campana")
                    .select("id,nombre_base,distrito,usuario,password_hash")
                    .eq("usuario", usuario_login)
                    .limit(1)
                    .execute()
                )

                if (
                    resultado.data
                    and verificar_password(
                        password_login,
                        resultado.data[0]["password_hash"]
                    )
                ):
                    cuenta = resultado.data[0]
                    st.session_state.base_id = cuenta["id"]
                    st.session_state.base_nombre = cuenta["nombre_base"]
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos.")

            except Exception:
                st.error("No se pudo comprobar el acceso.")


# ---------- PANEL DE LA BASE ----------
if st.session_state.base_id is not None:
    base_id = st.session_state.base_id

    st.success(f"Sesión: {st.session_state.base_nombre}")
    st.subheader("👥 Integrantes de tu base")

    if st.button("➕ Agregar integrante"):
        st.session_state.mostrar_integrante = True

    if st.session_state.get("mostrar_integrante", False):
        with st.form("form_integrante"):
            nombres = st.text_input("Nombres")
            apellidos = st.text_input("Apellidos")
            dni = st.text_input("DNI (8 dígitos)")
            celular = st.text_input("Número de celular")
            consentimiento = st.checkbox(
                "Confirmo que la persona conoce el uso de sus datos "
                "y autorizó su registro."
            )
            guardar = st.form_submit_button("Guardar integrante")

        if guardar:
            if not nombres.strip() or not apellidos.strip():
                st.warning("Completa nombres y apellidos.")
            elif not re.fullmatch(r"\d{8}", dni.strip()):
                st.warning("El DNI debe contener exactamente 8 dígitos.")
            elif not re.fullmatch(r"\+?\d{9,15}", celular.strip()):
                st.warning(
                    "Ingresa un celular válido, con 9 a 15 dígitos."
                )
            elif not consentimiento:
                st.warning("Debes confirmar la autorización.")
            else:
                try:
                    supabase.table("integrantes_base").insert({
                        "base_id": base_id,
                        "nombres": nombres.strip(),
                        "apellidos": apellidos.strip(),
                        "dni": dni.strip(),
                        "celular": celular.strip()
                    }).execute()

                    st.success("Integrante registrado.")
                    st.session_state.mostrar_integrante = False
                    st.rerun()

                except Exception:
                    st.error(
                        "No se pudo guardar el integrante. "
                        "Comprueba si ese DNI ya está registrado "
                        "en esta base."
                    )

    try:
        integrantes = (
            supabase.table("integrantes_base")
            .select("nombres,apellidos,dni,celular,fecha_registro")
            .eq("base_id", base_id)
            .order("fecha_registro", desc=True)
            .execute()
        )

        filas = integrantes.data or []
        st.metric("Total de integrantes", len(filas))

        if filas:
            st.dataframe(
                [
                    {
                        "Nombres": f["nombres"],
                        "Apellidos": f["apellidos"],
                        "DNI": f["dni"],
                        "Celular": f["celular"],
                        "Fecha": str(f["fecha_registro"])[:10]
                    }
                    for f in filas
                ],
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Todavía no hay integrantes registrados.")

    except Exception:
        st.error("No se pudo cargar la lista de integrantes.")

    if st.button("Cerrar sesión"):
        st.session_state.base_id = None
        st.session_state.base_nombre = ""
        st.session_state.mostrar_integrante = False
        st.rerun()


# ---------- AVISO DE PRIVACIDAD ----------
st.divider()
with st.expander("Aviso de privacidad"):
    st.write(
        "Los nombres, DNI y teléfonos son datos personales. "
        "Deben recopilarse con autorización y una finalidad informada, "
        "limitar el acceso a personas autorizadas, protegerse y "
        "conservarse solo durante el tiempo necesario. "
        "No registres datos de personas que no hayan sido informadas."
    )
