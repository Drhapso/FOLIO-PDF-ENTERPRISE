from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path


LEGACY_IMAGE_TYPES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".heic", ".heif"})
LEGACY_OFFICE_TYPES = frozenset({".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"})
LEGACY_ALL_UPLOAD_TYPES = (
    frozenset({".pdf", ".html", ".htm", ".epub"}) | LEGACY_IMAGE_TYPES | LEGACY_OFFICE_TYPES
)


@dataclass(frozen=True)
class OperationSpec:
    name: str
    handler_ref: str
    allowed_extensions: frozenset[str] = frozenset({".pdf"})
    min_files: int = 1
    bulk: bool = False
    heavy: bool = False
    ai_heavy: bool = False
    required_addons: tuple[str, ...] = ()
    preserve_zip_paths: bool = False
    phase: int = 1
    title: str = ""


_PDF = frozenset({".pdf"})
_PDF_OR_IMG = _PDF | LEGACY_IMAGE_TYPES

V2_SPECS: dict[str, OperationSpec] = {
    # Fase 1: MVP Determinista
    "anti_track": OperationSpec(
        name="anti_track",
        handler_ref="engines.forensics:handle_anti_track",
        allowed_extensions=_PDF,
        phase=1,
        title="Purga Anti-Rastreo",
    ),
    "forensic_sanitize": OperationSpec(
        name="forensic_sanitize",
        handler_ref="engines.forensics:handle_forensic_sanitize",
        allowed_extensions=_PDF,
        heavy=True,
        phase=1,
        title="Desinfeccion Forense Profunda",
    ),
    "extract_vectors_svg": OperationSpec(
        name="extract_vectors_svg",
        handler_ref="engines.vectors_and_tables:handle_extract_vectors_svg",
        allowed_extensions=_PDF,
        phase=1,
        title="Cosechador Vectorial SVG/EPS",
    ),
    "table_bridge_extract": OperationSpec(
        name="table_bridge_extract",
        handler_ref="engines.vectors_and_tables:handle_table_bridge_extract",
        allowed_extensions=_PDF,
        heavy=True,
        phase=1,
        title="Puente Tabular Tipado (Extraer)",
    ),
    "table_bridge_apply": OperationSpec(
        name="table_bridge_apply",
        handler_ref="engines.vectors_and_tables:handle_table_bridge_apply",
        allowed_extensions=_PDF | frozenset({".xlsx", ".json"}),
        min_files=2,
        heavy=True,
        phase=1,
        title="Puente Tabular Bidireccional (Aplicar)",
    ),
    "semantic_replace": OperationSpec(
        name="semantic_replace",
        handler_ref="engines.vectors_and_tables:handle_semantic_replace",
        allowed_extensions=_PDF,
        bulk=True,
        phase=1,
        title="Reemplazo Masivo Semantico y Divisas",
    ),
    # Fase 2: Lotes, Academia y CV Fotometrica
    "pipeline_run": OperationSpec(
        name="pipeline_run",
        handler_ref="engines.batch_and_templates:handle_pipeline_run",
        allowed_extensions=_PDF,
        bulk=True,
        heavy=True,
        preserve_zip_paths=True,
        phase=2,
        title="Pipeline Batch Sin Codigo",
    ),
    "template_detect": OperationSpec(
        name="template_detect",
        handler_ref="engines.batch_and_templates:handle_template_detect",
        allowed_extensions=_PDF,
        phase=2,
        title="Plantilla Inversa Viva (Detectar)",
    ),
    "template_compile": OperationSpec(
        name="template_compile",
        handler_ref="engines.batch_and_templates:handle_template_compile",
        allowed_extensions=_PDF | frozenset({".csv", ".json"}),
        min_files=2,
        heavy=True,
        phase=2,
        title="Plantilla Inversa Viva (Compilar Lote)",
    ),
    "compare_semantic": OperationSpec(
        name="compare_semantic",
        handler_ref="engines.batch_and_templates:handle_compare_semantic",
        allowed_extensions=_PDF,
        min_files=2,
        heavy=True,
        phase=2,
        title="Comparador Semantico y Migracion de Notas",
    ),
    "research_link": OperationSpec(
        name="research_link",
        handler_ref="engines.batch_and_templates:handle_research_link",
        allowed_extensions=_PDF | frozenset({".bib"}),
        bulk=True,
        heavy=True,
        phase=2,
        title="Enlazador Academico BibTeX/DOI",
    ),
    "scan_enhance_3d": OperationSpec(
        name="scan_enhance_3d",
        handler_ref="engines.vision_ocr:handle_scan_enhance_3d",
        allowed_extensions=_PDF_OR_IMG,
        heavy=True,
        phase=2,
        title="De-warping 3D Fotometrico y MRC",
    ),
    "scan_to_office": OperationSpec(
        name="scan_to_office",
        handler_ref="engines.scan_office_bridge:handle_scan_to_office",
        allowed_extensions=_PDF_OR_IMG,
        heavy=True,
        phase=2,
        title="PDF Escaneado a Office Editable (OCR + Vectores)",
    ),
    # Fase 3: Tipografia Profunda, Accesibilidad e IA Modular
    "edit_reflow": OperationSpec(
        name="edit_reflow",
        handler_ref="engines.typography_and_layout:handle_edit_reflow",
        allowed_extensions=_PDF,
        heavy=True,
        phase=3,
        title="Motor de Reflujo Inteligente",
    ),
    "liquid_compile": OperationSpec(
        name="liquid_compile",
        handler_ref="engines.typography_and_layout:handle_liquid_compile",
        allowed_extensions=_PDF | frozenset({".json"}),
        phase=3,
        title="Compilador Adaptativo Liquid PDF",
    ),
    "font_reconstruct": OperationSpec(
        name="font_reconstruct",
        handler_ref="engines.typography_and_layout:handle_font_reconstruct",
        allowed_extensions=_PDF,
        phase=3,
        title="Reconstructor de Fuentes y Diacriticos",
    ),
    "latex_ocr": OperationSpec(
        name="latex_ocr",
        handler_ref="engines.typography_and_layout:handle_latex_ocr",
        allowed_extensions=_PDF | frozenset({".png", ".jpg", ".jpeg", ".webp"}),
        heavy=True,
        ai_heavy=True,
        phase=3,
        title="Ecuaciones a LaTeX Vectorial",
    ),
    "accessibility_tagger": OperationSpec(
        name="accessibility_tagger",
        handler_ref="engines.typography_and_layout:handle_accessibility_tagger",
        allowed_extensions=_PDF,
        heavy=True,
        phase=3,
        title="Normalizador WCAG / PDF-UA y Audio-Tags",
    ),
    "translate_layout": OperationSpec(
        name="translate_layout",
        handler_ref="engines.typography_and_layout:handle_translate_layout",
        allowed_extensions=_PDF,
        heavy=True,
        ai_heavy=True,
        phase=3,
        title="Traductor Vectorial In-Situ",
    ),
    # Fase 4: Orquestacion Agentica, Criptografia Multicapa y Canvas
    "copilot_plan": OperationSpec(
        name="copilot_plan",
        handler_ref="engines.security_vault:handle_copilot_plan",
        allowed_extensions=_PDF,
        heavy=True,
        ai_heavy=True,
        phase=4,
        title="Co-Piloto Agentico (Plan y Vista Previa)",
    ),
    "copilot_apply": OperationSpec(
        name="copilot_apply",
        handler_ref="engines.security_vault:handle_copilot_apply",
        allowed_extensions=_PDF,
        heavy=True,
        phase=4,
        title="Co-Piloto Agentico (Ejecucion Aprobada)",
    ),
    "forensic_audit": OperationSpec(
        name="forensic_audit",
        handler_ref="engines.forensics:handle_forensic_audit",
        allowed_extensions=_PDF | frozenset({".txt"}),
        bulk=True,
        heavy=True,
        phase=4,
        title="Auditor de Custodia, Estilometria y Corpus",
    ),
    "crypto_container_pack": OperationSpec(
        name="crypto_container_pack",
        handler_ref="engines.security_vault:handle_crypto_pack",
        allowed_extensions=_PDF,
        heavy=True,
        phase=4,
        title="Cripto-Contenedor Multi-Rol (.evacrypt / ZIP)",
    ),
    "crypto_container_unlock": OperationSpec(
        name="crypto_container_unlock",
        handler_ref="engines.security_vault:handle_crypto_unlock",
        allowed_extensions=frozenset({".evacrypt"}),
        phase=4,
        title="Descifrar Contenedor Multi-Rol (.evacrypt)",
    ),
    "canvas_extract_sync": OperationSpec(
        name="canvas_extract_sync",
        handler_ref="engines.batch_and_templates:handle_canvas_sync",
        allowed_extensions=_PDF,
        phase=4,
        title="Sincronizador de Extractos Canvas Infinito",
    ),
}

