"""
indicadores.py
--------------
Cálculo de KPIs, filtros y datos de gráficas a partir de los documentos de
Firestore. Recibe listas de diccionarios (no DataFrames de SQL) y devuelve
estructuras JSON listas para que el frontend las dibuje con Plotly.js.

Incluye los indicadores obligatorios de la hoja "Indicadores" del Excel:
retrasos, vueltas extra, % por tipo de incidencia, % de quejas del cliente
y % de recolecciones sin incidencias.
"""

from collections import Counter

from modulos import utilidades as ut


# ---------------------------------------------------------------------------
# Enriquecimiento y filtros
# ---------------------------------------------------------------------------
def enriquecer(registros):
    """Agrega columnas de periodo (semana, mes, trimestre, año) a cada
    documento, y marca retrasos de horario en los servicios."""
    for r in registros:
        fecha = r.get("fecha")
        if not fecha:
            continue
        r["semana"] = ut.semana_iso(fecha)
        r["mes"] = ut.mes_etiqueta(fecha)
        r["trimestre"] = ut.trimestre_etiqueta(fecha)
        r["anio"] = ut.anio_etiqueta(fecha)
        # Retraso automático: hora real posterior a la programada
        if "hora_programada" in r:
            hp, hr = r.get("hora_programada"), r.get("hora_real")
            r["retraso_horario"] = bool(hp and hr and hr > hp)
    return registros


def opciones_filtros(servicios, incidencias):
    """Valores disponibles para poblar los selectores del dashboard."""
    def unicos(lista, campo):
        return sorted({r[campo] for r in lista if r.get(campo)})

    return {
        "anios": unicos(servicios, "anio"),
        "trimestres": unicos(servicios, "trimestre"),
        "meses": unicos(servicios, "mes"),
        "semanas": unicos(servicios, "semana"),
        "estados": unicos(servicios, "estado"),
        "categorias": unicos(servicios, "categoria"),
        "clientes": unicos(servicios, "cliente"),
        "frecuencias": unicos(servicios, "frecuencia"),
        "responsables": unicos(servicios, "responsable"),
        "tipos": unicos(incidencias, "tipo_incidencia"),
        "gravedades": ut.GRAVEDADES,
    }


