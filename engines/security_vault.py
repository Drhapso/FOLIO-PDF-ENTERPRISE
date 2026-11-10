from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import shutil
import zipfile
from pathlib import Path

import pikepdf
import pymupdf as pdf
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from engines.addons import active_ai_target, call_ai_backend
from engines.forensics import handle_anti_track, handle_forensic_sanitize
from engines.vectors_and_tables import handle_semantic_replace
from pdf_engine import ProcessingError, open_pdf, pages_from, render, save


PBKDF2_ITERATIONS = 310_000


def _derive_aes256_key(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(password.encode("utf-8"))


def _compile_role_sanitized_pdf(
    src_pdf: Path,
    src_password: str,
    role_cfg: dict,
    work_dir: Path,
    config: dict,
    root: Path,
) -> bytes:
    role_name = str(role_cfg.get("role", "rol")).strip()
    patterns = role_cfg.get("redact_patterns") or []
    visible_pages_spec = str(role_cfg.get("visible_pages", "")).strip()
    wm_text = str(role_cfg.get("watermark", "")).strip()

    # 1. Seleccionar solo paginas autorizadas para este rol antes de sanear
    staged = work_dir / "role_pages.pdf"
    with open_pdf(src_pdf, src_password, config["max_pages"]) as doc:
        if visible_pages_spec:
            selected = pages_from(visible_pages_spec, len(doc))
            doc.select(selected)
        if wm_text:
            for pg in doc:
                pg.insert_textbox(
                    pdf.Rect(20, pg.rect.height / 2 - 25, pg.rect.width - 20, pg.rect.height / 2 + 45),
                    wm_text[:100], fontsize=22, color=(0.45, 0.45, 0.45), align=1, overlay=True, fill_opacity=0.3,
                )
        save(doc, staged, clean=True)

    # 2. Aplicar desinfeccion forense irreversible sobre patrones restringidos para este rol
    sanitized_res = handle_forensic_sanitize(
        "forensic_sanitize",
        [staged],
        {
            "redact_patterns": list(patterns),
            "purge_annotations": True,
            "purge_hidden_layers": True,
            "include_report": False,
        },
        work_dir,
        config,
        root,
    )
    sanitized_path = work_dir / sanitized_res["file"]
    return sanitized_path.read_bytes()


def handle_crypto_pack(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    source = sources[0]
    src_password = str(options.get("password", ""))
    mode = str(options.get("mode", "dual")).lower()
    if mode not in ("dual", "evacrypt", "role_zip"):
        raise ProcessingError("Modo de empaquetado criptografico no valido (use dual, evacrypt o role_zip).", 400)

    roles = options.get("roles")
    if not isinstance(roles, list) or not 1 <= len(roles) <= 10:
        raise ProcessingError("Configure entre 1 y 10 roles con clave propia.", 400)

    container_id = secrets.token_hex(12)
    seen_roles: set[str] = set()
    encrypted_slots: list[dict] = []
    role_pdfs: list[tuple[str, str, bytes]] = []  # (safe_role, role_pw, clean_pdf_bytes)

    for idx, r in enumerate(roles, 1):
        if not isinstance(r, dict):
            raise ProcessingError("Configuracion de rol no valida.", 400)
        raw_role = str(r.get("role", f"rol-{idx}")).strip()
        safe_role = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_role).strip("_") or f"rol_{idx}"
        if safe_role.lower() in seen_roles:
            raise ProcessingError(f"Nombre de rol duplicado: {safe_role}", 400)
        seen_roles.add(safe_role.lower())

        role_pw = str(r.get("password", ""))
        if len(role_pw) < 8:
            raise ProcessingError(f"La clave del rol '{safe_role}' debe tener al menos 8 caracteres.", 400)

        work_dir = folder / f"role-{idx:02d}"
        work_dir.mkdir(exist_ok=True)
        try:
            clean_pdf_bytes = _compile_role_sanitized_pdf(source, src_password, r, work_dir, config, root)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        role_pdfs.append((safe_role, role_pw, clean_pdf_bytes))

        if mode in ("dual", "evacrypt"):
            salt = secrets.token_bytes(16)
            iv = secrets.token_bytes(12)
            key = _derive_aes256_key(role_pw, salt, PBKDF2_ITERATIONS)
            aad = f"{container_id}:{safe_role}".encode("utf-8")
            ciphertext = AESGCM(key).encrypt(iv, clean_pdf_bytes, aad)
            encrypted_slots.append({
                "role": safe_role,
                "kdf": "PBKDF2-SHA256",
                "iterations": PBKDF2_ITERATIONS,
                "salt_b64": base64.b64encode(salt).decode("ascii"),
                "cipher": "AES-256-GCM",
                "iv_b64": base64.b64encode(iv).decode("ascii"),
                "aad": aad.decode("utf-8"),
                "redacted_patterns_count": len(r.get("redact_patterns") or []),
                "payload_sha256": hashlib.sha256(clean_pdf_bytes).hexdigest(),
                "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
            })

    evacrypt_doc = {
        "format": "EVA-CRYPT-V1",
        "container_id": container_id,
        "cipher": "PBKDF2-SHA256+AES-256-GCM",
        "roles": encrypted_slots,
    }

    if mode == "evacrypt":
        out_file = folder / "contenedor.evacrypt"
        out_file.write_text(json.dumps(evacrypt_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "file": out_file.name,
            "notice": f"Contenedor .evacrypt creado para {len(encrypted_slots)} roles con cifrado AEAD independiente.",
        }

    bundle = folder / ("roles_compilados.zip" if mode == "role_zip" else "cripto_dual_roles.zip")
    manifest_roles = []
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        if mode == "dual":
            archive.writestr("contenedor.evacrypt", json.dumps(evacrypt_doc, ensure_ascii=False, indent=2))
        for safe_role, role_pw, clean_bytes in role_pdfs:
            # Compilar PDF estandar protegido AES-256 por cada rol con texto ya purgado
            with pdf.open(stream=clean_bytes, filetype="pdf") as rdoc:
                enc_bytes = rdoc.tobytes(
                    garbage=4, deflate=True,
                    encryption=pdf.PDF_ENCRYPT_AES_256,
                    owner_pw=secrets.token_hex(16),
                    user_pw=role_pw,
                    permissions=pdf.PDF_PERM_PRINT | pdf.PDF_PERM_COPY,
                )
            pdf_name = f"rol-{safe_role}.pdf"
            archive.writestr(pdf_name, enc_bytes)
            manifest_roles.append({"role": safe_role, "pdf_file": pdf_name, "aes_256": True})
        archive.writestr(
            "MANIFIESTO_ROLES.json",
            json.dumps({"container_id": container_id, "mode": mode, "roles": manifest_roles}, ensure_ascii=False, indent=2),
        )

    return {
        "file": bundle.name,
        "notice": f"Cripto-contenedor ({mode}) generado para {len(role_pdfs)} roles independientes.",
    }


def handle_crypto_unlock(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    src = sources[0]
    role_pw = str(options.get("role_password") or options.get("password") or "")
    target_role = str(options.get("role", "")).strip()
    if not role_pw:
        raise ProcessingError("Introduzca la clave del rol para descifrar el contenedor.", 400)

    try:
        envelope = json.loads(src.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProcessingError("El archivo .evacrypt esta danado o no tiene formato valido.") from None

    if not isinstance(envelope, dict) or envelope.get("format") != "EVA-CRYPT-V1":
        raise ProcessingError("Formato .evacrypt incompatible.")
    slots = envelope.get("roles") or []
    candidates = [s for s in slots if not target_role or str(s.get("role", "")).lower() == target_role.lower()]
    if not candidates:
        raise ProcessingError("El rol especificado no existe en este contenedor.", 404)

    for slot in candidates:
        try:
            salt = base64.b64decode(slot["salt_b64"])
            iv = base64.b64decode(slot["iv_b64"])
            ct = base64.b64decode(slot["ciphertext_b64"])
            iters = int(slot.get("iterations", PBKDF2_ITERATIONS))
            aad = str(slot["aad"]).encode("utf-8")
            key = _derive_aes256_key(role_pw, salt, min(max(100_000, iters), 1_000_000))
            plain = AESGCM(key).decrypt(iv, ct, aad)
            with pdf.open(stream=plain, filetype="pdf") as check_doc:
                if not len(check_doc):
                    raise ProcessingError("Contenedor descifrado vacio.")
            safe_role = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(slot["role"])) or "rol"
            out_pdf = folder / f"desbloqueado_{safe_role}.pdf"
            out_pdf.write_bytes(plain)
            return {
                "file": out_pdf.name,
                "notice": f"Acceso concedido al rol '{safe_role}' (AES-256-GCM verificado).",
            }
        except (InvalidTag, KeyError, ValueError):
            continue

    raise ProcessingError("Clave o rol invalido para este cripto-contenedor.", 403)


ALLOWED_COPILOT_ACTIONS = frozenset({
    "redact_pattern",
    "replace_text",
    "watermark",
    "anti_track",
    "forensic_sanitize",
    "delete_pages",
    "number_pages",
})


def _deterministic_nl_plan(prompt: str, total_pages: int) -> list[dict]:
    low = prompt.lower()
    steps: list[dict] = []

    # Deteccion de censura / redaccion de entidades sensibles
    if any(k in low for k in ("censur", "redact", "oculta", "tacha", "pii")):
        patterns = []
        if any(k in low for k in ("correo", "email", "mail")):
            patterns.append(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        if any(k in low for k in ("dni", "cedul", "nif", "iban", "tarjeta", "ssn", "telefon")):
            patterns.append(r"\b(?:[A-Z]{2}\d{2}[A-Z0-9]{10,24}|\d{7,12}|\+?\d[\d -]{7,15}\d)\b")
        # Comillas explicitas despues de censurar / ocultar
        for quoted in re.findall(r'["\']([^"\']{2,120})["\']', prompt):
            patterns.append(re.escape(quoted))
        if not patterns:
            patterns.append(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        steps.append({"action": "redact_pattern", "patterns": patterns})

    # Reemplazo "reemplaza/cambia X por Y"
    rep_m = re.search(
        r"(?:reemplaza|cambia|replace)\s+[\"']?(.+?)[\"']?\s+(?:por|con|with|to)\s+[\"']?(.+?)[\"']?(?:\s+en\b|$|,|\.)",
        prompt,
        re.IGNORECASE,
    )
    if rep_m:
        steps.append({"action": "replace_text", "find": rep_m.group(1).strip(), "replace": rep_m.group(2).strip()})

    # Marca de agua
    wm_m = re.search(r"(?:marca de agua|watermark)\s+[\"']?([A-Za-z0-9ÁÉÍÓÚÑ _-]{2,60})[\"']?", prompt, re.IGNORECASE)
    if wm_m:
        steps.append({"action": "watermark", "text": wm_m.group(1).strip()})

    # Numeracion
    if any(k in low for k in ("enumera", "numera", "number pages")):
        steps.append({"action": "number_pages"})

    # Anti-tracking y desinfeccion
    if any(k in low for k in ("rastreo", "tracking", "anti-track", "enlaces utm", "javascript")):
        steps.append({"action": "anti_track"})
    if any(k in low for k in ("desinfecta", "metadatos", "limpia forense", "sanitize")):
        steps.append({"action": "forensic_sanitize"})

    # Eliminar paginas concretas
    del_m = re.search(r"(?:elimina|borra|delete)\s+(?:la[s]?\s+)?pagina[s]?\s+([\d,\-\s]+)", low)
    if del_m:
        pages_tok = re.sub(r"\s+", "", del_m.group(1)).strip(",")
        if pages_tok:
            steps.append({"action": "delete_pages", "pages": pages_tok})

    return steps


def handle_copilot_plan(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    source = sources[0]
    password = str(options.get("password", ""))
    instruction = str(options.get("prompt") or options.get("instruction") or "").strip()
    if not instruction or len(instruction) > 1500:
        raise ProcessingError("Escriba una instruccion clara de 1 a 1500 caracteres para el Co-Piloto.", 400)

    steps: list[dict] = []
    planner_source = "deterministic_parser"

    kind, _ = active_ai_target(config)
    if kind != "none":
        schema_prompt = (
            "Convierte la instruccion del usuario en un arreglo JSON estricto 'steps' usando SOLO acciones de: "
            "redact_pattern(patterns[]), replace_text(find, replace), watermark(text), anti_track, "
            "forensic_sanitize, delete_pages(pages), number_pages. Responde SOLO JSON valido."
        )
        ai_res = call_ai_backend(instruction, schema_prompt, config, timeout=15)
        if ai_res and ai_res.get("content"):
            try:
                raw_json = ai_res["content"].strip()
                m = re.search(r"\{.*\}", raw_json, re.DOTALL)
                parsed = json.loads(m.group(0) if m else raw_json)
                cand_steps = parsed.get("steps", [])
                if isinstance(cand_steps, list):
                    valid = [s for s in cand_steps if isinstance(s, dict) and s.get("action") in ALLOWED_COPILOT_ACTIONS]
                    if valid:
                        steps = valid
                        planner_source = f"slm_{ai_res['backend']}"
            except (json.JSONDecodeError, AttributeError):
                pass

    with open_pdf(source, password, config["max_pages"]) as doc:
        if not steps:
            steps = _deterministic_nl_plan(instruction, len(doc))
        if not steps:
            raise ProcessingError("No se pudo derivar un plan ejecutable de la instruccion. Sea mas especifico (ej. censurar correos, marca de agua...).", 422)

        # Generar vista previa sin mutar el documento real
        highlights: list[dict] = []
        preview_doc_bytes = None
        for st in steps:
            act = st["action"]
            if act == "redact_pattern":
                for pno, page in enumerate(doc):
                    for pat in st.get("patterns", []):
                        try:
                            rx = re.compile(str(pat))
                        except re.error:
                            continue
                        for block in page.get_text("dict").get("blocks", []):
                            if block.get("type") != 0:
                                continue
                            for line in block.get("lines", []):
                                for span in line.get("spans", []):
                                    if rx.search(span.get("text", "")):
                                        highlights.append({"page": pno + 1, "action": "redact", "bbox": list(span["bbox"]), "snippet": span["text"][:60]})
            elif act == "replace_text" and st.get("find"):
                for pno, page in enumerate(doc):
                    for rect in page.search_for(str(st["find"])):
                        highlights.append({"page": pno + 1, "action": "replace", "bbox": list(rect), "snippet": f"{st['find']} -> {st.get('replace', '')}"})

        # Renderizar hasta 2 miniaturas marcadas visualmente sobre una copia en memoria
        thumbs_b64: list[str] = []
        with pdf.open(stream=doc.tobytes(), filetype="pdf") as vis_doc:
            for hl in highlights[:120]:
                pg = vis_doc[hl["page"] - 1]
                r = pdf.Rect(hl["bbox"]) & pg.rect
                if not r.is_empty:
                    color = (0.85, 0.12, 0.12) if hl["action"] == "redact" else (0.12, 0.45, 0.85)
                    pg.draw_rect(r, color=color, width=1.6, dashes="[3 2]")
            for pg in vis_doc[:2]:
                pix = render(pg, 90, config)
                thumbs_b64.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))

    plan_payload = {
        "requires_approval": True,
        "approved": False,
        "mutated_source": False,
        "planner": planner_source,
        "instruction": instruction,
        "steps": steps,
        "target_highlights": highlights[:300],
        "preview_thumbnails_png_b64": thumbs_b64,
    }
    out_json = folder / "plan_copiloto.json"
    out_json.write_text(json.dumps(plan_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "file": out_json.name,
        "notice": f"Plan Co-Piloto generado ({planner_source}): {len(steps)} paso(s), {len(highlights)} objetivos detectados (sin mutacion).",
    }


def handle_copilot_apply(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    if options.get("approved") is not True:
        raise ProcessingError("El Co-Piloto exige confirmacion explicita ('approved: true') para modificar el PDF.", 400)
    plan = options.get("plan") or options.get("steps")
    steps = plan.get("steps") if isinstance(plan, dict) else plan
    if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        raise ProcessingError("Plan de Co-Piloto no valido o vacio.", 400)

    for st in steps:
        if not isinstance(st, dict) or st.get("action") not in ALLOWED_COPILOT_ACTIONS:
            raise ProcessingError(f"Accion no permitida en el sandbox del Co-Piloto: {st}", 400)

    password = str(options.get("password", ""))
    work_pdf = folder / "copiloto_work.pdf"
    shutil.copyfile(sources[0], work_pdf)
    applied_log: list[str] = []

    for idx, st in enumerate(steps, 1):
        act = st["action"]
        step_dir = folder / f"cop-step-{idx:02d}"
        step_dir.mkdir(exist_ok=True)
        try:
            if act == "redact_pattern":
                res = handle_forensic_sanitize(
                    "forensic_sanitize", [work_pdf],
                    {"password": password, "redact_patterns": st.get("patterns", []), "purge_annotations": False, "include_report": False},
                    step_dir, config, root,
                )
                shutil.move(step_dir / res["file"], work_pdf)
                password = ""
                applied_log.append("redact_pattern")
            elif act == "replace_text":
                res = handle_semantic_replace(
                    "semantic_replace", [work_pdf],
                    {"password": password, "find": st.get("find", ""), "replace": st.get("replace", "")},
                    step_dir, config, root,
                )
                shutil.move(step_dir / res["file"], work_pdf)
                applied_log.append("replace_text")
            elif act == "anti_track":
                res = handle_anti_track("anti_track", [work_pdf], {"password": password}, step_dir, config, root)
                shutil.move(step_dir / res["file"], work_pdf)
                applied_log.append("anti_track")
            elif act == "forensic_sanitize":
                res = handle_forensic_sanitize("forensic_sanitize", [work_pdf], {"password": password}, step_dir, config, root)
                shutil.move(step_dir / res["file"], work_pdf)
                password = ""
                applied_log.append("forensic_sanitize")
            elif act == "watermark":
                wtxt = str(st.get("text", "CONFIDENCIAL"))[:100]
                next_tmp = step_dir / "wm.pdf"
                with open_pdf(work_pdf, password, config["max_pages"]) as doc:
                    for pg in doc:
                        pg.insert_textbox(
                            pdf.Rect(20, pg.rect.height / 2 - 25, pg.rect.width - 20, pg.rect.height / 2 + 45),
                            wtxt, fontsize=22, color=(0.4, 0.4, 0.4), align=1, overlay=True, fill_opacity=0.35,
                        )
                    save(doc, next_tmp)
                shutil.move(next_tmp, work_pdf)
                applied_log.append("watermark")
            elif act in ("delete_pages", "number_pages"):
                from extended_tools import process_extended

                res = process_extended(act, [work_pdf], {"password": password, "pages": st.get("pages", "")}, step_dir, config)
                shutil.move(step_dir / res["file"], work_pdf)
                applied_log.append(act)
        finally:
            shutil.rmtree(step_dir, ignore_errors=True)

    out_pdf = folder / "copiloto_aplicado.pdf"
    work_pdf.replace(out_pdf)
    return {
        "file": out_pdf.name,
        "notice": f"Plan Co-Piloto ejecutado: {', '.join(applied_log)}.",
    }
