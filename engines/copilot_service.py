from __future__ import annotations

import io
import re
import math
from pathlib import Path
from typing import Any

import pymupdf as pdf

from engines.security_vault import _deterministic_nl_plan, ALLOWED_COPILOT_ACTIONS

TOOL_KNOWLEDGE = [
    {
        "id": "compress",
        "name": "Comprimir PDF",
        "icon": "↙",
        "category": "optimize",
        "keywords": ["comprim", "reduc", "tamaño", "peso", "optim", "mb", "kb", "espacio", "liger", "calidad"],
        "summary": "Reduce el peso del archivo mediante compresión no destructiva (Equilibrada, Baja o Alta) que optimiza imágenes y preserva texto, vectores y formularios.",
    },
    {
        "id": "stamp",
        "name": "Firma visual e imágenes",
        "icon": "✍",
        "category": "edit",
        "keywords": ["firm", "rúbric", "manuscrit", "estamp", "sello", "logo", "fondo blanco"],
        "summary": "Estampa tu firma manuscrita o imagen eliminando automáticamente el fondo blanco de papel para integrarse al documento.",
    },
    {
        "id": "compare",
        "name": "Comparar PDF",
        "icon": "≠",
        "category": "organize",
        "keywords": ["compar", "diferenc", "version", "cotej", "cambio", "modific", "diff"],
        "summary": "Coteja dos versiones de un PDF página a página generando un informe con mapas visuales de diferencias y cambios de texto.",
    },
    {
        "id": "redact",
        "name": "Censurar PDF",
        "icon": "■",
        "category": "edit",
        "keywords": ["censur", "tach", "ocult", "borrar texto", "dni", "correo", "datos personales", "pii", "confidencial"],
        "summary": "Elimina de forma irreversible texto, imágenes y vectores en zonas confidenciales sin dejar rastros en el archivo final.",
    },
    {
        "id": "edit",
        "name": "Editor Acrobat · Editar PDF",
        "icon": "✎",
        "category": "edit",
        "keywords": ["edit", "modific", "cambiar texto", "reemplaz", "correg", "anot", "fuente", "resalt"],
        "summary": "Abre el editor visual interactivo para cambiar texto in-situ, ajustar tipografías, resaltar o anotar directamente en la página.",
    },
    {
        "id": "merge",
        "name": "Unir PDF",
        "icon": "⊕",
        "category": "organize",
        "keywords": ["unir", "junt", "combin", "peg", "fusion", "mezcl"],
        "summary": "Combina múltiples archivos PDF en un único documento respetando el orden que definas.",
    },
    {
        "id": "split",
        "name": "Dividir PDF",
        "icon": "⊟",
        "category": "organize",
        "keywords": ["divid", "separ", "part", "cort", "extra", "rango", "grupo"],
        "summary": "Separa páginas individuales o divide tu PDF en rangos personalizados descargables en un archivo ZIP.",
    },
    {
        "id": "ocr",
        "name": "Reconocer texto · OCR",
        "icon": "A",
        "category": "optimize",
        "keywords": ["ocr", "reconocer", "escanear", "escaneo", "foto a texto", "buscar texto", "tesseract"],
        "summary": "Aplica reconocimiento óptico Tesseract 100% local sobre documentos escaneados para volverlos buscables y seleccionables.",
    },
    {
        "id": "pdf_to_docx",
        "name": "PDF a Word",
        "icon": "W",
        "category": "convert",
        "keywords": ["word", "docx", "doc", "editable", "convertir a word"],
        "summary": "Exporta el contenido a Microsoft Word (.docx) recuperando texto, estilos, tablas e imágenes estructuradas.",
    },
    {
        "id": "pdf_to_xlsx",
        "name": "PDF a Excel",
        "icon": "X",
        "category": "convert",
        "keywords": ["excel", "xlsx", "tabla", "hoja de cálculo", "datos", "números"],
        "summary": "Extrae tablas tabulares hacia hojas de cálculo Excel conservando celdas combinadas y formatos numéricos.",
    },
    {
        "id": "protect",
        "name": "Proteger PDF",
        "icon": "⌑",
        "category": "edit",
        "keywords": ["proteger", "cifrar", "contraseña", "clave", "seguridad", "bloquear", "aes"],
        "summary": "Cifra el PDF con contraseña de apertura bajo estándar militar AES-256 sin almacenar contraseñas.",
    },
    {
        "id": "unlock",
        "name": "Desbloquear PDF",
        "icon": "⌕",
        "category": "edit",
        "keywords": ["desbloquear", "quitar contraseña", "retirar clave", "sin clave"],
        "summary": "Elimina la contraseña de apertura de un PDF propio introduciendo la clave actual autorizada.",
    },
    {
        "id": "rotate",
        "name": "Rotar PDF",
        "icon": "↻",
        "category": "organize",
        "keywords": ["rotar", "girar", "voltear", "ángulo", "orientación", "vertical", "horizontal"],
        "summary": "Gira páginas 90°, 180° o 270° para poner cada hoja en la orientación correcta de lectura.",
    },
    {
        "id": "flatten",
        "name": "Aplanar PDF",
        "icon": "▰",
        "category": "edit",
        "keywords": ["aplanar", "flatten", "bake", "bloquear campos", "fijar formulario", "fijar firma"],
        "summary": "Consolida formularios, firmas y anotaciones en el contenido gráfico estático de la página para evitar manipulaciones.",
    },
    {
        "id": "anti_track",
        "name": "Purga Anti-Rastreo",
        "icon": "🛡",
        "category": "edit",
        "keywords": ["rastreo", "tracking", "utm", "javascript", "privacidad", "balizas", "anti-track"],
        "summary": "Elimina código JavaScript, acciones ocultas, píxeles de rastreo y parámetros UTM de los enlaces del PDF.",
    },
]


