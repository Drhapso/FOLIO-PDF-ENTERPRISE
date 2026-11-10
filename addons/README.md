# EVA PDF Enterprise - Addons Modulares Offline

El nucleo de **EVA PDF Enterprise** funciona de manera autonoma y 100% offline con todas las herramientas clasicas y las 20 capacidades V2 mediante motores locales en Python (`PyMuPDF`, `pikepdf`, `OpenCV`, `NumPy`, `cryptography`, `pyHanko`, `lxml`, `openpyxl`).

Opcionalmente, puedes ampliar ciertas capacidades instalando paquetes locales dentro de esta carpeta `addons/` sin conectar el servidor a internet:

- `addons/pack-ocr-onnx/` (`manifest.json` + modelos ONNX / paquete Python `onnxruntime`): Acelera reconocimiento de ecuaciones matematicas complejas.
- `addons/pack-nmt/` (`manifest.json` + subcarpetas `en_es/` y `es_en/` con modelos CTranslate2 + `sentencepiece.model`/`bpe.model`, instalables localmente con `deploy\install-nmt.ps1`): Traduccion neuronal 100% offline ES↔EN sin SLM externo.
- `addons/pack-tts/` (`manifest.json` + ejecutable/modelos `piper` `.onnx`): Sintesis de voz WAV offline adjunta al paquete PDF/UA (`narracion.json` siempre se genera para Web Speech API).
- `addons/pack-jbig2/` (`manifest.json` + `jbig2enc` en modo estrictamente **lossless** / sin perdida): Compresion bitonal alternativa en capas MRC.
- `static/vendor/pdfium/` (`pdfium.js`, `pdfium.wasm`): Visor Wasm local para Canvas si activas `allow_wasm_viewer: true` en `config/site_config.json`.
- `static/vendor/katex/` (`katex.min.js`, `katex.min.css`): Tipografia KaTeX enriquecida en navegador (EVA ya incluye un renderizador SVG vectorial nativo en JavaScript).

Cada carpeta de pack puede incluir un `manifest.json` simple:

```json
{
  "name": "EVA TTS Offline Pack",
  "version": "1.0.0",
  "capabilities": ["piper_tts"]
}
```
