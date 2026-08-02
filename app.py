"""
app.py
------
API REST del Sistema de Incidencias Logísticas.

Arquitectura:
    GitHub Pages (frontend HTML/JS)  ->  Render (esta API Flask)  ->  Firebase
                                                                     (Firestore
                                                                      + Storage)

Este backend NO guarda nada en disco (el de Render es efímero): todos los
datos van a Firestore y todos los archivos de evidencia a Firebase Storage.

Variables de entorno que debes configurar en Render:

    FIREBASE_CREDENTIALS     JSON completo de la cuenta de servicio (texto)
    FIREBASE_STORAGE_BUCKET  p.ej. mi-proyecto.appspot.com  (o .firebasestorage.app)
    ORIGENES_PERMITIDOS      URL del frontend en GitHub Pages, separadas por
                             comas. Ej: https://usuario.github.io
    API_TOKEN                (opcional pero MUY recomendado) contraseña que el
                             frontend debe enviar para poder escribir datos.

Ejecución local:
    python app.py            -> http://localhost:5000
Ejecución en Render:
    gunicorn app:app
"""

import os
from datetime import datetime

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from modulos import firebase_db as fdb
from modulos import indicadores as ind
from modulos import reportes as rep
from modulos import utilidades as ut

app = Flask(__name__)

# --- CORS: solo el frontend de GitHub Pages puede llamar a esta API ---------
origenes = os.environ.get("ORIGENES_PERMITIDOS", "*")
lista_origenes = [o.strip() for o in origenes.split(",")] if origenes != "*" else "*"
CORS(app, resources={r"/api/*": {"origins": lista_origenes}})

app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # Adjuntos hasta 32 MB

API_TOKEN = os.environ.get("API_TOKEN")  # Si está vacío, la API queda abierta


# ---------------------------------------------------------------------------
# Autenticación sencilla por token
# ---------------------------------------------------------------------------
@app.before_request
def verificar_token():
    """Exige el token en las operaciones de escritura (POST).
    Las lecturas (GET) quedan libres para simplificar; si prefieres proteger
    también las lecturas, quita la condición del método."""
    if not API_TOKEN:
        return None                       # Sin token configurado: API abierta
    if request.method in ("OPTIONS", "GET"):
        return None                       # Preflight de CORS y lecturas
    if not request.path.startswith("/api/"):
        return None

    enviado = request.headers.get("X-API-Token")
    if enviado != API_TOKEN:
        return jsonify({"error": "Token inválido o ausente."}), 401


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------
def _cargar_todo():
    """Servicios e incidencias enriquecidos con columnas de periodo."""
    servicios = ind.enriquecer(fdb.listar_servicios())
    incidencias = ind.enriquecer(fdb.listar_incidencias())
    return servicios, incidencias


# ---------------------------------------------------------------------------
# Salud (útil para comprobar que Render está despierto)
# ---------------------------------------------------------------------------
@app.get("/api/salud")
def salud():
    return jsonify({"estado": "ok", "hora": datetime.now().isoformat()})


# ---------------------------------------------------------------------------
# Catálogos fijos (gravedades, tipos de servicio, etc.)
# ---------------------------------------------------------------------------
def _opciones_catalogo(nombre):
    """Opciones de fábrica del catálogo más las que se hayan agregado desde
    el formulario de clientes, ya sin duplicados."""
    return ut.combinar_opciones(ut.OPCIONES_BASE[nombre],
                                fdb.listar_opciones_catalogo(nombre))


@app.get("/api/catalogos")
def catalogos():
    return jsonify({
        "gravedades": ut.GRAVEDADES,
        "colores_gravedad": ut.COLORES_GRAVEDAD,
        "descripcion_gravedad": ut.DESCRIPCION_GRAVEDAD,
        "tipos_servicio": ut.TIPOS_SERVICIO,
        "resultados": ut.RESULTADOS_SERVICIO,
        "categorias": _opciones_catalogo("categorias"),
        "estados": _opciones_catalogo("estados"),
        "frecuencias": _opciones_catalogo("frecuencias"),
        "tipos_reporte": rep.TIPOS_REPORTE,
    })


@app.post("/api/catalogos/<nombre>/opciones")
def post_opcion_catalogo(nombre):
    """Agrega una opción a Categoría, Estado o Frecuencia.

    Queda guardada y disponible para todos los registros siguientes. Si la
    opción ya existía —aunque se haya escrito con otras mayúsculas, acentos o
    espacios— no se duplica: se devuelve la que ya estaba.
    """
    if nombre not in ut.OPCIONES_BASE:
        return jsonify({"error": f"El catálogo '{nombre}' no admite opciones nuevas."}), 404

    valor = ut.limpiar_texto((request.get_json(force=True) or {}).get("valor"))
    if not valor:
        return jsonify({"error": "Escribe el nombre de la nueva opción."}), 400

    actuales = _opciones_catalogo(nombre)
    clave = ut.clave_opcion(valor)
    for existente in actuales:
        if ut.clave_opcion(existente) == clave:
            return jsonify({
                "valor": existente, "creada": False, "valores": actuales,
                "mensaje": f"«{existente}» ya estaba en la lista; se usará esa.",
            })

    fdb.agregar_opcion_catalogo(nombre, valor)
    return jsonify({
        "valor": valor, "creada": True, "valores": _opciones_catalogo(nombre),
        "mensaje": f"«{valor}» quedó guardada para futuros registros.",
    }), 201


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
@app.get("/api/clientes")
def get_clientes():
    return jsonify(fdb.listar_clientes())