def match_tool_from_query(query: str) -> dict | None:
    low = query.lower()
    best_tool = None
    best_score = 0

    for t in TOOL_KNOWLEDGE:
        score = 0
        for kw in t["keywords"]:
            if kw in low:
                score += len(kw) * 2
        # Bonus for tool id or exact name match
        if t["id"] in low or t["name"].lower() in low:
            score += 15
        if score > best_score:
            best_score = score
            best_tool = t

    return best_tool if best_score >= 4 else None


def summarize_pdf_document(doc: pdf.Document, filename: str = "documento.pdf") -> dict:
    page_count = len(doc)
    meta = doc.metadata or {}
    title = meta.get("title") or filename
    author = meta.get("author") or ""
    
    pages_text = []
    total_words = 0
    for page in doc:
        txt = page.get_text()
        pages_text.append(txt)
        total_words += len(txt.split())
        
    is_scanned = total_words < 20 and page_count > 0
    toc = doc.get_toc()

    # Extract first significant paragraphs
    first_paragraphs = []
    for txt in pages_text[:3]:
        for p in txt.split("\n\n"):
            clean_p = " ".join(p.split()).strip()
            if len(clean_p) > 40 and not clean_p.startswith(("http", "www")):
                first_paragraphs.append(clean_p)
                if len(first_paragraphs) >= 3:
                    break
        if len(first_paragraphs) >= 3:
            break

    summary_text = ""
    if is_scanned:
        summary_text = (
            f"El documento '{title}' contiene {page_count} página(s), pero tiene muy poco o ningún texto digital seleccionable "
            f"(posible escaneo o imagen). Se recomienda ejecutar la herramienta 'Reconocer texto · OCR' para digitalizarlo."
        )
    else:
        sample = " ".join(first_paragraphs[:2])
        if len(sample) > 400:
            sample = sample[:397] + "..."
        summary_text = (
            f"El documento '{title}' contiene {page_count} página(s) y aproximadamente {total_words:,} palabras. "
            f"{'Extracto inicial: ' + chr(34) + sample + chr(34) if sample else ''}"
        )

    # Suggested actions
    suggested = []
    if is_scanned:
        suggested.append({"id": "ocr", "name": "Reconocer texto (OCR)", "icon": "A"})
    if page_count > 1:
        suggested.append({"id": "compress", "name": "Comprimir PDF", "icon": "↙"})
    suggested.append({"id": "edit", "name": "Abrir en Editor", "icon": "✎"})
    suggested.append({"id": "protect", "name": "Proteger con clave", "icon": "⌑"})

    return {
        "title": title,
        "author": author,
        "pages": page_count,
        "words": total_words,
        "is_scanned": is_scanned,
        "toc": toc[:10] if toc else [],
        "summary": summary_text,
        "suggested_tools": suggested,
    }


