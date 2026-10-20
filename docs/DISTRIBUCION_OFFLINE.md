# Preparacion de ejecutable e instalador offline

## Estado de esta entrega

Se prepara una receta Windows x64, **sin generar Folio.exe ni Setup.exe**.
Version propuesta: `3.1.0`; es un parametro de empaquetado, no una publicacion.
El build web sigue identificado por `CLIENT_BUILD` en `server.py`.
La receta debe certificarse creando y probando los binarios en una siguiente
entrega autorizada. Pruebas del codigo fuente no certifican un paquete congelado.

- Ejecutable: PyInstaller en modo **onedir**, consola visible para errores.
- Instalador: Inno Setup 6.3 o posterior de la serie 6, por usuario en `%LOCALAPPDATA%\Folio-PDF`.
- Sin Python previo, descargas, servicio automatico ni cambios de firewall
  durante la instalacion. No instala controladores, proxy ni certificados.
- La consola del servidor debe permanecer abierta. No se abre automaticamente
  el navegador: usar el acceso directo de navegador despues de iniciar el servidor.
- Windows 10/11 x64; Windows Server y ARM64 requieren certificacion aparte.

## Archivos de la receta

| Archivo | Funcion |
|---|---|
| `deploy/release.example.json` | Version propuesta, Python 3.13 x64, compilador Inno y hashes OCR. |
| `requirements-build.txt` | Dependencias del producto y PyInstaller; no se instala nada automaticamente. |
| `deploy/build-executable.ps1` | Prevalidacion; construccion solo con `-Build`. |
| `deploy/folio.spec` | Lista de recursos y motores que PyInstaller debe incorporar. |
| `deploy/frozen_entry.py` | Separa servidor y worker dentro de Folio.exe. |
| `deploy/installer.iss` | Receta de Setup.exe, sin acceso a Internet. |
| `tests/test_distribution.py` | Rutas del worker y despacho fuente/congelado. |

## Preparar la maquina de construccion (paso futuro)

Usar una carpeta de trabajo limpia, Windows x64 y CPython **3.13 x64**.
No reutilizar la `.venv` copiada de otro equipo ni modificar el entorno de
produccion. Crear `.venv-build` y preparar dependencias en esa maquina:

```powershell
py -3.13 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
```

Este es un paso manual futuro; no se ejecuto como parte de esta preparacion.
Para un constructor tambien desconectado, descargar previamente los wheels y
sus dependencias para **la misma version/arquitectura** en una maquina autorizada:

```powershell
.\.venv-build\Scripts\python.exe -m pip download -r requirements-build.txt --dest wheelhouse
.\.venv-build\Scripts\python.exe -m pip install --no-index --find-links wheelhouse -r requirements-build.txt
```

Las versiones tienen rangos; para repetir exactamente una release, conservar
`BUILD-DEPENDENCIES.txt`, el wheelhouse, sus hashes y las versiones del compilador,
Python y Windows en el expediente de release. Esta receta no promete builds
binarios reproducibles ni una cadena de suministro fijada por hashes.

Instalar Inno Setup 6.3+ en la maquina constructora y verificar su procedencia.
Copiar `deploy/release.example.json` a `deploy/release.local.json` y adaptar
version y ruta del compilador, sin incluir datos internos. Obtener los modelos
espanol/ingles con `deploy/install-ocr.ps1` en una maquina autorizada y comparar
sus SHA256 con los parametros. La construccion valida los modelos, no los baja.

## Prevalidar sin generar nada

```powershell
.\deploy\build-executable.ps1 -ParametersFile .\deploy\release.local.json -Python .\.venv-build\Scripts\python.exe
```

Sin `-Build` solo revisa parametros, interprete, dependencias, PyInstaller y
modelos. `-Installer` requiere `-Build`; no hay un instalador implicito.
Usar la politica de ejecucion aprobada por TI, sin cambiarla para sortear bloqueos.

## Construir en la proxima entrega autorizada

**No ejecutar estos comandos durante la preparacion actual.**
Antes, revisar licencias y aprobar la redistribucion:

```powershell
# Solo Folio.exe y dependencias:
.\deploy\build-executable.ps1 -ParametersFile .\deploy\release.local.json -Python .\.venv-build\Scripts\python.exe -Build -LicensesReviewed

# Folio.exe y Setup.exe, desde una salida que todavia no exista:
.\deploy\build-executable.ps1 -ParametersFile .\deploy\release.local.json -Python .\.venv-build\Scripts\python.exe -Build -Installer -LicensesReviewed
```

Se ejecutan las pruebas antes de PyInstaller. Una salida existente se rechaza,
no se borra ni se sobreescribe. Tras empaquetar se ejecuta `Folio.exe --calibrate`
para ejercitar la entrada congelada, workers, motores y modelos. Se eliminan
`instance` y `runtime` **solo de esa nueva carpeta de salida** para no distribuir
un perfil de hardware ni documentos del constructor. Si hay un error, se detiene
y conserva la salida parcial para investigacion; no distribuirla ni reanudar
pisandola. Eliminar solo esa salida concreta tras revisarla, o elegir otra version.

