# Guia del backend del sistema de incidencias logisticas

## 1. Objetivo general

Este proyecto es una API REST construida con Flask para registrar y consultar:

- Clientes.
- Tipos de incidencia.
- Servicios de recoleccion o entrega.
- Incidencias relacionadas con un servicio.
- Evidencias adjuntas, como imagenes y PDF.
- Indicadores, filtros y graficas para un dashboard.
- Reportes descargables en Excel.

El backend funciona como intermediario entre el frontend y Firebase:

```text
Frontend web
    |
    | HTTP / JSON / archivos
    v
Flask en Render
    |
    +--> Firestore: datos de clientes, servicios e incidencias
    |
    +--> Firebase Storage: evidencias adjuntas
```

El servidor no depende de archivos locales para conservar informacion. Esto es
importante en Render porque su disco puede ser efimero. Los Excel se construyen
en memoria y se descargan directamente; las evidencias se guardan en Firebase
Storage.

## 2. Estructura del proyecto

```text
BackEnd/
|-- app.py
|-- requirements.txt
|-- render.yaml
|-- README.md
|-- CONFIGURACION_FIREBASE.md
|-- GUIA_BACKEND.md
|-- .gitignore
|-- catalogos/
|   `-- Datos_para_doc_de_incidencias.xlsx
|-- modulos/
|   |-- __init__.py
|   |-- firebase_db.py
|   |-- indicadores.py
|   |-- reportes.py
|   `-- utilidades.py
|-- scripts/
|   `-- cargar_catalogos.py
`-- venv/
```

### Archivos de la raiz

#### `app.py`

Es el punto de entrada y la capa HTTP de la aplicacion. Crea la instancia de
Flask, configura CORS, limita el tamano de las peticiones, valida el token de
escritura y define todas las rutas `/api/...`.

Tambien coordina los modulos especializados:

- `firebase_db` para leer y guardar datos.
- `indicadores` para enriquecer, filtrar y calcular resultados del dashboard.
- `reportes` para crear archivos Excel.
- `utilidades` para limpieza, catalogos, fechas y evidencias.

Cuando se ejecuta directamente, escucha en `0.0.0.0` y usa el puerto de la
variable `PORT`; si no existe, usa el puerto `5000`.

#### `requirements.txt`

Declara las dependencias de Python:

| Paquete | Uso |
|---|---|
| `flask` | Servidor web y rutas HTTP. |
| `flask-cors` | Permite llamadas desde el frontend. |
| `firebase-admin` | Conexion administrativa con Firestore y Storage. |
| `openpyxl` | Construccion de reportes `.xlsx`. |
| `Pillow` | Redimension y compresion de imagenes. |
| `requests` | Descarga de imagenes para incrustarlas en Excel. |
| `gunicorn` | Servidor de produccion usado por Render. |

#### `render.yaml`

Es la configuracion opcional de infraestructura para Render. Define un servicio
web Python, el comando de instalacion, el comando de arranque y las variables
secretas.

**Advertencia actual:** contiene `rootDir: backend`, pero en este workspace
`app.py` y `requirements.txt` estan en la raiz. Si este es el repositorio que se
sube a Render, hay que quitar `rootDir` o cambiarlo por la carpeta real.

#### `README.md`

Actualmente solo identifica el proyecto. La documentacion tecnica detallada se
encuentra en este archivo y la configuracion especifica de Firebase esta en
`CONFIGURACION_FIREBASE.md`.

#### `CONFIGURACION_FIREBASE.md`

Explica como obtener credenciales, configurar variables en Windows PowerShell y
Render, comprobar la conexion y evitar publicar secretos.

#### `.gitignore`

Evita subir caches, entornos virtuales, archivos `.env` y credenciales como
`serviceAccount.json`. Las credenciales nunca deben guardarse en el repositorio.

### Carpeta `modulos/`

#### `modulos/__init__.py`

Esta vacio. Su funcion es marcar `modulos` como paquete importable de Python.

#### `modulos/firebase_db.py`

Es la capa de persistencia. Encapsula todo el acceso a Firebase y evita que
`app.py` tenga que conocer los detalles de Firestore o Storage.

Responsabilidades principales:

