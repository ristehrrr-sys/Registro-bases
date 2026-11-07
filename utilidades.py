import streamlit as st
import hashlib
import secrets
import hmac
import base64
import re
import io
import uuid
import time
import logging
import json
import copy
import zipfile
from functools import lru_cache
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from urllib.parse import quote, unquote

import pandas as pd
import requests
import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageOps

# Importamos las configuraciones y funciones base
from config import (supabase, BUCKET_FOTOS, BUCKET_PLANTILLAS, APP_PUBLIC_URL, 
                    clave_persona, clave_persona_legacy, hash_texto, 
                    token_credencial, token_reproducible)

logger = logging.getLogger("registro_bases")

def nombre_completo(f):
    return f'{f.get("nombres", "")} {f.get("apellidos", "")}'.strip()

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

def subir_foto_integrante(path, contenido):
    try:
        supabase.storage.from_(BUCKET_FOTOS).upload(
            path=path,
            file=bytes(contenido),
            file_options={
                "content-type": "image/jpeg",
                "cache-control": "3600",
                "upsert": "false",
            },
        )
        url = supabase.storage.from_(BUCKET_FOTOS).get_public_url(path)
        if not url:
            raise RuntimeError("Supabase no devolvio la URL publica de la fotografia.")
        return url
    except Exception as e:
        raise RuntimeError(
            "No se pudo subir la fotografia al bucket 'fotos_integrantes'. "
            "Verifica que el bucket exista y que SUPABASE_KEY tenga permiso de INSERT en Storage. "
            f"Detalle: {str(e)[:350]}"
        ) from e
 
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
        datos_foto = procesar_foto(foto)
        datos["foto_url"] = subir_foto_integrante(path, datos_foto)
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
        return f"{carpeta}/{bold if neg
