# EVA PDF Enterprise

### Tu centro documental. En tu equipo o en tu red. Sin subir archivos a una nube.

EVA PDF Enterprise es una plataforma web para organizar, editar, convertir,
comprimir y proteger documentos PDF desde el navegador. Funciona en un solo
equipo o como servidor de la red local (LAN), sin instalar el editor en cada
puesto, sin cuentas, sin suscripciones y sin enviar documentos a servicios
externos.

> Antes llamada **Folio PDF**. Algunas rutas, tareas y scripts internos
> conservan ese nombre por compatibilidad operativa.

## Características generales

- **Procesamiento 100 % local.** Sin APIs externas, CDN, fuentes remotas ni
  telemetría. Funciona sin Internet una vez instaladas sus dependencias.
- **Local, LAN u offline.** Los clientes solo necesitan un navegador; Python,
  LibreOffice y los modelos OCR residen en el servidor.
- **Privacidad por diseño.** No guarda biblioteca documental ni historial: los
  originales y temporales se eliminan al entregar el resultado.
- **Más de 40 herramientas PDF.** Unir, dividir, rotar, comprimir, OCR,
  convertir, firmar visualmente, formularios, comparar, reparar, proteger y más.
- **Lotes y expedientes.** Hasta 200 archivos por envío dentro de una cuota de
  1 GB, con resultados ZIP numerados.
- **Capacidad controlada.** Procesos aislados, cola acotada, límites de tiempo
  y memoria, y calibración según el hardware del equipo.
- **Interfaz propia.** Temas claro y oscuro, diseño adaptable y accesible.

## Funciones más novedosas

1. **Editor único estilo Acrobat.** Editar, anotar y censurar en una sola vista:
   el texto se reemplaza en el propio PDF, sin parches blancos superpuestos,
   conservando fondos, imágenes y trazos.
2. **Edición de documentos escaneados.** Reconstrucción local conservadora con
   OCR y restauración del fondo; rechaza las zonas donde no es seguro editar.
3. **PDF a Word con disposición fiel.** Texto y tablas editables en su posición
   original sobre el fondo de la página (logos, firmas, sellos y marcas de
   agua), con la misma paginación del PDF.
4. **PDF a Excel y PowerPoint editables.** Tablas con celdas combinadas,
   estilos y rellenos; diapositivas con texto y tablas editables.
5. **Compresión estructural sin pérdida.** Reduce el peso sin bajar la
   resolución ni rasterizar; si no mejora, devuelve el original con aviso.
6. **OCR sin servicios externos.** Español e inglés, enderezado y limpieza de
   escaneos.
7. **Comprobación de firmas offline.** Informe de integridad criptográfica,
   cobertura y cambios posteriores a la firma.
8. **Nombres de exportación uniformes.** Todos los resultados se descargan como
   `EVA00` con su extensión (`EVA00_01`, `EVA00_02`… dentro de los ZIP).

## Inicio rápido

Requisitos: Python 3.13 y Windows 10/11 o Server.

```powershell
# Desde la carpeta del repositorio
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\install-ocr.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\run-lan.ps1 -LocalOnly
```

Abrir `http://127.0.0.1:8090`; para servir en la LAN, omitir `-LocalOnly`.
Office a PDF requiere LibreOffice instalado en el servidor.

## Documentación

- [Manual técnico y de operación](docs/MANUAL_TECNICO.md): herramientas,
  límites, despliegue LAN, configuración, pruebas y recuperación.
- [Distribución offline](docs/DISTRIBUCION_OFFLINE.md)
- [Historial de cambios](CHANGELOG.md)

> EVA PDF Enterprise prioriza tareas documentales locales y no pretende
> sustituir todas las funciones de un editor profesional como Adobe Acrobat.
