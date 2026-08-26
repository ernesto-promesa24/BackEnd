"""
firebase_db.py
--------------
Capa de acceso a datos sobre Firebase.

- Firestore guarda los documentos (clientes, tipos, servicios, incidencias).
- Firebase Storage guarda los archivos de evidencia (fotos y PDF).

Las credenciales NUNCA se escriben en el código: se leen de variables de
entorno. En Render se configuran así:

    FIREBASE_CREDENTIALS      -> contenido completo del JSON de la cuenta
                                 de servicio (pegado como texto en una sola
                                 variable)
    FIREBASE_STORAGE_BUCKET   -> p.ej. mi-proyecto.appspot.com

Para desarrollo local también se acepta:

    GOOGLE_APPLICATION_CREDENTIALS -> ruta a un archivo .json

Colecciones en Firestore:
    clientes           { nombre, categoria, estado, frecuencia,
                         frecuencia_original, activo, cobro_por_recoleccion,
                         estatus }
    tipos_incidencia   { nombre, descripcion, gravedad_default, activo }
    servicios          { fecha, cliente_id, cliente, categoria, estado,
                         frecuencia, cobro_por_recoleccion, tipo_servicio,
                         hora_programada, hora_real, realizado, resultado,
                         responsable, observaciones, creado_en }
    incidencias        { servicio_id, tipo_incidencia_id, tipo_incidencia,
                         gravedad, descripcion, reporto_cliente, resuelta,
                         resuelta_a_tiempo, fecha_resolucion, accion_correctiva,
                         comentarios, vueltas_adicionales, minutos_retraso,
                         segunda_vuelta_no_cobrable, material_pendiente,
                         fecha, cliente_id, cliente, categoria, estado,
                         frecuencia, cobro_por_recoleccion, es_prioritario,
                         tipo_servicio, responsable, evidencias[], creado_en }
    catalogos          un documento por catálogo ampliable (categorias,
                       estados, frecuencias) con { valores: [...] }: las
                       opciones que se agregaron desde el formulario de
                       clientes, además de las de fábrica de utilidades.py

Nota de diseño: en las incidencias se DENORMALIZAN algunos campos del
servicio (fecha, cliente, estado...). En Firestore no existen los JOIN de
SQL, así que duplicar esos datos permite filtrar y graficar leyendo una
sola colección, que es mucho más rápido y barato en lecturas.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import firebase_admin
from firebase_admin import credentials, firestore, storage

from modulos import utilidades as ut

# Nombres de las colecciones
COL_CLIENTES = "clientes"
COL_TIPOS = "tipos_incidencia"
COL_SERVICIOS = "servicios"
COL_INCIDENCIAS = "incidencias"
# Opciones que el usuario agrega a los catálogos de categoría, estado y
# frecuencia. Un documento por catálogo, con un arreglo `valores`.
COL_CATALOGOS = "catalogos"

_app = None
_db = None
_bucket = None


# ---------------------------------------------------------------------------
# Inicialización
# ---------------------------------------------------------------------------
def inicializar():
    """Inicializa Firebase una sola vez, leyendo las credenciales del entorno."""
    global _app, _db, _bucket
    if _app is not None:
        return

    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")

    credenciales_json = os.environ.get("FIREBASE_CREDENTIALS")
    if credenciales_json:
        # Render: el JSON completo viene pegado en una variable de entorno
        cred = credentials.Certificate(json.loads(credenciales_json))
    elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        # Local: ruta a un archivo .json de cuenta de servicio
        cred = credentials.Certificate(
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    else:
        raise RuntimeError(
            "Faltan credenciales de Firebase. Define FIREBASE_CREDENTIALS "
            "(JSON completo) o GOOGLE_APPLICATION_CREDENTIALS (ruta al .json)."
        )

    opciones = {"storageBucket": bucket_name} if bucket_name else {}
    _app = firebase_admin.initialize_app(cred, opciones)
    _db = firestore.client()
    _bucket = storage.bucket() if bucket_name else None


def db():
    """Cliente de Firestore (inicializa si hace falta)."""
    if _db is None:
        inicializar()
    return _db


def bucket():
    """Bucket de Firebase Storage."""
    if _bucket is None:
        inicializar()
    return _bucket


def _ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _con_id(doc):
    """Convierte un documento de Firestore en dict incluyendo su id."""
    datos = doc.to_dict() or {}
    datos["id"] = doc.id
    return datos


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
def listar_clientes():
    docs = db().collection(COL_CLIENTES).stream()
    clientes = [_con_id(d) for d in docs]
    return sorted(clientes, key=lambda c: c.get("nombre", ""))


def obtener_cliente(cliente_id):
    doc = db().collection(COL_CLIENTES).document(cliente_id).get()
    return _con_id(doc) if doc.exists else None


def crear_cliente(datos):
    """Crea un cliente. `datos` ya viene validado desde app.py."""
    ref = db().collection(COL_CLIENTES).document()
    ref.set({
        "nombre": datos["nombre"],
        "categoria": datos.get("categoria", "Empresa"),
        "estado": datos.get("estado", "Ciudad de México"),
        "frecuencia": datos.get("frecuencia", "Mensual"),
        "frecuencia_original": datos.get("frecuencia", "Mensual"),
        "activo": bool(datos.get("activo", True)),
        "cobro_por_recoleccion": bool(datos.get("cobro_por_recoleccion", False)),
        "estatus": "Activo" if datos.get("activo", True) else "Sin recolecciones",
    })
    return ref.id


def existe_cliente_con_nombre(nombre, excluir_id=None):
    """¿Ya hay un cliente con ese nombre?

    La comparación ignora mayúsculas, acentos y espacios sobrantes, así que
    "walmart norte" y "Walmart  Norte" cuentan como el mismo cliente.
    `excluir_id` sirve al editar: el propio cliente no se compara consigo mismo.
    """
    clave = ut.clave_opcion(nombre)
    for cliente in listar_clientes():
        if excluir_id and cliente.get("id") == excluir_id:
            continue
        if ut.clave_opcion(cliente.get("nombre")) == clave:
            return True
    return False


# Campos del cliente que se copian (denormalizan) en servicios e incidencias.
# Al editar un cliente hay que refrescarlos ahí también, o el dashboard
# seguiría mostrando el dato viejo.
def _propagar_cliente(cliente_id, cliente):
    """Refresca los datos del cliente copiados en servicios e incidencias.

    Devuelve cuántos documentos se actualizaron. Se usan lotes (batch)
    porque un cliente puede tener muchos servicios.
    """
    denormalizado = {
        "cliente": cliente["nombre"],
        "categoria": cliente["categoria"],
        "estado": cliente["estado"],
        "frecuencia": cliente["frecuencia"],
        "cobro_por_recoleccion": cliente["cobro_por_recoleccion"],
    }
    base = db()
    total = 0

    for coleccion in (COL_SERVICIOS, COL_INCIDENCIAS):
        cambios = dict(denormalizado)
        if coleccion == COL_INCIDENCIAS:
            # En incidencias, «prioritario» sale del cobro por recolección
            cambios["es_prioritario"] = cliente["cobro_por_recoleccion"]

        documentos = (base.collection(coleccion)
                      .where(filter=firestore.FieldFilter("cliente_id", "==", cliente_id))
                      .stream())

        lote, en_lote = base.batch(), 0
        for doc in documentos:
            lote.update(doc.reference, cambios)
            en_lote += 1
            total += 1
            if en_lote >= 400:          # Firestore permite hasta 500 por lote
                lote.commit()
                lote, en_lote = base.batch(), 0
        if en_lote:
            lote.commit()

    return total


def actualizar_cliente(cliente_id, datos):
    """Corrige los datos de un cliente ya registrado.

    Los campos que no vengan en `datos` conservan su valor anterior. Devuelve
    cuántos servicios e incidencias se refrescaron con los datos nuevos.
    """
    ref = db().collection(COL_CLIENTES).document(cliente_id)
    documento = ref.get()
    if not documento.exists:
        raise ValueError("El cliente indicado no existe.")
    previo = documento.to_dict() or {}

    activo = bool(datos.get("activo", previo.get("activo", True)))
    cambios = {
        "nombre": datos["nombre"],
        "categoria": datos.get("categoria") or previo.get("categoria", "Empresa"),
        "estado": datos.get("estado") or previo.get("estado", "Ciudad de México"),
        "frecuencia": datos.get("frecuencia") or previo.get("frecuencia", "Mensual"),
        "activo": activo,
        "cobro_por_recoleccion": bool(datos.get("cobro_por_recoleccion", False)),
        "estatus": "Activo" if activo else "Sin recolecciones",
    }
    # `frecuencia_original` guarda lo que decía el Excel de origen: es un dato
    # histórico y no se toca al editar.
    ref.update(cambios)
    return _propagar_cliente(cliente_id, cambios)


# ---------------------------------------------------------------------------
# Catálogos ampliables (categorías, estados y frecuencias)
# ---------------------------------------------------------------------------
def listar_opciones_catalogo(nombre):
    """Opciones que se han agregado a mano a un catálogo. Las de fábrica
    viven en utilidades.OPCIONES_BASE; estas se suman a aquellas."""
    doc = db().collection(COL_CATALOGOS).document(nombre).get()
    if not doc.exists:
        return []
    return list((doc.to_dict() or {}).get("valores") or [])


def agregar_opcion_catalogo(nombre, valor):
    """Guarda una opción nueva para que esté disponible en futuros registros.
    Quien llama ya verificó que no esté duplicada."""
    (db().collection(COL_CATALOGOS).document(nombre)
     .set({"valores": firestore.ArrayUnion([valor])}, merge=True))


# ---------------------------------------------------------------------------
# Tipos de incidencia
# ---------------------------------------------------------------------------
def listar_tipos():
    docs = db().collection(COL_TIPOS).stream()
    tipos = [_con_id(d) for d in docs]
    return sorted(tipos, key=lambda t: t.get("nombre", ""))


def crear_tipo(datos):
    ref = db().collection(COL_TIPOS).document()
    ref.set({
        "nombre": datos["nombre"],
        "descripcion": datos.get("descripcion", ""),
        "gravedad_default": datos.get("gravedad_default", "Amarillo"),
        "activo": True,
    })
    return ref.id


def existe_tipo_con_nombre(nombre):
    consulta = (db().collection(COL_TIPOS)
                .where(filter=firestore.FieldFilter("nombre", "==", nombre))
                .limit(1).stream())
    return any(True for _ in consulta)


# ---------------------------------------------------------------------------
# Servicios
# ---------------------------------------------------------------------------
def listar_servicios():
    docs = db().collection(COL_SERVICIOS).stream()
    servicios = [_con_id(d) for d in docs]
    # Orden descendente por fecha (más recientes primero)
    return sorted(servicios, key=lambda s: (s.get("fecha", ""), s.get("creado_en", "")),
                  reverse=True)


def crear_servicio(datos):
    """Crea un servicio. Se denormalizan los datos del cliente para poder
    filtrar y graficar sin hacer lecturas adicionales."""
    cliente = obtener_cliente(datos["cliente_id"])
    if cliente is None:
        raise ValueError("El cliente indicado no existe.")

    ref = db().collection(COL_SERVICIOS).document()
    ref.set({
        "fecha": datos["fecha"],                       # 'YYYY-MM-DD'
        "cliente_id": datos["cliente_id"],
        "cliente": cliente["nombre"],                  # denormalizado
        "categoria": cliente.get("categoria"),         # denormalizado
        "estado": cliente.get("estado"),               # denormalizado
        "frecuencia": cliente.get("frecuencia"),       # denormalizado
        "cobro_por_recoleccion": bool(cliente.get("cobro_por_recoleccion")),
        "tipo_servicio": datos.get("tipo_servicio", "Recolección"),
        "hora_programada": datos.get("hora_programada") or None,
        "hora_real": datos.get("hora_real") or None,
        "realizado": bool(datos.get("realizado", True)),
        "resultado": datos.get("resultado"),
        "responsable": datos.get("responsable"),
        "observaciones": datos.get("observaciones"),
        "creado_en": _ahora(),
    })
    return ref.id


def obtener_servicio(servicio_id):
    doc = db().collection(COL_SERVICIOS).document(servicio_id).get()
    return _con_id(doc) if doc.exists else None


# ---------------------------------------------------------------------------
# Incidencias
# ---------------------------------------------------------------------------
def listar_incidencias():
    docs = db().collection(COL_INCIDENCIAS).stream()
    incidencias = [_con_id(d) for d in docs]
    return sorted(incidencias, key=lambda i: (i.get("fecha", ""), i.get("creado_en", "")),
                  reverse=True)


def _entero(valor):
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return 0


def _servicio_y_tipo(datos):
    """Comprueba que el servicio y el tipo existan y los devuelve.
    Es lo que se denormaliza dentro de la incidencia."""
    servicio = obtener_servicio(datos["servicio_id"])
    if servicio is None:
        raise ValueError("El servicio indicado no existe.")

    tipo_doc = db().collection(COL_TIPOS).document(datos["tipo_incidencia_id"]).get()
    if not tipo_doc.exists:
        raise ValueError("El tipo de incidencia indicado no existe.")
    return servicio, tipo_doc.to_dict()


def _documento_incidencia(datos, servicio, tipo):
    """Campos de una incidencia a partir de lo capturado en el formulario.

    Lo usan tanto el alta como la edición, para que una incidencia corregida
    quede exactamente igual que si se hubiera capturado bien desde el inicio.
    No incluye `creado_en` ni `evidencias`: esos solo se fijan al crearla.
    """
    resuelta = bool(datos.get("resuelta", False))
    return {
        "servicio_id": datos["servicio_id"],
        "tipo_incidencia_id": datos["tipo_incidencia_id"],
        "tipo_incidencia": tipo.get("nombre"),          # denormalizado
        "gravedad": datos.get("gravedad", tipo.get("gravedad_default", "Amarillo")),
        "descripcion": datos.get("descripcion"),        # descripción detallada
        "reporto_cliente": bool(datos.get("reporto_cliente", False)),
        "resuelta": resuelta,
        "resuelta_a_tiempo": bool(datos["resuelta_a_tiempo"])
                             if resuelta and datos.get("resuelta_a_tiempo") is not None
                             else None,
        "fecha_resolucion": datos.get("fecha_resolucion") if resuelta else None,
        "accion_correctiva": datos.get("accion_correctiva"),
        "comentarios": datos.get("comentarios"),
        # Cantidades para los indicadores obligatorios
        "vueltas_adicionales": _entero(datos.get("vueltas_adicionales")),
        "minutos_retraso": _entero(datos.get("minutos_retraso")),
        # Detalle de clientes prioritarios (Walmart / Bodega / Sam's)
        "segunda_vuelta_no_cobrable": bool(datos.get("segunda_vuelta_no_cobrable", False)),
        "material_pendiente": datos.get("material_pendiente"),
        # Datos del servicio (denormalizados para filtros y gráficas)
        "fecha": servicio["fecha"],
        "cliente_id": servicio["cliente_id"],
        "cliente": servicio["cliente"],
        "categoria": servicio.get("categoria"),
        "estado": servicio.get("estado"),
        "frecuencia": servicio.get("frecuencia"),
        "cobro_por_recoleccion": bool(servicio.get("cobro_por_recoleccion")),
        "es_prioritario": bool(servicio.get("cobro_por_recoleccion")),
        "tipo_servicio": servicio.get("tipo_servicio"),
        "responsable": servicio.get("responsable"),
    }


def crear_incidencia(datos):
    """Crea una incidencia asociada a un servicio, denormalizando los datos
    del servicio y del tipo para que el dashboard lea una sola colección."""
    servicio, tipo = _servicio_y_tipo(datos)

    ref = db().collection(COL_INCIDENCIAS).document()
    ref.set({
        **_documento_incidencia(datos, servicio, tipo),
        "evidencias": [],                                # se llenan al subir
        "creado_en": _ahora(),
    })
    return ref.id


def obtener_incidencia(incidencia_id):
    doc = db().collection(COL_INCIDENCIAS).document(incidencia_id).get()
    return _con_id(doc) if doc.exists else None


def actualizar_incidencia(incidencia_id, datos):
    """Corrige una incidencia ya registrada, sin crear un registro nuevo.

    Se vuelven a copiar los datos del servicio y del tipo, por si se cambió
    alguno de los dos. Las evidencias ya subidas y la fecha de alta no se
    tocan: se conservan tal cual.
    """
    ref = db().collection(COL_INCIDENCIAS).document(incidencia_id)
    if not ref.get().exists:
        raise ValueError("La incidencia indicada no existe.")

    servicio, tipo = _servicio_y_tipo(datos)
    ref.update({
        **_documento_incidencia(datos, servicio, tipo),
        "actualizado_en": _ahora(),
    })


def resolver_incidencia(incidencia_id, fecha_resolucion, a_tiempo, comentario=None):
    ref = db().collection(COL_INCIDENCIAS).document(incidencia_id)
    if not ref.get().exists:
        raise ValueError("La incidencia no existe.")
    cambios = {
        "resuelta": True,
        "fecha_resolucion": fecha_resolucion,
        "resuelta_a_tiempo": bool(a_tiempo),
    }
    if comentario:
        cambios["comentarios"] = comentario
    ref.update(cambios)

def eliminar_incidencia(incidencia_id):
    """
    Borra físicamente el documento de la incidencia en Firestore.
    """
    # Intentamos usar una constante si existe, si no, usamos el string 'incidencias'
    coleccion = globals().get('COL_INCIDENCIAS', 'incidencias')
    
    # Referencia al documento
    doc_ref = db().collection(coleccion).document(incidencia_id)
    
    if not doc_ref.get().exists:
        raise ValueError("La incidencia no existe.")

    doc_ref.delete()


# ---------------------------------------------------------------------------
# Evidencias (Firebase Storage)
# ---------------------------------------------------------------------------
def subir_evidencia(incidencia_id, archivo, nombre_archivo, tipo_contenido):
    """Sube un archivo a Firebase Storage y registra su URL en la incidencia.

    IMPORTANTE: el archivo NO se guarda en el disco de Render (que es
    efímero), sino en Storage, que es permanente.
    """
    almacen = bucket()
    if almacen is None:
        raise RuntimeError("FIREBASE_STORAGE_BUCKET no está configurado.")

    # Ruta única dentro del bucket
    extension = os.path.splitext(nombre_archivo)[1].lower()
    ruta = f"evidencias/{incidencia_id}/{uuid.uuid4().hex}{extension}"

    # Se usa un "download token" de Firebase en lugar de make_public().
    # Motivo: los buckets nuevos traen activado el "acceso uniforme a nivel de
    # bucket", y con esa configuración make_public() falla (no se permiten
    # permisos por archivo). El token, en cambio, funciona siempre y genera
    # una URL de descarga que no caduca (idéntica a la del SDK de Firebase).
    token = uuid.uuid4().hex
    blob = almacen.blob(ruta)
    blob.metadata = {"firebaseStorageDownloadTokens": token}
    blob.upload_from_file(archivo, content_type=tipo_contenido)

    ruta_codificada = quote(ruta, safe="")
    url = (f"https://firebasestorage.googleapis.com/v0/b/{almacen.name}"
           f"/o/{ruta_codificada}?alt=media&token={token}")

    evidencia = {
        "url": url,
        "ruta": ruta,
        "nombre": nombre_archivo,
        "tipo": "pdf" if extension == ".pdf" else "imagen",
        "fecha_carga": _ahora(),
    }

    # Agregar la evidencia al arreglo de la incidencia
    ref = db().collection(COL_INCIDENCIAS).document(incidencia_id)
    ref.update({"evidencias": firestore.ArrayUnion([evidencia])})
    return evidencia
