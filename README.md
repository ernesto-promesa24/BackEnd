<div align="center">
  <img src="https://luiscpromesa.github.io/Dashboiard_Incidencias/static/img/isotipo_promesa.png" alt="Isotipo Grupo PROMESA" width="120"/>
  <h1>Sistema de Incidencias Logísticas | API REST</h1>
  <p><strong>Motor de persistencia, reglas de negocio y generación de reportes operativos</strong></p>
</div>

---

## 📌 Descripción del Proyecto

Este repositorio contiene la capa lógica (Backend) del **Sistema de Incidencias Logísticas** de Grupo PROMESA. Construido como una API RESTful, actúa como el puente de comunicación seguro y eficiente entre la interfaz de usuario web y la infraestructura de almacenamiento en la nube de Google Cloud (Firebase)[cite: 2].

El backend no almacena datos de forma local, lo que permite un despliegue efímero y altamente escalable en plataformas de contenedores o servicios en la nube (PaaS) como Render[cite: 2].

---

## ✨ Funcionalidades Core

* 🔗 **Integración con Firebase:** Conexión administrativa con Firestore para el almacenamiento NoSQL de catálogos, clientes e incidencias, y con Firebase Storage para la retención de evidencias multimedia[cite: 2].
* 🚀 **Consultas Optimizadas:** Implementación de un modelo de datos desnormalizado que incrusta información de clientes dentro de los servicios e incidencias, eliminando la necesidad de *JOINs* y logrando respuestas en milisegundos[cite: 2].
* 📊 **Motor de Inteligencia de Datos:** Módulo dedicado (`indicadores.py`) que procesa la información en memoria para calcular KPIs, cruzar variables de tiempo y estructurar datos listos para ser consumidos por librerías gráficas como Plotly[cite: 2].
* 📄 **Generación de Reportes Dinámicos:** Construcción de archivos Excel (`.xlsx`) en memoria que incluyen resúmenes ejecutivos, hojas de datos detalladas y evidencias fotográficas incrustadas dinámicamente[cite: 2].
* 🖼️ **Procesamiento de Archivos:** Validación MIME, compresión y redimensionamiento automático de imágenes subidas mediante `FormData` a formato JPEG optimizado antes de su carga a la nube[cite: 2].

---

## 🛠️ Stack Tecnológico

| Tecnología | Propósito en el Proyecto |
| :--- | :--- |
| **Python 3** | Lenguaje de programación principal[cite: 2]. |
| **Flask** | Micro-framework web para el enrutamiento HTTP y endpoints REST[cite: 2]. |
| **Firebase Admin SDK** | Autenticación y gestión directa con los servicios de Google Cloud[cite: 2]. |
| **OpenPyXL** | Creación y manipulación avanzada de libros de Excel[cite: 2]. |
| **Pillow (PIL)** | Manipulación y compresión de imágenes en el servidor[cite: 2]. |
| **Gunicorn** | Servidor HTTP WSGI para la orquestación en entornos de producción[cite: 2]. |

---

## 📂 Arquitectura de Módulos

El proyecto respeta el principio de responsabilidad única, separando las capas de la siguiente forma[cite: 2]:

* `app.py`: Punto de entrada HTTP. Controla el enrutamiento, CORS, verificación de tokens y respuestas JSON[cite: 2].
* `modulos/firebase_db.py`: Capa de abstracción de datos. Aísla toda la lógica de lectura, escritura y eliminación hacia Firestore y Storage[cite: 2].
* `modulos/indicadores.py`: Motor matemático que filtra, agrupa y calcula KPIs basados en el periodo de tiempo solicitado[cite: 2].
* `modulos/reportes.py`: Generador asíncrono de reportes `.xlsx`[cite: 2].
* `modulos/utilidades.py`: Funciones transversales (limpieza de texto, estandarización de fechas, procesamiento de imágenes)[cite: 2].

---

## 🔐 Configuración y Despliegue (Entorno de Producción)

Para el despliegue del servicio web (ej. Render), es indispensable inyectar las siguientes variables de entorno (Secrets)[cite: 2]:

1. `FIREBASE_CREDENTIALS`: Cadena de texto exacta que contiene el JSON de la cuenta de servicio de Google Cloud[cite: 2].
2. `FIREBASE_STORAGE_BUCKET`: URL del bucket (ej. `proyecto.appspot.com`)[cite: 2].
3. `API_TOKEN`: Cadena de alta entropía requerida en el Header `X-API-Token` para autorizar las peticiones `POST`, `PUT` y `DELETE`[cite: 2].
4. `ORIGENES_PERMITIDOS`: (Recomendado) Lista de dominios admitidos para restringir el acceso vía CORS[cite: 2].

> **Aviso de Seguridad:** El archivo `.gitignore` protege la integridad del repositorio bloqueando la subida de claves como `serviceAccount.json`, entornos virtuales (`venv/`) y variables locales (`.env`)[cite: 2].