1. Inicializar Firebase una sola vez.
2. Crear el cliente de Firestore y el bucket de Storage.
3. Leer y escribir las colecciones.
4. Generar IDs y marcas de tiempo UTC.
5. Validar relaciones entre clientes, servicios y tipos.
6. Denormalizar datos para facilitar filtros y graficas.
7. Subir evidencias y guardar sus URLs en la incidencia.

La inicializacion es perezosa: Firebase no se conecta al importar el modulo,
sino cuando alguna operacion necesita `db()` o `bucket()`.

#### `modulos/indicadores.py`

Trabaja con listas de diccionarios obtenidas de Firestore, sin usar SQL ni
DataFrames. Sus funciones:

- Agregan semana ISO, mes, trimestre y anio a cada registro.
- Detectan retrasos comparando hora programada y hora real.
- Aplican filtros de fechas, periodo, cliente, estado, categoria, frecuencia,
  responsable, tipo, gravedad y estado de resolucion.
- Calculan KPIs.
- Preparan estructuras compatibles con Plotly para las graficas.

#### `modulos/reportes.py`

Genera archivos Excel con `openpyxl` en memoria. Un reporte puede incluir:

1. `Resumen`: KPIs y desglose por tipo, mes y trimestre.
2. `Servicios`: detalle del periodo.
3. `Incidencias`: detalle con gravedad coloreada.
4. `Evidencias`: imagenes incrustadas y enlaces a otros adjuntos.

Los tipos de reporte son semanal, mensual, trimestral, anual, por cliente e
incidencias pendientes.

#### `modulos/utilidades.py`

Contiene logica reutilizable que no depende de Flask ni Firebase:

- Limpieza y normalizacion de texto.
- Comparacion de opciones ignorando mayusculas, acentos y espacios repetidos.
- Normalizacion de frecuencias provenientes del Excel.
- Calculo de semana, mes, trimestre y anio.
- Catalogos fijos y colores de gravedad.
- Identificacion de clientes prioritarios.
- Validacion, compresion y redimension de evidencias.

Las extensiones permitidas son `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif` y
`.pdf`. Las imagenes se convierten a JPEG, con ancho maximo de 1600 pixeles y
calidad 80. Los PDF se conservan sin conversion.

### Carpeta `catalogos/`

#### `Datos_para_doc_de_incidencias.xlsx`

Es el Excel de origen utilizado por `scripts/cargar_catalogos.py` para cargar
clientes. El script busca una hoja cuyo nombre contenga "generales" y una fila
con el encabezado "Nombre del Cliente".

### Carpeta `scripts/`

#### `scripts/cargar_catalogos.py`

Es un proceso de carga inicial, independiente del servidor web. Lee el Excel,
normaliza clientes y crea los tipos de incidencia iniciales en Firestore.

Caracteristicas:

- Carga los clientes del Excel.
- Normaliza frecuencias como semanal, mensual o varias veces por semana.
- Marca como prioritarios los nombres que empiezan por `walmart`, `bodega` o
  `sam` sin importar mayusculas o acentos.
- Crea ocho tipos de incidencia con su gravedad predeterminada.
- Usa lotes de Firestore de hasta 400 documentos.
- Puede ejecutarse de nuevo sin duplicar registros exactos ya existentes.

No se ejecuta en cada arranque de la API; se ejecuta manualmente una vez o
cuando sea necesario cargar nuevos catalogos.

### Carpeta `venv/`

Es un entorno virtual local. No forma parte de la aplicacion desplegada y esta
excluido por `.gitignore`.

## 3. Configuracion y dependencias externas

### Variables de entorno

| Variable | Necesidad | Funcion |
|---|---|---|
| `FIREBASE_CREDENTIALS` | Requerida en Render | JSON completo de la cuenta de servicio, como texto. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Alternativa local | Ruta al JSON de la cuenta de servicio. |
| `FIREBASE_STORAGE_BUCKET` | Necesaria para evidencias | Nombre del bucket de Firebase Storage. |
| `ORIGENES_PERMITIDOS` | Recomendada | URL o URLs autorizadas del frontend, separadas por comas. |
| `API_TOKEN` | Muy recomendada | Token enviado en `X-API-Token` para escribir. |
| `PORT` | Opcional | Puerto local o asignado por Render. |

Si no existe `API_TOKEN`, la API queda abierta para escrituras. Si existe,
`GET` y `OPTIONS` quedan libres, pero las operaciones distintas de esas deben
enviar:

```http
X-API-Token: valor-del-token
```

Si no existe `ORIGENES_PERMITIDOS`, CORS queda abierto con `*`. Para produccion
conviene indicar unicamente el dominio real del frontend.

## 4. Modelo de datos en Firestore

Firestore utiliza estas colecciones:

### `clientes`

Cada documento representa un cliente y contiene normalmente:

```text
nombre
categoria
estado
frecuencia
frecuencia_original
activo
cobro_por_recoleccion
estatus
```

`frecuencia_original` conserva el valor historico del Excel. La frecuencia
normalizada se utiliza para filtros y reportes. `cobro_por_recoleccion` activa
la regla de cliente prioritario y de segunda vuelta no cobrable.

### `tipos_incidencia`

Contiene el catalogo de tipos de incidencia:

```text
nombre
descripcion
gravedad_default
activo
```

Al crear una incidencia se copia el nombre del tipo y se usa su gravedad
predeterminada si el formulario no envia otra.

### `servicios`

Cada documento representa una recoleccion o entrega:

```text
fecha
cliente_id
cliente
categoria
estado
frecuencia
cobro_por_recoleccion
tipo_servicio
hora_programada
hora_real
realizado
resultado
responsable
observaciones
creado_en
```

Los campos del cliente se guardan tambien dentro del servicio. Esto se llama
denormalizacion: Firestore no hace JOINs como una base SQL, por lo que el
dashboard puede filtrar y graficar sin consultar el cliente por separado.

### `incidencias`

Cada incidencia pertenece a un servicio y a un tipo:

```text
servicio_id
tipo_incidencia_id
tipo_incidencia
gravedad
descripcion
reporto_cliente
resuelta
resuelta_a_tiempo
fecha_resolucion
accion_correctiva
comentarios
vueltas_adicionales
minutos_retraso
segunda_vuelta_no_cobrable
material_pendiente
fecha
cliente_id
cliente
categoria
estado
frecuencia
cobro_por_recoleccion
es_prioritario
tipo_servicio
responsable
evidencias
creado_en
actualizado_en
```

Ademas de los datos propios, copia datos del servicio y del cliente. Esto
permite obtener el detalle y los indicadores leyendo una sola coleccion.

### `catalogos`

Guarda opciones agregadas por los usuarios. Cada documento corresponde a
`categorias`, `estados` o `frecuencias` y tiene esta forma:

```text
valores: ["opcion 1", "opcion 2"]
```

Las opciones almacenadas se combinan con las opciones base de
`utilidades.py`, eliminando duplicados por texto normalizado.

## 5. Flujo general de una peticion

1. El frontend envia una peticion HTTP a una ruta `/api/...`.
2. Flask ejecuta `verificar_token` antes de la ruta.
3. Para escrituras, comprueba `X-API-Token` si `API_TOKEN` esta configurado.
4. La ruta recibe JSON, parametros de URL o archivos multipart.
5. `utilidades.py` limpia textos y normaliza datos basicos.
6. `firebase_db.py` valida referencias y persiste en Firestore o Storage.
7. `indicadores.py` o `reportes.py` procesa los datos cuando corresponde.
8. Flask devuelve JSON, un codigo HTTP o un archivo Excel.

Los codigos mas usados son:

- `200`: lectura o actualizacion correcta.
- `201`: registro o archivo creado.
- `207`: algunos archivos subieron y otros fallaron.
- `400`: datos faltantes o invalidos.
- `401`: token ausente o incorrecto.
- `404`: recurso o catalogo inexistente.
- `409`: nombre duplicado.

## 6. Endpoints disponibles

### Salud y catalogos

| Metodo y ruta | Funcion |
|---|---|
| `GET /api/salud` | Comprueba que Flask esta activo. No valida Firebase. |
| `GET /api/catalogos` | Devuelve gravedades, colores, tipos de servicio, resultados, categorias, estados, frecuencias y tipos de reporte. |
| `POST /api/catalogos/<nombre>/opciones` | Agrega una opcion a categoria, estado o frecuencia. |

### Clientes

| Metodo y ruta | Funcion |
|---|---|
| `GET /api/clientes` | Lista clientes ordenados por nombre. |
| `POST /api/clientes` | Crea un cliente; exige nombre y evita duplicados normalizados. |
| `PUT /api/clientes/<cliente_id>` | Actualiza un cliente y propaga sus datos a servicios e incidencias existentes. |