@app.post("/api/clientes")
def post_cliente():
    datos = request.get_json(force=True)
    nombre = ut.limpiar_texto(datos.get("nombre"))
    if not nombre:
        return jsonify({"error": "El nombre del cliente es obligatorio."}), 400
    if fdb.existe_cliente_con_nombre(nombre):
        return jsonify({"error": "Ya existe un cliente con ese nombre."}), 409

    datos["nombre"] = nombre
    cliente_id = fdb.crear_cliente(datos)
    return jsonify({"id": cliente_id, "mensaje": f"Cliente '{nombre}' dado de alta."}), 201


@app.put("/api/clientes/<cliente_id>")
def put_cliente(cliente_id):
    """Corrige los datos de un cliente ya registrado.

    Los datos del cliente están copiados dentro de cada servicio y de cada
    incidencia (así el dashboard lee una sola colección), de modo que al
    corregirlos aquí también se refrescan allá.
    """
    datos = request.get_json(force=True)
    nombre = ut.limpiar_texto(datos.get("nombre"))
    if not nombre:
        return jsonify({"error": "El nombre del cliente es obligatorio."}), 400
    if fdb.existe_cliente_con_nombre(nombre, excluir_id=cliente_id):
        return jsonify({"error": "Ya existe otro cliente con ese nombre."}), 409

    datos["nombre"] = nombre
    try:
        actualizados = fdb.actualizar_cliente(cliente_id, datos)
    except ValueError as error:
        return jsonify({"error": str(error)}), 404

    return jsonify({
        "id": cliente_id,
        "registros_actualizados": actualizados,
        "mensaje": f"Cliente '{nombre}' actualizado.",
    })


# ---------------------------------------------------------------------------
# Tipos de incidencia
# ---------------------------------------------------------------------------
@app.get("/api/tipos")
def get_tipos():
    return jsonify(fdb.listar_tipos())


@app.post("/api/tipos")
def post_tipo():
    datos = request.get_json(force=True)
    nombre = ut.limpiar_texto(datos.get("nombre"))
    if not nombre:
        return jsonify({"error": "El nombre del tipo es obligatorio."}), 400
    if fdb.existe_tipo_con_nombre(nombre):
        return jsonify({"error": "Ya existe un tipo con ese nombre."}), 409

    datos["nombre"] = nombre
    datos["descripcion"] = ut.limpiar_texto(datos.get("descripcion")) or ""
    tipo_id = fdb.crear_tipo(datos)
    return jsonify({"id": tipo_id, "mensaje": f"Tipo '{nombre}' agregado."}), 201


# ---------------------------------------------------------------------------
# Servicios
# ---------------------------------------------------------------------------
@app.get("/api/servicios")
def get_servicios():
    servicios = fdb.listar_servicios()
    limite = request.args.get("limite", type=int)
    return jsonify(servicios[:limite] if limite else servicios)


@app.post("/api/servicios")
def post_servicio():
    datos = request.get_json(force=True)
    if not datos.get("fecha") or not datos.get("cliente_id"):
        return jsonify({"error": "La fecha y el cliente son obligatorios."}), 400

    datos["responsable"] = ut.limpiar_texto(datos.get("responsable"))
    datos["observaciones"] = ut.limpiar_texto(datos.get("observaciones"))
    try:
        servicio_id = fdb.crear_servicio(datos)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"id": servicio_id, "mensaje": "Servicio guardado."}), 201


# ---------------------------------------------------------------------------
# Incidencias
# ---------------------------------------------------------------------------
@app.get("/api/incidencias")
def get_incidencias():
    incidencias = fdb.listar_incidencias()
    if request.args.get("abiertas") == "1":
        incidencias = [i for i in incidencias if not i.get("resuelta")]
    return jsonify(incidencias)


def _validar_incidencia(datos):
    """Comprueba lo obligatorio y limpia los textos. Devuelve el mensaje de
    error, o None si todo está bien."""
    if not datos.get("servicio_id") or not datos.get("tipo_incidencia_id"):
        return "El servicio y el tipo son obligatorios."

    for campo in ("comentarios", "descripcion", "accion_correctiva",
                  "material_pendiente"):
        datos[campo] = ut.limpiar_texto(datos.get(campo))
    return None


@app.post("/api/incidencias")
def post_incidencia():
    datos = request.get_json(force=True)
    error = _validar_incidencia(datos)
    if error:
        return jsonify({"error": error}), 400

    try:
        incidencia_id = fdb.crear_incidencia(datos)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"id": incidencia_id, "mensaje": "Incidencia guardada."}), 201


