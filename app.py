import streamlit as st
from config import *
from utilidades import *
# INICIALIZAR VARIABLES DE SESION
for k, v in {
    "base_id": None,
    "base_nombre": "",
    "base_provincia": "",
    "base_distrito": "",
    "base_direccion": "",
    "admin_autenticado": False,
    "es_admin": False
}.items():
    if k not in st.session_state:
        st.session_state[k] = v 
# VERIFICACION PUBLICA DEL QR
# ---------------------------------------------------------------------
st.markdown('<div class="top"><div class="av">\U0001f5f3\ufe0f</div><div class="tt"><div class="n">Registro de Bases y Comandos</div><div class="s">Gesti\u00f3n de bases, integrantes y credenciales verificables</div></div></div>', unsafe_allow_html=True)
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
                     .select("id,nombre_base,provincia,distrito,direccion,usuario,password_hash")
                     .eq("usuario", usuario_login).limit(1).execute())
                hash_guardado = r.data[0].get("password_hash", "") if r.data else HASH_FICTICIO
                if verificar_password(password_login, hash_guardado) and r.data:
                    limpiar_fallos(clave_rl)
                    b = r.data[0]
                    st.session_state.base_id = b["id"]
                    st.session_state.base_nombre = b["nombre_base"]
                    st.session_state.base_provincia = b.get("provincia") or ""
                    st.session_state.base_distrito = b.get("distrito") or ""
                    st.session_state.base_direccion = b.get("direccion") or ""
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
    st.markdown('<div class="chip"><span class="dot"></span>Administrador \u00b7 en l\u00ednea</div>', unsafe_allow_html=True)
    if not str(st.secrets.get("ADMIN_PASSWORD_HASH", "")).strip():
        st.warning("Est\u00e1s usando ADMIN_PASSWORD en texto plano. Conviene reemplazarlo por ADMIN_PASSWORD_HASH en Secrets.")
    # Navegacion administrativa: menus desplegables. Se conservan intactas
    # las secciones y operaciones existentes; solo cambia la forma de navegar.
    st.markdown("""
    <div class="admin-nav-heading">
      <div class="admin-nav-kicker">CENTRO DE CONTROL</div>
      <div class="admin-nav-title">Panel de administración</div>
      <div class="admin-nav-caption">Selecciona un módulo para gestionar el registro.</div>
    </div>
    """, unsafe_allow_html=True)
 
    menu_opciones = ["Bases", "Reuniones", "Credenciales", "Exportar", "Plantillas"]
    if st.session_state.get("admin_menu_actual") not in menu_opciones:
        st.session_state.admin_menu_actual = "Bases"
    panel = st.selectbox(
        "Módulo principal",
        menu_opciones,
        key="admin_menu_actual",
        format_func=lambda x: {
            "Bases": "👥  Bases e integrantes",
            "Reuniones": "📅  Reuniones y asistencia",
            "Credenciales": "🪪  Credenciales QR",
            "Exportar": "📤  Exportación de datos",
            "Plantillas": "🎨  Plantillas de credenciales",
        }.get(x, x),
    )
 
    sub = ""
    sub_opciones = {
        "Bases": ["Integrantes", "Crear base", "Administrar"],
        "Credenciales": ["Una persona", "Varias personas", "Generadas"],
    }
    if panel in sub_opciones:
        opciones_sub = sub_opciones[panel]
        clave_sub = "admin_sub_bases_actual" if panel == "Bases" else "admin_sub_cred_actual"
        if st.session_state.get(clave_sub) not in opciones_sub:
            st.session_state[clave_sub] = opciones_sub[0]
        iconos_sub = {
            "Integrantes": "👤  Consultar integrantes",
            "Crear base": "➕  Crear nueva base",
            "Administrar": "⚙️  Administrar registros",
            "Una persona": "🪪  Credencial individual",
            "Varias personas": "👥  Emisión por lote",
            "Generadas": "📋  Credenciales emitidas",
        }
        sub = st.selectbox(
            "Sección",
            opciones_sub,
            key=clave_sub,
            format_func=lambda x: iconos_sub.get(x, x),
        )
    st.markdown('<div class="admin-nav-separator"></div>', unsafe_allow_html=True)
 
    if panel == "Bases" and sub == "Crear base":
        st.subheader("Crear una base o comando")
        # Provincia y Distrito van FUERA de st.form: dentro de un formulario Streamlit no
        # vuelve a ejecutar la app al cambiar la provincia, y el distrito se quedaba sin opciones.
        n_cb = st.session_state.get("admin_crear_base_n", 0)
        msg_cb = st.session_state.pop("mostrar_msg_crear_base", None)
        if msg_cb:
            st.success(msg_cb)
        with st.container(border=True):
            nombre = st.text_input("Nombre de la base o comando", key=f"admin_cb_nombre_{n_cb}")
            provincia = st.selectbox("Provincia", ["Seleccionar provincia"] + PROVINCIAS,
                                     key=f"admin_cb_prov_{n_cb}")
            ds = sorted(DISTRITOS_PUNO.get(provincia, []))
            # La clave incluye la provincia: al cambiarla, el distrito se reinicia con sus opciones.
            distrito = st.selectbox("Distrito", ["Seleccionar distrito"] + ds,
                                    key=f"admin_cb_dist_{n_cb}_{provincia}", disabled=not ds)
            direccion = st.text_input("Direcci\u00f3n de la base o comando",
                                      placeholder="Ej.: Jr. Lima 123, a una cuadra de la plaza",
                                      key=f"admin_cb_dir_{n_cb}")
            usuario = st.text_input("Crear usuario de la base", key=f"admin_cb_user_{n_cb}").strip()
            password = st.text_input("Contrase\u00f1a inicial (m\u00ednimo 10 caracteres, con letras y n\u00fameros)",
                                     type="password", key=f"admin_cb_pw_{n_cb}")
            confirmar = st.text_input("Confirmar contrase\u00f1a", type="password", key=f"admin_cb_pw2_{n_cb}")
            acepta = st.checkbox("Confirmo que estoy autorizado para crear esta cuenta.",
                                 key=f"admin_cb_ok_{n_cb}")
            crear = st.button("Crear base", key=f"admin_cb_btn_{n_cb}")
        if crear:
            creada = False
            if (not nombre.strip() or provincia not in DISTRITOS_PUNO or distrito not in ds
                    or not direccion.strip()):
                st.warning("Completa el nombre, la provincia, el distrito y la direcci\u00f3n.")
            elif len(direccion.strip()) < 5:
                st.warning("Escribe una direcci\u00f3n m\u00e1s completa para poder ubicar la base.")
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
                            "distrito": distrito, "direccion": direccion.strip(), "usuario": usuario,
                            "password_hash": crear_hash(password)
                        }).execute()
                        creada = True
                except Exception as e:
                    error_supabase("No se pudo crear la base.", e)
            if creada:
                # Se cambia el contador para que el formulario aparezca limpio.
                st.session_state["admin_crear_base_n"] = n_cb + 1
                st.session_state["mostrar_msg_crear_base"] = "Base creada correctamente."
                st.rerun()
 
 
    if panel == "Bases" and sub == "Integrantes":
        st.subheader("Bases e integrantes")
        try:
            bases = cargar_bases()
            if bases:
                mapa = {f'{b["nombre_base"]} \u2014 {b.get("provincia") or ""}/{b.get("distrito") or ""} (ID {b["id"]})': b for b in bases}
                label = st.selectbox("Seleccionar base", list(mapa.keys()))
                bsel = mapa[label]
                miembros = cargar_integrantes(bsel["id"])
                st.write(f'**Direcci\u00f3n de la base:** {bsel.get("direccion") or "Sin direcci\u00f3n registrada"}')
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
 
    if panel == "Bases" and sub == "Administrar":
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
                di = st.text_input("Direcci\u00f3n de la base o comando", value=bad.get("direccion") or "",
                                   key=f"admin_di_{bid}")
                us = st.text_input("Usuario de la base", value=bad["usuario"], key=f"admin_us_{bid}").strip()
                if st.button("Guardar datos de la base", key=f"admin_gb_{bid}"):
                    if not nb.strip() or pv not in DISTRITOS_PUNO or ds not in dss or not di.strip():
                        st.warning("Completa el nombre, la provincia, el distrito y la direcci\u00f3n.")
                    elif not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", us):
                        st.warning("El usuario debe tener de 3 a 40 caracteres v\u00e1lidos.")
                    elif (supabase.table("bases_campana").select("id").eq("usuario", us)
                          .neq("id", bid).limit(1).execute().data):
                        st.error("Ese usuario ya est\u00e1 ocupado por otra base.")
                    else:
                        supabase.table("bases_campana").update({
                            "nombre_base": nb.strip(), "provincia": pv, "distrito": ds,
                            "direccion": di.strip(), "usuario": us
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
                        # CORRECCIÓN: Se quitó clear_on_submit=True para evitar que la foto se borre antes de procesarse.
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
 
    if panel == "Reuniones":
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
 
    if panel == "Exportar":
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
                    "Direcci\u00f3n": b.get("direccion") or "",
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
 
    if panel == "Credenciales" and sub == "Una persona":
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
                # Recupera las bases asociadas al mismo DNI; no publica DNI en el QR.
                bases_info = datos_bases_por_dni(integrante["dni"])
                principal = next((b for b in bases_info if b["id"] == integrante.get("base_id")),
                                 bases_info[0] if bases_info else {})
                integrante_render = dict(integrante)
                integrante_render["nombre_base"] = ", ".join(b["nombre_base"] for b in bases_info)
                # Antes la provincia y el distrito salian vacios en la credencial.
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
                vigente = bool(cred_actual) and cred_actual.get("estado") == "vigente"
                accion = None
                if vigente:
                    st.write(f'**Estado de la credencial:** {cred_actual["estado"]} \u00b7 emitida el {str(cred_actual.get("emitida_en", ""))[:10]}')
                    if token_reproducible(integrante["dni"], cred_actual):
                        if st.button("Volver a descargar credencial", type="primary", key="redescargar_cred"):
                            accion = "descargar"
                        st.caption("Muestra la misma credencial, con el mismo QR. No cambia nada.")
                    else:
                        st.info("Esta credencial se emiti\u00f3 con una versi\u00f3n anterior y no se puede volver a descargar. "
                                "Elim\u00ednala y gen\u00e9rala de nuevo una sola vez; desde entonces ya podr\u00e1s volver a descargarla.")
                    confirma_borrar = st.checkbox("Confirmo que quiero eliminar esta credencial",
                                                  key=f'credencial_conf_{integrante["dni"]}')
                    if st.button("Eliminar credencial", key="eliminar_cred", disabled=not confirma_borrar):
                        supabase.table("credenciales").delete().eq("id", cred_actual["id"]).execute()
                        st.session_state.pop("credencial_generada", None)
                        st.session_state.pop("credencial_reverso", None)
                        st.success("Credencial eliminada. Su QR ya no es v\u00e1lido. Ahora puedes generar una nueva.")
                elif st.button("Generar credencial", type="primary", key="generar_cred"):
                    accion = "nueva"
                if accion:
                    if not APP_PUBLIC_URL:
                        st.error("No se puede emitir un QR funcional hasta configurar APP_PUBLIC_URL.")
                    else:
                        # Primero se generan las imagenes; solo se guarda en la base si todo salio bien.
                        cred_id = cred_actual["id"] if accion == "descargar" else str(uuid.uuid4())
                        token = token_credencial(integrante["dni"], cred_id)
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
                        if accion == "nueva":
                            emitir_credencial(integrante, plantilla.get("id"), cred_id, token)
                        st.session_state["credencial_generada"] = buffer.getvalue()
                        st.session_state["credencial_dni"] = str(integrante["dni"])
                        st.session_state["credencial_nombre"] = re.sub(r"[^A-Za-z0-9_-]", "_", str(integrante["dni"]))
                        if reverso_bytes:
                            st.session_state["credencial_reverso"] = reverso_bytes
                        else:
                            st.session_state.pop("credencial_reverso", None)
                        if accion == "descargar":
                            st.success("Credencial lista para descargar. Es la misma de siempre, con el mismo QR.")
                        else:
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
 
    if panel == "Credenciales" and sub == "Varias personas":
        st.subheader("\U0001faaa Credenciales de varias personas")
        st.caption("Genera varias credenciales a la vez y desc\u00e1rgalas en ZIP o en PDF listo para imprimir.")
        f_zip = "ZIP con im\u00e1genes PNG"
        f_pdf = "PDF (una credencial por p\u00e1gina)"
        f_a4 = "PDF A4 para imprimir (8 por hoja)"
        M_FALTAN = "Generar las que a\u00fan no tienen credencial"
        M_DESCARGAR = "Volver a descargar las ya generadas"
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
                    sel = st.selectbox("Base", list(opciones.keys()), key="lote_base")
                    modo = st.radio("\u00bfQu\u00e9 quieres hacer?", [M_FALTAN, M_DESCARGAR], key="lote_modo")
                    id_base = opciones[sel]
                    unicos = {}
                    for f in todos:
                        d = str(f.get("dni", "")).strip()
                        if d and d not in unicos and (id_base is None or f["base_id"] == id_base):
                            unicos[d] = f
                    personas = sorted(unicos.values(), key=lambda x: (str(x.get("apellidos", "")).lower(),
                                                                       str(x.get("nombres", "")).lower()))
                    estados_cred = mapa_estados_credenciales()
                    estados, filas_cred = {}, {}
                    for p in personas:
                        d = str(p["dni"]).strip()
                        fila_c = estados_cred.get(clave_persona(d)) or estados_cred.get(clave_persona_legacy(d))
                        if fila_c:
                            filas_cred[d] = fila_c
                        estados[d] = fila_c["estado"] if fila_c else "sin credencial"
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Personas", len(personas))
                    m2.metric("Sin credencial", sum(1 for v in estados.values() if v == "sin credencial"))
                    m3.metric("Vigentes", sum(1 for v in estados.values() if v == "vigente"))
                    m4.metric("Revocadas", sum(1 for v in estados.values() if v == "revocada"))
                    if modo == M_FALTAN:
                        cola = [p for p in personas if estados[str(p["dni"]).strip()] == "sin credencial"]
                    else:
                        cola = [p for p in personas if estados[str(p["dni"]).strip()] == "vigente"]
                    if not cola:
                        st.info("No hay personas para esta opci\u00f3n con este filtro.")
                    else:
                        et_personas = {f'{nombre_completo(p)} (DNI {p["dni"]})': p for p in cola}
                        elegidas = st.multiselect(
                            "Elegir personas (opcional; si no eliges ninguna, se usan todas las de la lista)",
                            list(et_personas.keys()), key=f"lote_personas_{id_base}_{modo}")
                        if elegidas:
                            cola = [et_personas[e] for e in elegidas if e in et_personas] or cola
                        tam = st.selectbox("Credenciales por tanda", [25, 50, 100], index=1, key="lote_tam")
                        n_tandas = -(-len(cola) // tam)
                        if modo == M_FALTAN or n_tandas == 1:
                            tanda = 1
                        else:
                            tanda = st.number_input("Tanda", min_value=1, max_value=n_tandas,
                                                    value=1, step=1, key="lote_tanda")
                        lote = cola[(tanda - 1) * tam: tanda * tam]
                        extra = f", tanda {tanda} de {n_tandas}" if (modo != M_FALTAN and n_tandas > 1) else ""
                        st.write(f"Se preparar\u00e1n **{len(lote)}** credenciales ({len(cola)} en total{extra}).")
                        formatos = st.multiselect("Formatos de descarga", [f_zip, f_pdf, f_a4],
                                                  default=[f_zip, f_a4], key="lote_formatos")
                        etiqueta = "Generar" if modo == M_FALTAN else "Descargar"
                        plantilla = plantilla_activa()
                        st.caption(f'Plantilla: {plantilla["nombre"]}')
                        if st.button(f"{etiqueta} {len(lote)} credenciales", type="primary",
                                     disabled=not formatos, key="lote_generar"):
                            barra = st.progress(0.0, text="Preparando\u2026")
 
                            def avance(i, total):
                                barra.progress(i / total, text=f"Generando credencial {i} de {total}\u2026")
 
                            existentes = ({str(p["dni"]).strip(): filas_cred[str(p["dni"]).strip()] for p in lote}
                                          if modo == M_DESCARGAR else None)
                            resultados, errores = generar_lote(lote, plantilla, dni_bases, avance, existentes)
                            if resultados:
                                if modo == M_FALTAN:
                                    barra.progress(1.0, text="Guardando en la base de datos\u2026")
                                    guardar_credenciales_lote(resultados, plantilla.get("id"))
                                archivos = {"sello": datetime.now().strftime("%Y%m%d_%H%M"),
                                            "n": len(resultados), "descarga": modo == M_DESCARGAR,
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
                        if archivos.get("descarga"):
                            st.success(f'{archivos["n"]} credenciales listas para descargar (mismos QR de siempre).')
                        else:
                            st.success(f'{archivos["n"]} credenciales generadas y registradas.')
                        if archivos["errores"]:
                            st.warning("No se pudieron preparar: " + ", ".join(archivos["errores"]))
                            if archivos.get("descarga"):
                                st.caption("Esas credenciales se emitieron con una versi\u00f3n anterior. Elim\u00ednalas desde "
                                           "\u00abCredenciales generadas\u00bb y gen\u00e9ralas de nuevo una sola vez.")
                        st.caption("Si pierdes los archivos, puedes volver a descargarlas con la opci\u00f3n "
                                   "\u00abVolver a descargar las ya generadas\u00bb.")
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
                error_supabase("No se pudo completar la generaci\u00f3n de varias credenciales.", e)
 
    if panel == "Credenciales" and sub == "Generadas":
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
 
    if panel == "Plantillas":
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
    st.markdown(f'<div class="chip"><span class="dot"></span>{_html.escape(str(st.session_state.base_nombre))} \u00b7 {_html.escape(str(st.session_state.base_provincia))} / {_html.escape(str(st.session_state.base_distrito))}</div>', unsafe_allow_html=True)
    st.subheader("Integrantes de tu base")
    with st.expander("Agregar integrante", expanded=False):
        # CORRECCIÓN: Se quitó clear_on_submit=True para evitar que la foto se borre antes de procesarse.
        with st.form("form_integrante"):
            nombres = st.text_input("Nombres")
            apellidos = st.text_input("Apellidos")
            dni = st.text_input("DNI (8 d\u00edgitos)")
            celular = st.text_input("Celular (9 a 15 d\u00edgitos)")
            cargo_sel = st.selectbox("Cargo o condici\u00f3n", CARGOS)
            cargo_otro = st.text_input("Especifica el cargo") if cargo_sel == "Otro" else ""
            foto = st.file_uploader("Fotograf\u00eda del integrante (opcional)", type=["jpg", "jpeg", "png"])
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
                            # La imagen se revalida y se recomprime (sin metadatos/GPS),
                            # y el nombre del archivo ya no contiene el DNI.
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
                           "distrito": st.session_state.base_distrito,
                           "direccion": st.session_state.get("base_direccion", "")}, filas, "mi_base")
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