La propagacion usa lotes y actualiza los documentos relacionados por
`cliente_id`. `frecuencia_original` no se modifica al editar.

### Tipos de incidencia

| Metodo y ruta | Funcion |
|---|---|
| `GET /api/tipos` | Lista tipos de incidencia. |
| `POST /api/tipos` | Crea un tipo con nombre, descripcion y gravedad predeterminada. |

### Servicios

| Metodo y ruta | Funcion |
|---|---|
| `GET /api/servicios` | Lista servicios ordenados del mas reciente al mas antiguo. |
| `GET /api/servicios?limite=20` | Devuelve como maximo la cantidad indicada. |
| `POST /api/servicios` | Crea un servicio; exige `fecha` y `cliente_id`. |

Al crear un servicio, el backend busca el cliente y copia sus datos actuales.
Si el cliente no existe, devuelve error y no crea el servicio.

### Incidencias

| Metodo y ruta | Funcion |
|---|---|
| `GET /api/incidencias` | Lista incidencias ordenadas por fecha. |
| `GET /api/incidencias?abiertas=1` | Devuelve solo incidencias no resueltas. |
| `POST /api/incidencias` | Crea una incidencia ligada a un servicio y un tipo. |
| `PUT /api/incidencias/<incidencia_id>` | Corrige una incidencia existente y conserva evidencias. |
| `POST /api/incidencias/<incidencia_id>/resolver` | Marca una incidencia como resuelta. |
| `POST /api/incidencias/<incidencia_id>/evidencias` | Sube uno o varios archivos usando el campo multipart `evidencias`. |

Para crear o editar una incidencia son obligatorios `servicio_id` y
`tipo_incidencia_id`. El backend valida que ambos documentos existan. Los
campos numericos `vueltas_adicionales` y `minutos_retraso` se convierten a
enteros no negativos.

### Dashboard

| Metodo y ruta | Funcion |
|---|---|
| `GET /api/dashboard` | Devuelve KPIs, graficas, opciones de filtros y detalle de incidencias. |

Acepta filtros como `desde`, `hasta`, `anio`, `trimestre`, `mes`, `semana`,
`estado`, `categoria`, `cliente`, `frecuencia`, `responsable`, `tipo`,
`gravedad`, `reporto_cliente`, `resuelta_a_tiempo` y `prioritario`.

El proceso es:

1. Lee servicios e incidencias.
2. Agrega periodo y retraso horario.
3. Aplica los filtros.
4. Calcula KPIs sobre los datos filtrados.
5. Genera estructuras de Plotly.
6. Devuelve detalle filtrado y opciones disponibles.

### Reportes

| Metodo y ruta | Funcion |
|---|---|
| `GET /api/reportes/opciones` | Devuelve tipos y valores de periodos/clientes disponibles. |
| `GET /api/reportes/generar?tipo=Mensual&valor=2026-01&evidencias=1` | Genera y descarga un Excel. |

El reporte se crea en memoria. `evidencias=0` omite la hoja de evidencias y
evita descargar imagenes desde Storage.

## 7. Indicadores y reglas de negocio

El dashboard y el reporte usan reglas equivalentes:

- **Servicios con incidencia:** cantidad de servicios distintos relacionados
  con alguna incidencia.
- **Servicios sin incidencia:** porcentaje restante sobre el total de servicios.
- **Retrasos:** se toma el mayor valor entre retrasos detectados por horario y
  las incidencias de tipo `Incumplimiento de horario`.
- **Vueltas extra:** se suman `vueltas_adicionales`; si nadie captura una
  cantidad, se cuentan incidencias de tipo `Desvio de ruta / Vueltas excedentes`.
- **Quejas:** incidencias donde `reporto_cliente` es verdadero.
- **Resueltas a tiempo:** porcentaje calculado solo sobre incidencias ya
  resueltas que tienen ese dato.
- **Abiertas y cerradas:** se basan en `resuelta`.
- **Clientes prioritarios:** se identifican mediante `cobro_por_recoleccion`.
- **Segunda vuelta no cobrable:** se cuenta mediante
  `segunda_vuelta_no_cobrable`.
- **Retraso automatico:** una hora real posterior a la hora programada se
  considera retraso.