def aplicar_filtros(servicios, incidencias, filtros):
    """Filtra servicios e incidencias. Un filtro vacío no restringe nada.

    `filtros` acepta: desde, hasta, anio, trimestre, mes, semana, estado,
    categoria, cliente, responsable, tipo, gravedad.
    """
    def activo(clave):
        return bool(filtros.get(clave))

    def es_si(clave):
        """Interpreta un filtro 'si'/'no' (para reporte del cliente, etc.)."""
        return str(filtros.get(clave, "")).lower() in ("si", "sí", "1", "true")

    servicios_f = []
    for s in servicios:
        fecha = ut.a_fecha(s.get("fecha"))
        if activo("desde") and fecha < ut.a_fecha(filtros["desde"]):
            continue
        if activo("hasta") and fecha > ut.a_fecha(filtros["hasta"]):
            continue
        descartar = False
        for clave in ("anio", "trimestre", "mes", "semana", "estado",
                      "categoria", "cliente", "frecuencia", "responsable"):
            if activo(clave) and s.get(clave) != filtros[clave]:
                descartar = True
                break
        # Filtro de clientes prioritarios (Walmart / Bodega / Sam's)
        if not descartar and filtros.get("prioritario") and not s.get("cobro_por_recoleccion"):
            descartar = True
        if not descartar:
            servicios_f.append(s)

    ids_servicios = {s["id"] for s in servicios_f}
    incidencias_f = []
    for i in incidencias:
        if i.get("servicio_id") not in ids_servicios:
            continue
        if activo("tipo") and i.get("tipo_incidencia") != filtros["tipo"]:
            continue
        if activo("gravedad") and i.get("gravedad") != filtros["gravedad"]:
            continue
        if activo("reporto_cliente") and bool(i.get("reporto_cliente")) != es_si("reporto_cliente"):
            continue
        if activo("resuelta_a_tiempo"):
            # Solo aplica a incidencias ya resueltas
            if i.get("resuelta_a_tiempo") is None:
                continue
            if bool(i.get("resuelta_a_tiempo")) != es_si("resuelta_a_tiempo"):
                continue
        incidencias_f.append(i)

    return servicios_f, incidencias_f


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
def calcular_kpis(servicios, incidencias):
    """Tarjetas del dashboard, incluidos los indicadores obligatorios."""
    total_serv = len(servicios)
    total_inci = len(incidencias)
    serv_con_inci = len({i["servicio_id"] for i in incidencias})
    pct_con = 100 * serv_con_inci / total_serv if total_serv else 0

    retrasos_horario = sum(1 for s in servicios if s.get("retraso_horario"))
    retrasos_tipo = sum(1 for i in incidencias
                        if i.get("tipo_incidencia") == ut.TIPO_RETRASO)
    retrasos = max(retrasos_horario, retrasos_tipo)
    minutos_retraso = sum(i.get("minutos_retraso") or 0 for i in incidencias)

    # Vueltas extra: se suma la cantidad capturada; si nadie capturó número,
    # se cuenta cada incidencia del tipo "Desvío de ruta / Vueltas excedentes".
    vueltas_capturadas = sum(i.get("vueltas_adicionales") or 0 for i in incidencias)
    vueltas_por_tipo = sum(1 for i in incidencias
                           if i.get("tipo_incidencia") == ut.TIPO_VUELTAS)
    vueltas = vueltas_capturadas or vueltas_por_tipo

    quejas = sum(1 for i in incidencias if i.get("reporto_cliente"))
    abiertas = sum(1 for i in incidencias if not i.get("resuelta"))

    # % de incidencias resueltas a tiempo (sobre las que ya se resolvieron)
    resueltas = [i for i in incidencias if i.get("resuelta")]
    a_tiempo = sum(1 for i in resueltas if i.get("resuelta_a_tiempo"))
    pct_a_tiempo = 100 * a_tiempo / len(resueltas) if resueltas else 0

    # Clientes prioritarios (Walmart / Bodega / Sam's)
    inci_prioritarios = sum(1 for i in incidencias if i.get("es_prioritario"))
    segundas_vueltas = sum(1 for i in incidencias if i.get("segunda_vuelta_no_cobrable"))

    # Tiempo promedio de resolución (días entre servicio y cierre)
    dias = []
    for i in incidencias:
        if i.get("resuelta") and i.get("fecha_resolucion") and i.get("fecha"):
            delta = (ut.a_fecha(i["fecha_resolucion"]) - ut.a_fecha(i["fecha"])).days
            dias.append(delta)
    tiempo_promedio = f"{sum(dias)/len(dias):.1f} días" if dias else "—"

    return {
        "total_servicios": total_serv,
        "total_incidencias": total_inci,
        "pct_con_incidencia": f"{pct_con:.1f}%",
        "pct_sin_incidencia": f"{(100 - pct_con if total_serv else 0):.1f}%",
        "retrasos": retrasos,
        "pct_retrasos": f"{(100*retrasos/total_serv if total_serv else 0):.1f}%",
        "vueltas": vueltas,
        "pct_vueltas": f"{(100*vueltas/total_serv if total_serv else 0):.1f}%",
        "minutos_retraso": minutos_retraso,
        "quejas": quejas,
        "pct_quejas": f"{(100*quejas/total_inci if total_inci else 0):.1f}%",
        "pct_a_tiempo": f"{pct_a_tiempo:.1f}%",
        "abiertas": abiertas,
        "cerradas": total_inci - abiertas,
        "tiempo_promedio": tiempo_promedio,
        "inci_prioritarios": inci_prioritarios,
        "segundas_vueltas": segundas_vueltas,
    }


