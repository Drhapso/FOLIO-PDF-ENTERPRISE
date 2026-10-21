# Despliegue del editor y reconstruccion local de escaneos

## Version publicada

- Build: `2026-10-21-scan-local-1`.
- Fecha: 2026-10-21.
- Desarrollo: `D:\PROYECTOS IA INDEPENDIENTES\FOLIO PDF\FOLIO PDF ENTERPRISE`.
- Produccion: `G:\PROYECTOS IA INDEPENDIENTES\FOLIO PDF\FOLIO PDF ENTERPRISE`.
- Servicio: tarea `Folio-PDF-LAN`, puerto 8090.
- Acceso principal: `http://172.23.174.11:8090`.
- Acceso proxy: `http://172.23.174.103:8090`.

El editor unificado agrega reconstruccion local conservadora de palabras en
escaneos. No convierte toda la pagina, no equivale al motor propietario de
Adobe y exige revision visual. Las zonas no admitidas se bloquean con motivo.
Consultar [README](../README.md#escaneos-reconstruccion-local-conservadora)
y [registro de cambios](../CHANGELOG.md).

## Publicacion y activacion

El publicador automatico copia fuentes de desarrollo al servidor. Durante la
preparacion ya habia propagado el codigo nuevo, pero el proceso activo seguia
informando `2026-10-21-acrobat-unified-1`. Copiar archivos no reinicia el proceso.

Se verificaron en el entorno virtual de produccion PyMuPDF 1.28.2, OpenCV
4.14.0, NumPy 2.5.4 y la existencia de modelos OCR espanol e ingles. No fue
necesario instalar paquetes ni cambiar dependencias.

Se respaldaron las fuentes recibidas y el baseline Git `aca7f9c` en:

`G:\PROYECTOS IA INDEPENDIENTES\_OPERACION\arranque-principal\release-backup-20261021-scan-local-1`

El respaldo de fuentes recibidas ya contiene codigo propagado por el publicador;
no debe confundirse con una copia exacta del codigo cargado por el proceso
anterior. `baseline-aca7f9c.zip` conserva una revision Git anterior conocida.
`release-sha256.json` registra hashes del conjunto de archivos publicado.

Se copiaron explicitamente fuentes, recursos y documentacion relacionados,
comprobando SHA-256 local/remoto. No se tocaron configuraciones privadas,
modelos, bases de datos, instalaciones de otros proyectos ni reglas de red.
Los PDF de muestra no se incorporan al repositorio Git.

Tras comprobar que no existian trabajos ni transferencias temporales se
ejecuto el script administrativo `reiniciar-folio.ps1` del servidor principal.
Solo se reinicio EVA PDF. El listener paso del PID 17452 al PID 16528 y el
registro manual confirmo `manual_restart_verified` a las 13:08:29 UTC.
El hash de la configuracion privada permanecio identico.

## Diagnostico posterior

- 35 pruebas enfocadas locales aprobadas: texto nativo, escaneos, OCR invisible,
  pagina mixta, anotaciones, censura, funciones vecinas y distribucion.
- Aparecen avisos `ResourceWarning` de temporales en la ejecucion de pruebas;
  no se consideran resueltos por este despliegue. No hubo fallos de prueba.
- `/health` directo y por proxy: HTTP 200, estado `ok`, build nuevo.
- Interfaz `/editor` publicada con controles y avisos de escaneos.
- Prueba HTTP contra produccion con una muestra real: 552 palabras detectadas,
  325 admitidas y 227 bloqueadas.
- Reemplazo individual comprobado en PDF descargado y vista multipart; cabecera
  de limpieza `complete`.
- Comparacion a 216 DPI: cero pixeles cambiados fuera de la caja de control
  (fragmento mas dos puntos por lado). Tras quitar en memoria el reemplazo,
  fraccion de canales oscuros menores de 180 en el fragmento: 0.
- Hash del original sin cambios.
- Limites conservados: 1024 MiB por archivo y por envio conjunto, cinco motores
  como techo; no se modifico la configuracion de produccion.

Las metricas de una muestra no garantizan resultados en todos los documentos.
No se genero ni publico un instalador offline nuevo: se actualizo la aplicacion
web y la receta del ejecutable para incluir `scan_editor`.

## Recuperacion

Coordinar una ventana sin trabajos. Corregir primero las fuentes locales del
publicador a la revision elegida: restaurar solo el servidor no es persistente.
No restaurar configuraciones privadas ni bases desde una version de codigo.
El archivo baseline permite recuperar la revision anterior conocida; su activacion
requiere revision y validacion previa, no sobrescribir indiscriminadamente.
Despues reiniciar exclusivamente Folio con el script administrativo y verificar
identidad del listener, `/health`, recursos y una operacion de prueba.

Ver [recuperacion de servicios](../RECUPERACION_SERVICIOS.md#reinicio-manual).