def search_in_pdf(doc: pdf.Document, query: str) -> list[dict]:
    keywords = [w.lower() for w in re.findall(r"[A-Za-z0-9ÁÉÍÓÚáéíóúñÑ]{3,}", query)]
    if not keywords:
        return []

    results = []
    for pno, page in enumerate(doc):
        text = page.get_text()
        if not text.strip():
            continue
        paragraphs = text.split("\n\n")
        for para in paragraphs:
            para_clean = " ".join(para.split()).strip()
            if len(para_clean) < 15:
                continue
            para_low = para_clean.lower()
            score = sum(3 for kw in keywords if kw in para_low)
            # Match whole phrase bonus
            if query.lower() in para_low:
                score += 15
            if score > 0:
                snippet = para_clean
                if len(snippet) > 280:
                    snippet = snippet[:277] + "..."
                results.append({
                    "page": pno + 1,
                    "score": score,
                    "snippet": snippet,
                })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:5]


def process_copilot_request(
    prompt: str,
    pdf_bytes: bytes | None = None,
    filename: str = "documento.pdf",
    config: dict | None = None,
) -> dict[str, Any]:
    prompt = (prompt or "").strip()
    low_prompt = prompt.lower()
    
    # Check if a plan is requested on an uploaded document
    if pdf_bytes:
        try:
            with pdf.open(stream=pdf_bytes, filetype="pdf") as doc:
                page_count = len(doc)
                
                # Check for action commands
                action_words = ("censur", "tacha", "marca de agua", "watermark", "elimina pagina", "reemplaza", "anti-track", "desinfecta")
                if any(w in low_prompt for w in action_words):
                    plan_steps = _deterministic_nl_plan(prompt, page_count)
                    if plan_steps:
                        return {
                            "type": "plan",
                            "prompt": prompt,
                            "reply": f"He analizado tu solicitud y generado un plan con {len(plan_steps)} paso(s) ejecutable(s) de forma segura:",
                            "steps": plan_steps,
                            "filename": filename,
                            "page_count": page_count,
                            "requires_approval": True,
                        }

                # Check if user asked to summarize
                if not prompt or any(w in low_prompt for w in ("resum", "resumen", "de qué trata", "analiza", "qué contiene", "informe")):
                    summary_data = summarize_pdf_document(doc, filename)
                    return {
                        "type": "summary",
                        "prompt": prompt or "Resumen del documento",
                        "reply": summary_data["summary"],
                        "data": summary_data,
                    }

                # Otherwise, treat as Q&A search query inside the document
                matches = search_in_pdf(doc, prompt)
                if matches:
                    return {
                        "type": "qa",
                        "prompt": prompt,
                        "reply": f"Encontré {len(matches)} fragmento(s) relevante(s) en tu documento para '{prompt}':",
                        "matches": matches,
                        "filename": filename,
                        "suggested_tool": {"id": "edit", "name": "Editor Acrobat", "icon": "✎"},
                    }
                else:
                    matched_tool = match_tool_from_query(prompt)
                    tool_resp = {
                        "type": "guidance",
                        "prompt": prompt,
                        "reply": f"No encontré coincidencias textuales directas en el PDF para '{prompt}'. Si buscas realizar una operación documental, te sugiero la siguiente herramienta:",
                        "recommended_tool": matched_tool or {"id": "edit", "name": "Editor Acrobat", "icon": "✎"},
                    }
                    return tool_resp
        except Exception as e:
            pass

    # No document provided or general tool inquiry
    matched_tool = match_tool_from_query(prompt)
    if matched_tool:
        return {
            "type": "tool_recommendation",
            "prompt": prompt,
            "reply": f"Para esta tarea te recomiendo usar **{matched_tool['name']}**. {matched_tool['summary']}",
            "recommended_tool": matched_tool,
        }

    return {
        "type": "general_help",
        "prompt": prompt,
        "reply": (
            "Soy el Copiloto Inteligente de EVA PDF Enterprise. Puedo ayudarte a encontrar la herramienta "
            "adecuada (comprimir, firmar, censurar, comparar, convertir a Word/Excel, OCR) o analizar un PDF que arrastres "
            "a esta sección para resumirlo, responder preguntas sobre su contenido o aplicar tareas automáticas."
        ),
        "chips": [
            "¿Cómo reduzco el tamaño de mi PDF?",
            "¿Cómo firmo un documento y quito el fondo?",
            "¿Cómo comparo dos versiones de un PDF?",
            "Censurar datos sensibles",
            "Convertir PDF a Word editable",
        ],
    }