Las graficas incluyen incidencias por tipo, gravedad, cliente, estado,
categoria y prioridad; frecuencia programada frente a incidencias; y
tendencias mensuales y semanales.

## 8. Evidencias y almacenamiento

El flujo de una evidencia es:

1. El cliente envia archivos multipart en `evidencias`.
2. `app.py` recibe todos los archivos.
3. `utilidades.preparar_evidencia` rechaza extensiones no permitidas.
4. Las imagenes se convierten y comprimen a JPEG.
5. `firebase_db.subir_evidencia` crea una ruta unica:
   `evidencias/<incidencia_id>/<uuid>.<extension>`.
6. El archivo se sube a Firebase Storage.
7. Se crea una URL de descarga con token.
8. El objeto de evidencia se agrega al arreglo `evidencias` de la incidencia.

El limite global de peticion en Flask es de 32 MB. Las evidencias no se
guardan en el disco local de Render.

## 9. Ejecucion local

Desde PowerShell, con las credenciales fuera del repositorio:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\ruta\privada\serviceAccount.json"
$env:FIREBASE_STORAGE_BUCKET="mi-proyecto.firebasestorage.app"
$env:ORIGENES_PERMITIDOS="http://localhost:3000"
$env:API_TOKEN="crea-un-token-largo-y-aleatorio"
python app.py
```

La API queda disponible en `http://localhost:5000` salvo que `PORT` indique
otro puerto.

Comprobaciones recomendadas:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/salud
Invoke-RestMethod http://127.0.0.1:5000/api/catalogos
```

La primera comprueba que Flask esta arriba. La segunda comprueba tambien el
acceso real a Firestore.

## 10. Carga inicial de catalogos

Con las credenciales configuradas, ejecutar desde la raiz:

```powershell
python scripts/cargar_catalogos.py
```

El script crea los tipos de incidencia y carga los clientes del Excel. Se debe
verificar el contenido y la estructura del Excel antes de usarlo en otro
proyecto, porque el script espera la hoja y encabezados indicados arriba.

## 11. Despliegue en Render

La configuracion de produccion prevista es:

```text
Build: pip install -r requirements.txt
Start: gunicorn app:app
```

En Render se deben configurar como secretos:

- `FIREBASE_CREDENTIALS` con el JSON completo de la cuenta de servicio.
- `FIREBASE_STORAGE_BUCKET` con el nombre exacto del bucket.
- `ORIGENES_PERMITIDOS` con el dominio del frontend.
- `API_TOKEN` con un valor largo y aleatorio.

Nunca se debe publicar el JSON de la cuenta de servicio en el codigo, README,
issues, commits o chats. Si una clave fue expuesta, hay que revocarla y generar
otra.

## 12. Puntos importantes del estado actual

1. La API no tiene autenticacion de lectura: los `GET` quedan libres incluso
   cuando existe `API_TOKEN`.
2. Sin `API_TOKEN`, cualquier cliente que alcance la API puede escribir.
3. Sin `ORIGENES_PERMITIDOS`, CORS permite cualquier origen.
4. La conexion a Firebase es perezosa; que Flask arranque no garantiza que las
   credenciales sean correctas.
5. Las incidencias y servicios duplican datos del cliente. Si se edita un
   cliente mediante el endpoint previsto, el backend propaga los cambios; una
   modificacion directa en Firestore podria dejar datos desactualizados.
6. El limite de subida es 32 MB por peticion, no necesariamente por archivo.
7. Los reportes pueden tardar mas si incluyen muchas evidencias porque descargan
   imagenes desde Storage para incrustarlas en Excel.
8. `render.yaml` debe corregirse si el repositorio desplegado conserva la
   estructura actual de este workspace.

## 13. Resumen de responsabilidades

```text
app.py
  HTTP, rutas, token, CORS, respuestas

firebase_db.py
  Firebase, Firestore, Storage, persistencia y relaciones

utilidades.py
  Limpieza, catalogos, fechas, reglas auxiliares y archivos

indicadores.py
  Periodos, filtros, KPIs y datos de graficas

reportes.py
  Seleccion de periodo y generacion de Excel

cargar_catalogos.py
  Carga inicial desde Excel
```

En conjunto, el sistema sigue una separacion sencilla: la API recibe y valida,
la capa Firebase persiste, las utilidades normalizan, indicadores analiza y
reportes exporta.