HEAVY_V2_OPERATIONS = frozenset(name for name, spec in V2_SPECS.items() if spec.heavy)
AI_HEAVY_OPERATIONS = frozenset(name for name, spec in V2_SPECS.items() if spec.ai_heavy)
BULK_V2_OPERATIONS = frozenset(name for name, spec in V2_SPECS.items() if spec.bulk)
PRESERVE_PIPELINE_ZIP_OPERATIONS = frozenset(
    name for name, spec in V2_SPECS.items() if spec.preserve_zip_paths
)


def v2_operation_spec(operation: str) -> OperationSpec | None:
    return V2_SPECS.get(operation)


def allowed_upload_suffixes(operation: str) -> frozenset[str]:
    spec = V2_SPECS.get(operation)
    if spec is not None:
        return spec.allowed_extensions
    return LEGACY_ALL_UPLOAD_TYPES


def dispatch_v2(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    spec = V2_SPECS[operation]
    module_name, func_name = spec.handler_ref.split(":", 1)
    module = importlib.import_module(module_name)
    handler = getattr(module, func_name)
    return handler(operation, sources, options, folder, config, root)


def public_v2_catalog() -> list[dict]:
    return [
        {
            "id": spec.name,
            "title": spec.title,
            "phase": spec.phase,
            "bulk": spec.bulk,
            "heavy": spec.heavy,
            "ai_heavy": spec.ai_heavy,
            "extensions": sorted(spec.allowed_extensions),
            "min_files": spec.min_files,
        }
        for spec in V2_SPECS.values()
    ]
