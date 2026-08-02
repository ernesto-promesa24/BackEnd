"""
utilidades.py
-------------
Funciones auxiliares del backend, sin dependencias de Flask ni de Firebase:
- Normalización de textos.
- Cálculo de periodos (semana, mes, trimestre, año).
- Semáforo de gravedad.
- Compresión de imágenes de evidencia antes de subirlas a Storage.
"""

import io
import os
import re
import unicodedata
from datetime import date, datetime

# ---------------------------------------------------------------------------
# Catálogos fijos
# ---------------------------------------------------------------------------
GRAVEDADES = ["Rojo", "Naranja", "Amarillo", "Verde"]

COLORES_GRAVEDAD = {
    "Rojo": "#D32F2F",      # Gravedad alta
    "Naranja": "#F57C00",   # Grave, menor impacto
    "Amarillo": "#FBC02D",  # Preocupación menor
    "Verde": "#388E3C",     # Solución sencilla
}

DESCRIPCION_GRAVEDAD = {
    "Rojo": "Gravedad alta",
    "Naranja": "Grave, menor impacto",
    "Amarillo": "Preocupación menor",
    "Verde": "Solución sencilla",
}

TIPOS_SERVICIO = ["Recolección", "Entrega"]
RESULTADOS_SERVICIO = ["Exitoso", "Parcial", "Fallido", "Reprogramado"]
CATEGORIAS = ["Empresa", "Vivienda", "Restaurante"]
ESTADOS = ["Ciudad de México", "Estado de México", "Monterrey",
           "Guadalajara", "Queretaro"]

# Tipos ligados a indicadores obligatorios de las PM
TIPO_RETRASO = "Incumplimiento de horario"
TIPO_VUELTAS = "Desvío de ruta / Vueltas excedentes"

# Frecuencias normalizadas que ofrece el sistema (para altas y filtros).
FRECUENCIAS = ["Semanal", "Quincenal", "Mensual", "Bimestral", "Trimestral",
               "2 veces por semana", "3 veces por semana", "6 veces por semana",
               "Sin recolección", "Sin definir"]

# Catálogos que el usuario puede ampliar desde el formulario de clientes con
# la opción «+ Agregar nueva opción». Las listas de arriba son la base que
# siempre está disponible; lo que se agregue se guarda en Firestore y se une
# a esa base cada vez que se piden los catálogos (ver combinar_opciones).
OPCIONES_BASE = {
    "categorias": CATEGORIAS,
    "estados": ESTADOS,
    "frecuencias": FRECUENCIAS,
}

# Clientes prioritarios: se les cobra por recolección, así que una segunda
# vuelta por material olvidado NO se les puede volver a cobrar (regla de las PM).
PREFIJOS_PRIORITARIOS = ("walmart", "bodega", "sam")


def es_prioritario(nombre):
    """True si el cliente es Walmart, Bodega Aurrera o Sam's (por su nombre)."""
    return sin_acentos_minusculas(nombre).startswith(PREFIJOS_PRIORITARIOS)

EXTENSIONES_PERMITIDAS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf"}
EXTENSIONES_IMAGEN = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


# ---------------------------------------------------------------------------
# Textos
# ---------------------------------------------------------------------------
def limpiar_texto(texto):
    """Quita espacios sobrantes; devuelve None si queda vacío."""
    if texto is None:
        return None
    texto = re.sub(r"\s+", " ", str(texto)).strip()
    return texto or None


def sin_acentos_minusculas(texto):
    """Sin acentos y en minúsculas, para comparar textos."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def clave_opcion(texto):
    """Clave para comparar dos opciones y detectar duplicados.

    Ignora mayúsculas/minúsculas, acentos y los espacios sobrantes (al
    principio, al final y los repetidos en medio). Así « ciudad  de MEXICO »
    y "Ciudad de México" se reconocen como la misma opción.
    """
    return sin_acentos_minusculas(limpiar_texto(texto) or "")


def combinar_opciones(*listas):
    """Une varias listas de opciones sin duplicados.

    Conserva el orden de aparición y la primera forma escrita de cada opción
    (la de la lista base, cuando existe ahí). La comparación usa
    `clave_opcion`, así que no se cuelan variantes que solo cambian en
    mayúsculas, acentos o espacios.
    """
    vistas, resultado = set(), []
    for lista in listas:
        for valor in lista or []:
            limpio = limpiar_texto(valor)
            if not limpio:
                continue
            clave = clave_opcion(limpio)
            if clave in vistas:
                continue
            vistas.add(clave)
            resultado.append(limpio)
    return resultado


def normalizar_frecuencia(texto_original):
    """Convierte la frecuencia libre del Excel en (frecuencia, activo)."""
    limpio = limpiar_texto(texto_original)
    if limpio is None:
        return ("Sin definir", False)

    base = sin_acentos_minusculas(limpio)
    if "pausa" in base or "sin recolec" in base:
        return ("Sin recolección", False)

    mapa = {"semanal": "Semanal", "quincenal": "Quincenal", "mensual": "Mensual",
            "bimestral": "Bimestral", "trimestral": "Trimestral"}
    if base in mapa:
        return (mapa[base], True)

    m = re.search(r"(\d+|dos|tres|seis)\s*veces", base)
    if m:
        numeros = {"dos": "2", "tres": "3", "seis": "6"}
        n = numeros.get(m.group(1), m.group(1))
        return (f"{n} veces por semana", True)

    return (limpio, True)


# ---------------------------------------------------------------------------
# Periodos
# ---------------------------------------------------------------------------
def a_fecha(valor):
    """'YYYY-MM-DD' o date/datetime -> date."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()


def semana_iso(fecha):
    iso = a_fecha(fecha).isocalendar()
    return f"{iso[0]}-S{iso[1]:02d}"


def mes_etiqueta(fecha):
    f = a_fecha(fecha)
    return f"{f.year}-{f.month:02d}"


def trimestre_etiqueta(fecha):
    f = a_fecha(fecha)
    return f"{f.year}-T{(f.month - 1) // 3 + 1}"


def anio_etiqueta(fecha):
    return str(a_fecha(fecha).year)


# ---------------------------------------------------------------------------
# Evidencias: compresión antes de subir
# ---------------------------------------------------------------------------
def preparar_evidencia(archivo, nombre, ancho_max=1600, calidad=80):
    """Devuelve (buffer, nombre_final, content_type) listo para Storage.

    Las imágenes se redimensionan y comprimen a JPEG para no desperdiciar
    cuota de Firebase Storage (una foto de teléfono de 4 MB baja a ~250 KB
    sin perder legibilidad). Los PDF se suben tal cual.
    """
    extension = os.path.splitext(nombre)[1].lower()
    if extension not in EXTENSIONES_PERMITIDAS:
        raise ValueError(f"Extensión no permitida: {extension}")

    if extension == ".pdf":
        return archivo, nombre, "application/pdf"

    from PIL import Image  # Import local: solo se necesita para imágenes

    imagen = Image.open(archivo)
    if imagen.mode in ("RGBA", "P", "LA"):
        imagen = imagen.convert("RGB")

    if imagen.width > ancho_max:
        alto = int(imagen.height * ancho_max / imagen.width)
        imagen = imagen.resize((ancho_max, alto), Image.LANCZOS)

    buffer = io.BytesIO()
    imagen.save(buffer, format="JPEG", quality=calidad, optimize=True)
    buffer.seek(0)

    nombre_final = os.path.splitext(nombre)[0] + ".jpg"
    return buffer, nombre_final, "image/jpeg"
