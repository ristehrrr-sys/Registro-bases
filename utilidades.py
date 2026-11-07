import streamlit as st
import logging
from functools import lru_cache
from config import supabase, BUCKET_FOTOS, BUCKET_PLANTILLAS, APP_PUBLIC_URL
from config import clave_persona, clave_persona_legacy, hash_texto, token_credencial, token_reproducible
# DATOS
# ---------------------------------------------------------------------
def traer_todo(construir, tam=1000):
    # Supabase devuelve como maximo 1000 filas por consulta; se pide por paginas.
    filas, ini = [], 0
    while True:
        bloque = construir().range(ini, ini + tam - 1).execute().data or []
        filas.extend(bloque)
        if len(bloque) < tam:
            return filas
        ini += tam
 
def cargar_bases():
    return traer_todo(lambda: supabase.table("bases_campana")
                      .select("id,nombre_base,provincia,distrito,direccion,usuario,fecha_registro")
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
    texto = " / ".join(x for x in (base.get("provincia"), base.get("distrito")) if x)
    direccion = str(base.get("direccion") or "").strip()
    if direccion:
        texto = f"{texto} \u00b7 Direcci\u00f3n: {direccion}" if texto else f"Direcci\u00f3n: {direccion}"
    return texto
 
def excel_multihoja(hojas, titulo=None):
    # hojas: {nombre: DataFrame}. Encabezado con estilo, filtros, panel fijo y columnas ajustadas.
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
                            celda.data_type = "s"   # texto, nunca formula
                        celda.number_format = "@"
    archivo.seek(0)
    return archivo.getvalue()
 
def excel_bytes(df, hoja="Registros", titulo=None):
    return excel_multihoja({hoja: df}, titulo)
 
COLUMNAS_DETALLE = ["N.\u00ba", "Base", "Provincia", "Distrito", "Direcci\u00f3n de la base", "Apellidos", "Nombres",
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
            "Distrito": b.get("distrito") or "", "Direcci\u00f3n de la base": b.get("direccion") or "",
            "Apellidos": f.get("apellidos", ""),
            "Nombres": f.get("nombres", ""), "DNI": f.get("dni", ""),
            "Celular": f.get("celular", ""), "Cargo / condici\u00f3n": f.get("cargo") or "",
            "Fecha de registro": str(f.get("fecha_registro", ""))[:10],
        })
    return pd.DataFrame(salida, columns=COLUMNAS_DETALLE)
 
def pdf_lista(titulo, subtitulo, miembros, con_firma=False):
    # Lista imprimible de una base. con_firma=True anade columna de firma (asistencia).
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
    # Tres descargas de la lista de una base: Excel, PDF y PDF con columna de firma.
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
    # Valida que sea una imagen real, corrige la orientacion, reduce el tamano
    # y la guarda como JPEG nuevo (asi se eliminan metadatos EXIF/GPS).
    try:
        # CORRECCIÓN: leer los bytes de forma segura antes de abrir con Pillow
        contenido = archivo.getvalue()
        if not contenido:
            raise ValueError("El archivo de imagen está vacío o no se cargó correctamente.")
        im = Image.open(io.BytesIO(contenido))
        im.load()
    except Exception as e:
        # CORRECCIÓN: imprimir el error real en los logs de Streamlit
        print(f"ERROR procesando foto: {e}")
        raise ValueError("La fotograf\u00eda no es una imagen v\u00e1lida o no se pudo leer.")
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
    # Busca con la clave nueva (HMAC) y con la anterior, para no duplicar credenciales ya emitidas.
    claves = list({clave_persona(dni), clave_persona_legacy(dni)})
    filas = (supabase.table("credenciales")
             .select("id,integrante_id,estado,emitida_en,token_hash").in_("persona_key", claves)
             .limit(1).execute().data or [])
    return filas[0] if filas else None
 
def escribir_credencial(existente_id, fila):
    # "fila" trae un id nuevo: asi el codigo del QR cambia y el anterior deja de valer.
    if existente_id:
        try:
            supabase.table("credenciales").update(fila).eq("id", existente_id).execute()
            return
        except Exception as e:
            logger.warning("No se pudo actualizar la credencial %s; se reemplaza: %r", existente_id, e)
            supabase.table("credenciales").delete().eq("id", existente_id).execute()
    supabase.table("credenciales").insert(fila).execute()
 
