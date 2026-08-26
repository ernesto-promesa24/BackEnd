# Configuracion de Firebase

## Hallazgo principal

El backend **no contiene actualmente un archivo JSON de credenciales**. La busqueda del workspace no encontro ningun `*.json` de cuenta de servicio.

La inicializacion ocurre en `modulos/firebase_db.py` y usa este orden:

1. `FIREBASE_CREDENTIALS`: JSON completo de una cuenta de servicio, guardado como texto en la variable.
2. `GOOGLE_APPLICATION_CREDENTIALS`: ruta local a un archivo JSON de cuenta de servicio.
3. Si ninguna existe, se lanza:

   `RuntimeError: Faltan credenciales de Firebase...`

La conexion es perezosa: `python app.py` puede mostrar que Flask arranco, pero la primera ruta que consulta Firestore, por ejemplo `/api/catalogos`, fallara si no hay credenciales.

## Variables requeridas y opcionales

| Variable | Obligatoria | Valor |
| --- | --- | --- |
| `FIREBASE_CREDENTIALS` | Si se despliega en Render | Contenido JSON completo de la cuenta de servicio de Firebase, sin modificarlo. Es la variable critica. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Alternativa local | Ruta absoluta al JSON de la cuenta de servicio. No se usa si `FIREBASE_CREDENTIALS` esta definida. |
| `FIREBASE_STORAGE_BUCKET` | Para adjuntar evidencias | Nombre del bucket, por ejemplo `mi-proyecto.firebasestorage.app` o el valor mostrado en Firebase Storage. |
| `ORIGENES_PERMITIDOS` | Recomendable | URL del frontend, o varias URLs separadas por comas. Si falta, CORS queda abierto (`*`). |
| `API_TOKEN` | Muy recomendable | Token que el frontend debe enviar en `X-API-Token` para operaciones distintas de `GET` y `OPTIONS`. Si falta, la API queda abierta para escrituras. |

`FIREBASE_STORAGE_BUCKET` no reemplaza a las credenciales. Firestore puede inicializarse sin bucket, pero las evidencias requieren que esta variable este configurada.

## Obtener las credenciales

1. En Firebase Console, abre el proyecto correcto.
2. Entra en **Project settings > Service accounts**.
3. Selecciona **Generate new private key** y descarga el JSON.
4. Guarda el archivo fuera del repositorio, con permisos restringidos.
5. Nunca pegues el JSON en el codigo, en el README, en un issue, en un commit ni en un chat. La clave privada del JSON es un secreto.

Si una clave ya fue expuesta, revocala y genera otra desde Google Cloud/Firebase antes de continuar.

## Configuracion local en Windows PowerShell

Desde la raiz del proyecto, suponiendo que el archivo se guardo en una ruta privada:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\ruta\privada\serviceAccount.json"
$env:FIREBASE_STORAGE_BUCKET="mi-proyecto.firebasestorage.app"
$env:ORIGENES_PERMITIDOS="http://localhost:3000"
$env:API_TOKEN="crea-un-token-largo-y-aleatorio"
python app.py
```

Estas variables solo viven en la terminal actual. Para revisar que la ruta existe sin imprimir el secreto:

```powershell
Test-Path $env:GOOGLE_APPLICATION_CREDENTIALS
```

Para limpiar las variables al terminar:

```powershell
Remove-Item Env:GOOGLE_APPLICATION_CREDENTIALS
Remove-Item Env:FIREBASE_STORAGE_BUCKET
Remove-Item Env:ORIGENES_PERMITIDOS
Remove-Item Env:API_TOKEN
```

### Usar `FIREBASE_CREDENTIALS` localmente

Tambien se puede cargar el JSON completo en `FIREBASE_CREDENTIALS`, aunque para desarrollo local es mas practico y menos propenso a errores usar `GOOGLE_APPLICATION_CREDENTIALS`:

```powershell
$json = Get-Content "C:\ruta\privada\serviceAccount.json" -Raw
$env:FIREBASE_CREDENTIALS = $json
$env:FIREBASE_STORAGE_BUCKET = "mi-proyecto.firebasestorage.app"
python app.py
```

No ejecutes `Write-Output $env:FIREBASE_CREDENTIALS` ni pegues su contenido en una consola compartida.

## Configuracion en Render

En el servicio web, abre **Environment** y agrega:

- `FIREBASE_CREDENTIALS`: pega el JSON completo de la cuenta de servicio como valor secreto.
- `FIREBASE_STORAGE_BUCKET`: nombre exacto del bucket.
- `ORIGENES_PERMITIDOS`: URL publica del frontend, sin comodin si es posible.
- `API_TOKEN`: token largo y aleatorio.

Despues guarda y haz un redeploy. En Render no configures `GOOGLE_APPLICATION_CREDENTIALS` salvo que tambien subas de forma segura el archivo al entorno, lo que no es necesario para este proyecto.

### Importante sobre `render.yaml`

El archivo actual declara `rootDir: backend`. Esta configuracion solo es correcta si `render.yaml` esta siendo usado desde un repositorio cuyo subdirectorio se llama `backend` y contiene `app.py` y `requirements.txt`. En este workspace esos archivos estan en la raiz `BackEnd`; si este es tambien el repositorio desplegado, elimina `rootDir: backend` o cambialo por la ruta real antes de desplegar.

## Verificacion segura

1. Arranca el servidor con las variables configuradas.
2. Comprueba salud:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/salud
```

3. Comprueba una lectura que use Firestore:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/catalogos
```

La primera respuesta valida que Flask esta arriba; la segunda valida que las credenciales permiten acceder a Firestore. No uses un endpoint de escritura como prueba inicial.

## Seguridad del repositorio

`.gitignore` ya excluye `serviceAccount.json`, `*serviceAccount*.json`, `.env`, `venv/` y caches de Python. Mantener esas exclusiones y confirmar antes de subir cambios:

```powershell
git status --short
git check-ignore -v serviceAccount.json
```

No se incluyeron credenciales reales en este documento porque no existe ningun JSON de cuenta de servicio en el workspace y porque esas credenciales no deben documentarse en texto plano.