Salida prevista: `dist/release-<version>/Folio/Folio.exe`, dependencias al lado
y, si se solicita, `Folio-Setup-<version>-win-x64.exe`.
`SHA256SUMS.txt` enumera el payload; `INSTALLER-SHA256SUMS.txt` verifica el Setup.
Los hashes no equivalen a firma de editor. Esta receta **no firma** los binarios;
TI debe revisar firma Authenticode/SmartScreen y politica antivirus antes de publicar.
El inventario de dependencias usa nombres/versiones (`pip list`), no URLs
de instalaciones directas que pudieran incluir rutas o credenciales.

## Alcance offline y motores externos

Los modelos y librerias Python se incluyen. Los recursos web son locales;
no se incluye el GIF de referencia ni arte, audio o tipografias de terceros
tomados como inspiracion. La comprobacion de firmas sigue siendo offline:
no valida confianza, revocacion ni validez legal.

**LibreOffice no se redistribuye ni instala en esta receta.** Office a PDF
requiere instalarlo previamente en el destino, mediante un instalador offline
aprobado y revisando sus licencias, o configurar `libreoffice_path`. Sin el motor,
la interfaz indica MOTOR PENDIENTE. No se promete un instalador con todas las
funciones habilitadas sin ese requisito. WIA/impresion/camara siguen en construccion.

## Licencias y publicacion en GitHub

- Revisar la licencia exacta de cada version, incluidas dependencias transitivas
  y bibliotecas nativas; conservar avisos y textos de licencia del paquete.
- En particular, PyMuPDF/MuPDF tiene condiciones AGPL o licencia comercial:
  decidir un regimen compatible antes de distribuir. `-LicensesReviewed` es
  una confirmacion operativa, no concede derechos ni reemplaza esa revision.
- Revisar tambien pikepdf/qpdf, Pillow/HEIF y codecs, OpenCV, criptografia,
  modelos tessdata, PyInstaller y dependencias web. No retirar sus avisos.
- No se asigna una licencia al codigo propio sin decision del titular.
  Un repositorio publico sin licencia no equivale a software de libre uso.
- Publicar codigo revisado por Git y adjuntar binarios aprobados mediante
  GitHub Releases; no guardar EXE, ZIP, ruedas o motores en el repositorio.
- No usar `git add .` sin revisar. Excluir configuracion local, `.venv*`,
  `instance`, `runtime`, datos, claves, logs y modelos. `.gitignore` no limpia
  archivos ya rastreados ni el historial: revisar `git ls-files` y `git diff --cached`.
- Revisar manualmente el TXT de referencia y la imagen existente en la raiz:
  verificar derechos de publicacion y contenido antes de agregarlos a una release.
- Los TXT de `FOLIO PDF INSTALLER WINDOWS` son referencias historicas:
  no prueban que una release corresponda al codigo actual.

No se hizo commit, push ni publicacion como parte de esta preparacion.

## Validacion realizada durante la preparacion

- 86 pruebas de codigo fuente aprobadas, incluidas cinco nuevas de despacho
  de workers y entrada congelada simulada.
- Sintaxis de PowerShell validada mediante su parser; sintaxis de la receta
  Python y parametros JSON comprobados sin compilar.
- Exclusiones Git verificadas y ausencia de `build`/`dist` confirmada.
- La ejecucion de prevalidacion PowerShell fue bloqueada por la politica
  de scripts de este equipo; no se cambio ni se sorteo esa politica.
- PyInstaller no esta instalado en el entorno actual y no se encontro
  Inno Setup en la ruta de ejemplo. Prepararlos en un constructor dedicado
  es una tarea futura, no un requisito para continuar usando Folio desde fuente.
- No se ejecutaron PyInstaller ni Inno Setup; el ejecutable y el instalador
  siguen pendientes de generacion y pruebas en VM offline.

## Instalacion, actualizacion y aceptacion pendiente

1. En una VM Windows limpia, sin Python y con red desconectada, instalar
   Setup como usuario normal en una ruta con espacios y caracteres no ASCII.
2. Iniciar el servidor y comprobar `/health`, las 46 tarjetas, `/editor`,
   fuentes, apertura a pantalla completa y opciones de portada.
3. Procesar PDF sinteticos: unir, expediente con/sin portada, dividir,
   texto, render, OCR espanol/ingles, HEIC, EPUB y firmas de prueba.
   Repetir Office a PDF con y sin LibreOffice disponible.
4. Verificar cuotas, cancelacion a 120 s, concurrencia, aislamiento Windows,
   descarga grande y limpieza tras error/reinicio. Recalibrar en el destino.
5. Probar inicio LAN explicito con `Folio.exe --host 0.0.0.0`, firewall
   aprobado y un segundo equipo fisico. El instalador no abre la red.
6. Detener Folio antes de actualizar; respaldar solo configuracion tecnica,
   nunca `runtime`. Los archivos locales no forman parte del payload.
   El instalador conserva archivos no instalados (configuracion y estado).
7. Desinstalar y comprobar restos. Los datos creados en ejecucion no se
   borran recursivamente por la receta; revisar y eliminar solo la carpeta de
   instalacion conocida tras detener el servidor, conforme a la politica local.
8. Verificar hashes, licencias, firma/antivirus y funcionamiento sin Internet.
   Registrar resultados y aprobacion antes de anunciar la release como estable.