def emitir_credencial(integrante, plantilla_id, cred_id, token):
    # Un DNI = una credencial.
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
    # Sin caracteres que se confunden (0/O, 1/l/I). Siempre con letras y numeros.
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    while True:
        clave = "".join(secrets.choice(alfabeto) for _ in range(n))
        if re.search(r"[A-Za-z]", clave) and re.search(r"\d", clave):
            return clave
 
def ruta_de_foto(url):
    # De la URL publica de la foto saca su ruta dentro del bucket.
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
    # Se usa cuando a una persona se le cambia el DNI: su credencial (ligada al DNI anterior)
    # pasa a otro registro de la misma persona si existe; si no, se elimina.
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
    # Elimina uno o muchos integrantes con todo lo que depende de ellos.
    if not integrantes:
        return
    ids = [i["id"] for i in integrantes]
    ids_set = set(ids)
    dni_de = {i["id"]: str(i.get("dni", "")).strip() for i in integrantes}
    # Otros registros de la misma persona que se conservan (otra base con el mismo DNI).
    conservados = {}
    dnis = [d for d in set(dni_de.values()) if d]
    for k in range(0, len(dnis), 50):
        filas = (supabase.table("integrantes_base").select("id,dni")
                 .in_("dni", dnis[k:k + 50]).execute().data or [])
        for f in filas:
            if f["id"] not in ids_set:
                conservados.setdefault(str(f["dni"]).strip(), f["id"])
    # Credenciales: pasan a otro registro de la misma persona o se eliminan.
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
    # La plantilla se descarga una sola vez y se reutiliza.
    return descargar_bytes(url_plantilla(path))
 
def imagen_plantilla(path):
    im = Image.open(io.BytesIO(bytes_plantilla(path)))
    im.load()
    return im.convert("RGBA")
 
def precargar_fotos(urls, max_hilos=8):
    # Descarga las fotos en paralelo (sin tocar Streamlit dentro de los hilos).
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
    # Genera las imagenes en memoria. No toca la base de datos: eso se hace despues.
    fotos = precargar_fotos(list({p["foto_url"] for p in personas if p.get("foto_url")}))
    resultados, errores = [], []
    for i, p in enumerate(personas, start=1):
        try:
            dni_p = str(p["dni"]).strip()
            if existentes is not None:
                # Volver a descargar: se reconstruye el mismo codigo de la credencial existente.
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
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:   # los PNG ya vienen comprimidos
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
        # Una credencial por pagina, respetando la proporcion de la imagen.
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
    # Hojas A4 con 8 credenciales (2 x 4). Primero los frentes y luego los reversos,
    # con las columnas invertidas para que coincidan al imprimir a doble cara.
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
    # Busca una fuente real en el sistema. Si el servidor no tiene ninguna, usa la
    # interna de Pillow con el tamano pedido (antes salia diminuta e ignoraba el tamano).
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
        import matplotlib   # si esta instalado, trae DejaVu incluida
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
        return ImageFont.load_default(size=tamano)   # Pillow 10.1 o superior
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
 
# Distribuciones predefinidas. Todas las medidas son proporciones (0 a 1) del ancho y
# del alto de la imagen, asi funcionan aunque la plantilla tenga otro tamano.
# En "campos", "y" es la altura de la linea sobre la que se escribe el dato.
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
 
# Si una plantilla con imagen no tiene distribucion guardada, se usa esta.
DISENO_POR_DEFECTO = "Marcos y l\u00edneas (ejemplo Puno)"
 
@st.cache_data(ttl=300, show_spinner=False)
def cargar_diseno(plantilla_id):
    # La distribucion de cada plantilla se guarda como diseno.json junto a sus imagenes.
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
    # Escribe sobre una linea: reduce la letra si no cabe y, en ultimo caso, recorta con "...".
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
        # Sin foto se conserva el dibujo de la plantilla (por ejemplo, la silueta).
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
    # Las credenciales ya emitidas se conservan: solo dejan de apuntar a esta plantilla.
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
        # Plantilla predeterminada si no se cargo una imagen.
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
 
    # Coordenadas relativas para adaptarse a plantillas horizontales o verticales.
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