@app.put("/api/incidencias/<incidencia_id>")
def put_incidencia(incidencia_id):
    """Corrige una incidencia ya registrada, sin crear un registro nuevo.
    Las evidencias que ya se subieron se conservan."""
    datos = request.get_json(force=True)
    error = _validar_incidencia(datos)
    if error:
        return jsonify({"error": error}), 400

    try:
        fdb.actualizar_incidencia(incidencia_id, datos)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"id": incidencia_id, "mensaje": "Incidencia actualizada."})


@app.post("/api/incidencias/<incidencia_id>/resolver")
def post_resolver(incidencia_id):
    datos = request.get_json(force=True)
    fecha = datos.get("fecha_resolucion")
    if not fecha:
        return jsonify({"error": "La fecha de resolución es obligatoria."}), 400
    try:
        fdb.resolver_incidencia(
            incidencia_id, fecha, datos.get("resuelta_a_tiempo", True),
            ut.limpiar_texto(datos.get("comentario")),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 404
    return jsonify({"mensaje": "Incidencia marcada como resuelta."})


# ---------------------------------------------------------------------------
# Evidencias (van a Firebase Storage, NO al disco de Render)
# ---------------------------------------------------------------------------
@app.post("/api/incidencias/<incidencia_id>/evidencias")
def post_evidencias(incidencia_id):
    archivos = request.files.getlist("evidencias")
    if not archivos:
        return jsonify({"error": "No se recibió ningún archivo."}), 400

    subidas, rechazadas, errores = [], [], []
    for archivo in archivos:
        if not archivo or not archivo.filename:
            continue
        try:
            # Se comprimen las imágenes para no agotar la cuota de Storage
            buffer, nombre, tipo_contenido = ut.preparar_evidencia(
                archivo.stream, archivo.filename)
            evidencia = fdb.subir_evidencia(incidencia_id, buffer, nombre, tipo_contenido)
            subidas.append(evidencia)
        except ValueError:
            rechazadas.append(archivo.filename)          # extensión no permitida
        except Exception as error:                        # fallo al subir a Storage
            app.logger.exception("Error al subir evidencia")
            errores.append(f"{archivo.filename}: {error}")

    respuesta = {"subidas": subidas, "rechazadas": rechazadas,
                 "mensaje": f"{len(subidas)} evidencia(s) subida(s)."}
    if errores:
        # La incidencia ya quedó guardada; solo fallaron los archivos.
        respuesta["errores"] = errores
        return jsonify(respuesta), 207        # Multi-Status: éxito parcial
    return jsonify(respuesta), 201


# ---------------------------------------------------------------------------
# Dashboard: KPIs, gráficas, filtros y detalle en una sola llamada
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
def get_dashboard():
    servicios, incidencias = _cargar_todo()

    claves = ["desde", "hasta", "anio", "trimestre", "mes", "semana",
              "estado", "categoria", "cliente", "frecuencia", "responsable",
              "tipo", "gravedad", "reporto_cliente", "resuelta_a_tiempo",
              "prioritario"]
    filtros = {c: request.args.get(c, "") for c in claves}

    servicios_f, incidencias_f = ind.aplicar_filtros(servicios, incidencias, filtros)

    return jsonify({
        "kpis": ind.calcular_kpis(servicios_f, incidencias_f),
        "graficas": ind.graficas(servicios_f, incidencias_f),
        "opciones": ind.opciones_filtros(servicios, incidencias),
        "detalle": incidencias_f,
        "sin_datos": len(servicios) == 0,
    })


# ---------------------------------------------------------------------------
# Reportes en Excel (generados en memoria y descargados)
# ---------------------------------------------------------------------------
@app.get("/api/reportes/opciones")
def get_opciones_reporte():
    servicios, _ = _cargar_todo()
    return jsonify({
        "tipos_reporte": rep.TIPOS_REPORTE,
        "semanas": sorted({s["semana"] for s in servicios if s.get("semana")}, reverse=True),
        "meses": sorted({s["mes"] for s in servicios if s.get("mes")}, reverse=True),
        "trimestres": sorted({s["trimestre"] for s in servicios if s.get("trimestre")}, reverse=True),
        "anios": sorted({s["anio"] for s in servicios if s.get("anio")}, reverse=True),
        "clientes": sorted({s["cliente"] for s in servicios if s.get("cliente")}),
        "hay_datos": len(servicios) > 0,
    })


@app.get("/api/reportes/generar")
def generar_reporte():
    tipo = request.args.get("tipo", "Mensual")
    valor = request.args.get("valor", "")
    incluir_ev = request.args.get("evidencias", "1") == "1"

    servicios, incidencias = _cargar_todo()
    if not servicios:
        return jsonify({"error": "Aún no hay servicios registrados."}), 400

    servicios_f, incidencias_f, sufijo = rep.filtrar_por_reporte(
        servicios, incidencias, tipo, valor)

    buffer = rep.generar_excel(
        f"Reporte {tipo} {sufijo}".strip(), servicios_f, incidencias_f, incluir_ev)

    nombre = (f"reporte_{ut.sin_acentos_minusculas(tipo).replace(' ', '_')}"
              f"_{sufijo}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
    return send_file(
        buffer, as_attachment=True, download_name=nombre,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=puerto, debug=False)
