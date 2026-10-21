# Reglas de Proyecto — FOLIO-PDF-ENTERPRISE (EVA PDF Enterprise)

## Registro Obligatorio de Cambios para GitHub Copilot Chat

Enunciado original del usuario:
> "todos los cambios que se hagan aqui, registralos en un archivo txt llamado "Cambios de antigravity" para que en otro equipo , Github copilot chat pueda leerlos y entender que cambio y como implementarlo. guarda esto en tu memoria para cada edicion o modificacion hecha a este proyecto en adelante. deja este mismo enunciado completo en el archivo txt, guardalo en el formato necesario para que github copilot chat lo pueda entender sin problemas"

### Reglas de Ejecución en Cada Modificación
1. **Invariante obligatorio:** Cada vez que se cree, edite o elimine cualquier archivo del proyecto, **DEBES** actualizar inmediatamente el archivo `Cambios de antigravity.txt` en la raíz del repositorio antes de dar por finalizada la tarea.
2. **Preservación del encabezado:** Nunca elimines ni alteres el encabezado con el enunciado original del usuario ni la guía de lectura para GitHub Copilot Chat en `Cambios de antigravity.txt`.
3. **Formato de cada entrada (`[CAMBIO-XXX]`):**
   Añade al final de la sección `HISTORIAL DE CAMBIOS` de `Cambios de antigravity.txt` un bloque numerado secuencialmente con:
   - **ID, Fecha/Hora y Título descriptivo.**
   - **Resumen / Motivo:** Qué cambió y por qué, incluyendo cualquier consideración de arquitectura (`CLIENT_BUILD`, aislamiento de subprocesos, limpieza temporal).
   - **Archivos modificados:** Rutas relativas desde la raíz del proyecto e indicador (`creado`, `modificado` o `eliminado`).
   - **Detalle de implementación para GitHub Copilot Chat:** Bloques exactos `<<< SEARCH`, `=== REPLACE` y `>>> END` con líneas de contexto suficientes para que GitHub Copilot Chat en otro equipo pueda localizar y aplicar el cambio sin ambigüedad.
   - **Verificación:** Comandos de prueba ejecutados y resultado obtenido.