# ---------------------------------------------------------------------------
# Gráficas (estructuras Plotly listas para el frontend)
# ---------------------------------------------------------------------------
def graficas(servicios, incidencias):
    """Devuelve {nombre: {data, layout}} para dibujar con Plotly.js."""
    figuras = {}

    if incidencias:
        total = len(incidencias)

        # % por tipo de incidencia (indicador obligatorio)
        por_tipo = Counter(i["tipo_incidencia"] for i in incidencias).most_common()
        figuras["por_tipo"] = {
            "data": [{
                "type": "bar", "orientation": "h",
                "x": [c for _, c in por_tipo][::-1],
                "y": [t for t, _ in por_tipo][::-1],
                "text": [f"{100*c/total:.1f}%" for _, c in por_tipo][::-1],
                "textposition": "auto",
                "marker": {"color": "#1976D2"},
            }],
            "layout": {"title": "Incidencias por tipo (%)", "height": 380,
                       "margin": {"l": 230, "r": 20, "t": 45, "b": 35}},
        }

        # Gravedad, con el semáforo de colores
        por_grav = Counter(i["gravedad"] for i in incidencias).most_common()
        figuras["por_gravedad"] = {
            "data": [{
                "type": "pie",
                "labels": [g for g, _ in por_grav],
                "values": [c for _, c in por_grav],
                "marker": {"colors": [ut.COLORES_GRAVEDAD.get(g, "#999")
                                      for g, _ in por_grav]},
            }],
            "layout": {"title": "Incidencias por gravedad", "height": 380},
        }

        # Clientes con más incidencias (Top 10)
        por_cliente = Counter(i["cliente"] for i in incidencias).most_common(10)
        figuras["por_cliente"] = {
            "data": [{
                "type": "bar", "orientation": "h",
                "x": [c for _, c in por_cliente][::-1],
                "y": [n for n, _ in por_cliente][::-1],
                "marker": {"color": "#7B1FA2"},
            }],
            "layout": {"title": "Clientes con más incidencias (Top 10)",
                       "height": 380,
                       "margin": {"l": 200, "r": 20, "t": 45, "b": 35}},
        }

        # Incidencias por estado
        por_estado = Counter(i.get("estado") or "—" for i in incidencias).most_common()
        figuras["por_estado"] = {
            "data": [{
                "type": "bar",
                "x": [e for e, _ in por_estado],
                "y": [c for _, c in por_estado],
                "marker": {"color": "#00796B"},
            }],
            "layout": {"title": "Incidencias por estado", "height": 380},
        }

        # Incidencias por categoría de cliente (Empresa / Vivienda / Restaurante)
        por_categoria = Counter(i.get("categoria") or "—" for i in incidencias).most_common()
        figuras["por_categoria"] = {
            "data": [{
                "type": "bar",
                "x": [c for c, _ in por_categoria],
                "y": [n for _, n in por_categoria],
                "text": [f"{100*n/total:.1f}%" for _, n in por_categoria],
                "textposition": "auto",
                "marker": {"color": "#5D4037"},
            }],
            "layout": {"title": "Incidencias por categoría de cliente", "height": 380},
        }

        # Incidencias de clientes prioritarios (Walmart / Bodega / Sam's)
        prioritarias = [i for i in incidencias if i.get("es_prioritario")]
        if prioritarias:
            por_prio = Counter(i["cliente"] for i in prioritarias).most_common(10)
            figuras["prioritarios"] = {
                "data": [{
                    "type": "bar", "orientation": "h",
                    "x": [c for _, c in por_prio][::-1],
                    "y": [n for n, _ in por_prio][::-1],
                    "marker": {"color": "#C62828"},
                }],
                "layout": {"title": "Incidencias Walmart / Bodega / Sam's",
                           "height": 380,
                           "margin": {"l": 200, "r": 20, "t": 45, "b": 35}},
            }

    # Comparación: frecuencia programada de recolección vs. incidencias.
    # Cruza cuántos servicios y cuántas incidencias hubo en cada frecuencia,
    # para ver a qué esquema de recolección le fallamos más.
    if servicios:
        serv_frec = Counter(s.get("frecuencia") or "—" for s in servicios)
        inci_frec = Counter(i.get("frecuencia") or "—" for i in incidencias)
        frecuencias = sorted(set(serv_frec) | set(inci_frec))
        figuras["frecuencia_vs_incidencias"] = {
            "data": [
                {"type": "bar", "name": "Servicios", "x": frecuencias,
                 "y": [serv_frec.get(f, 0) for f in frecuencias],
                 "marker": {"color": "#1976D2"}},
                {"type": "bar", "name": "Incidencias", "x": frecuencias,
                 "y": [inci_frec.get(f, 0) for f in frecuencias],
                 "marker": {"color": "#D32F2F"}},
            ],
            "layout": {"title": "Frecuencia programada vs. incidencias",
                       "height": 380, "barmode": "group",
                       "legend": {"orientation": "h", "y": 1.15}},
        }

    # Tendencias: servicios vs incidencias por mes y por semana
    for campo, nombre, titulo in [("mes", "tendencia_mensual", "Tendencia mensual"),
                                  ("semana", "tendencia_semanal", "Tendencia semanal")]:
        if not servicios:
            continue
        serv = Counter(s[campo] for s in servicios if s.get(campo))
        inci = Counter(i[campo] for i in incidencias if i.get(campo))
        periodos = sorted(set(serv) | set(inci))
        figuras[nombre] = {
            "data": [
                {"type": "scatter", "mode": "lines+markers", "name": "Servicios",
                 "x": periodos, "y": [serv.get(p, 0) for p in periodos],
                 "line": {"color": "#1976D2", "width": 3}},
                {"type": "scatter", "mode": "lines+markers", "name": "Incidencias",
                 "x": periodos, "y": [inci.get(p, 0) for p in periodos],
                 "line": {"color": "#D32F2F", "width": 3}},
            ],
            "layout": {"title": titulo, "height": 350,
                       "legend": {"orientation": "h", "y": 1.15}},
        }

    return figuras
