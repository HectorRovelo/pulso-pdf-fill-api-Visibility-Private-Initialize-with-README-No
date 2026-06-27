from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
GENERATED_DIR = Path(os.getenv("GENERATED_DIR", BASE_DIR / "generated"))
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

FORMAT_REGISTRY = {
    "axa_informe_medico_gmm_feb22": {
        "carrier": "AXA",
        "canonical_name": "AXA-Informe-Medico-GMM-FEB22",
        "template": TEMPLATE_DIR / "AXA-Informe-Medico-GMM-FEB22.pdf",
        "filler": "axa_informe_medico_gmm_feb22",
        "aliases": [
            "AXA-Informe-Medico-GMM-FEB22",
            "AXA - Informe Medico GMM FEB22",
            "AXA - Informe Médico GMM FEB22",
            "AXA Informe Medico GMM FEB22",
            "Informe medico AXA",
            "Informe médico AXA",
        ],
    },
}


class FillRequest(BaseModel):
    formato_pdf: str = Field(default="")
    raw_text: str = Field(default="")
    paciente: dict[str, Any] = Field(default_factory=dict)
    administrativo: dict[str, Any] = Field(default_factory=dict)
    clinico: dict[str, Any] = Field(default_factory=dict)
    medico: dict[str, Any] = Field(default_factory=dict)
    solicitud: dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title="Pulso AI PDF Fill API", version="1.0.0")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def all_formats() -> list[dict[str, Any]]:
    return [
        {
            "id": format_id,
            "carrier": info["carrier"],
            "canonical_name": info["canonical_name"],
            "implemented": Path(info["template"]).exists(),
            "aliases": info["aliases"],
        }
        for format_id, info in FORMAT_REGISTRY.items()
    ]


def requested_format_name(payload: "FillRequest") -> str:
    return (
        clean(payload.formato_pdf)
        or clean(payload.administrativo.get("formato_recomendado"))
        or clean(payload.administrativo.get("formatos_pendientes"))
    )


def resolve_format(format_name: str) -> tuple[str | None, dict[str, Any] | None]:
    normalized = normalize_key(format_name)
    for format_id, info in FORMAT_REGISTRY.items():
        candidates = [format_id, info["canonical_name"], *info["aliases"]]
        if normalized in {normalize_key(candidate) for candidate in candidates}:
            return format_id, info
    return None, None


def split_name(full_name: str) -> tuple[str, str, str]:
    parts = [p for p in clean(full_name).split() if p]
    if len(parts) >= 3:
        return parts[-2], parts[-1], " ".join(parts[:-2])
    if len(parts) == 2:
        return parts[1], "", parts[0]
    return "", "", clean(full_name)


def compact_date(value: str) -> str:
    value = clean(value)
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", value)
    if match:
        yyyy, mm, dd = match.groups()
        return f"{dd}{mm}{yyyy}"
    return value.replace("/", "").replace("-", "")


def short(value: str, length: int = 75) -> str:
    value = clean(value)
    return value if len(value) <= length else value[: length - 3].rstrip() + "..."


def first_value(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = clean(data.get(key))
        if value:
            return value
    return ""


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", clean(value))


def raw_request_text(data: FillRequest) -> str:
    return normalize_spaces(
        clean(data.raw_text)
        or clean(data.solicitud.get("texto_original"))
        or clean(data.clinico.get("observaciones"))
    )


def match_group(pattern: str, text: str, group: int = 1) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return normalize_spaces(match.group(group)) if match else ""


def text_after_label(text: str, labels: str, stop_labels: str) -> str:
    pattern = rf"(?:{labels})\s*:?\s*(.+?)(?=\s+(?:{stop_labels})\s*:|\s*$)"
    return match_group(pattern, text)


def format_talla(value: str) -> str:
    value = clean(value).replace(",", ".")
    if not value:
        return ""
    try:
        number = float(value)
    except ValueError:
        return value
    if number > 10:
        number = number / 100
    return f"{number:.2f} m"


def extracted_from_raw_text(text: str) -> dict[str, dict[str, str]]:
    if not text:
        return {"paciente": {}, "clinico": {}, "medico": {}}

    stop = (
        "peso|talla|estatura|tension arterial|tensión arterial|presion arterial|"
        "presión arterial|diagnostico actual|diagnóstico actual|fecha de diagnostico|"
        "fecha de diagnóstico|exploracion fisica|exploración física|medico|médico|"
        "dr|dra|cedula|cédula|telefono|teléfono"
    )

    paciente = {
        "peso": match_group(r"\b(?:peso|pesa)\s*:?\s*(\d{2,3}(?:[\.,]\d+)?)\s*(?:kg|kilos?)?\b", text),
        "talla": format_talla(
            match_group(r"\b(?:talla|estatura|mide)\s*:?\s*(\d(?:[\.,]\d{1,2})|\d{2,3})\s*(?:m|mts|metros|cm)?\b", text)
        ),
        "tension_arterial": match_group(
            r"\b(?:tension arterial|tensión arterial|presion arterial|presión arterial|TA)\s*:?\s*(\d{2,3}\s*/\s*\d{2,3})(?:\s*mmhg)?\b",
            text,
        ),
    }

    clinico = {
        "diagnostico": text_after_label(text, "diagnostico actual|diagnóstico actual|diagnostico|diagnóstico", stop),
        "fecha_diagnostico": match_group(
            r"(?:fecha de diagnostico|fecha de diagnóstico)\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})",
            text,
        ),
        "exploracion_fisica": text_after_label(text, "exploracion fisica|exploración física", stop),
    }

    medico_text = match_group(
        r"(?:medico|médico)\s*:?\s*((?:dr\.?|dra\.?)?\s*[^,;]+?)(?=,\s*c[eé]dula|,\s*tel[eé]fono|;|$)",
        text,
    )
    if not medico_text:
        medico_text = match_group(r"\b((?:dr\.?|dra\.?)\s+[A-ZÁÉÍÓÚÑ][^,;]+)", text)
    medico_text = re.sub(r"^(?:dr\.?|dra\.?)\s+", "", medico_text, flags=re.IGNORECASE)
    medico = {
        "nombre": medico_text,
        "cedula_profesional": match_group(r"c[eé]dula profesional\s*:?\s*(\d+)", text),
        "cedula_especialidad": match_group(r"c[eé]dula (?:de )?especialidad\s*:?\s*(\d+)", text),
        "telefono": match_group(r"(?:tel[eé]fono medico|tel[eé]fono del medico|tel[eé]fono)\s*:?\s*(\+?\d[\d\s]{7,})", text),
    }

    return {"paciente": paciente, "clinico": clinico, "medico": medico}


def apply_raw_extractions(data: FillRequest) -> None:
    extracted = extracted_from_raw_text(raw_request_text(data))
    for section_name, values in extracted.items():
        section = getattr(data, section_name)
        for key, value in values.items():
            if value and not clean(section.get(key)):
                section[key] = value


def build_axa_values(data: FillRequest) -> dict[str, str]:
    paciente = data.paciente
    clinico = data.clinico
    administrativo = data.administrativo
    medico = data.medico

    apellido_paterno, apellido_materno, nombres = split_name(clean(paciente.get("nombre")))
    diagnostico = clean(clinico.get("diagnostico"))
    antecedentes = clean(clinico.get("antecedentes"))
    sintomas = clean(clinico.get("sintomas_actuales"))
    plan = clean(clinico.get("plan"))
    estudios = clean(clinico.get("estudios"))
    medicamentos = clean(clinico.get("medicamentos"))
    alergias = clean(clinico.get("alergias"))
    observaciones = clean(clinico.get("observaciones"))

    padecimiento = "\n".join(
        part
        for part in [
            f"Antecedentes: {antecedentes}" if antecedentes else "",
            f"Sintomas actuales: {sintomas}" if sintomas else "",
            f"Alergias: {alergias}" if alergias else "",
            f"Observaciones: {observaciones}" if observaciones else "",
        ]
        if part
    )

    estudios_texto = "\n".join(
        part
        for part in [
            estudios,
            f"Tramite solicitado: {clean(administrativo.get('tramite'))}",
            f"Poliza: {clean(administrativo.get('poliza'))}",
            f"Aseguradora: {clean(administrativo.get('aseguradora'))}",
        ]
        if part and not part.endswith(": ")
    )

    return {
        "Lugar": clean(administrativo.get("lugar")) or "Tuxtla Gutierrez, Chiapas",
        "Información general": clean(administrativo.get("fecha")) or time.strftime("%Y-%m-%d"),
        "Apellido paterno": apellido_paterno,
        "Apellido materno": apellido_materno,
        "Nombres": nombres,
        "Edad": clean(paciente.get("edad")),
        "Día": compact_date(clean(paciente.get("fecha_nacimiento"))),
        "Talla": clean(paciente.get("talla")),
        "Peso": clean(paciente.get("peso")),
        "Tensión arterial": clean(paciente.get("tension_arterial")),
        "NoRow1": "1" if diagnostico else "",
        "DiagnósticoRow1": short(diagnostico),
        "Fecha de diagnóstico ddmmaaaaRow1": clean(clinico.get("fecha_diagnostico")),
        "Tratamiento recibidoRow1": clean(clinico.get("tratamiento_recibido")) or "En estudio",
        "Padecimiento actual principales signos síntomas y detalles de evolución": padecimiento,
        "Tiempo de evolución_3": clean(clinico.get("tiempo_evolucion")),
        "Causa o etiología del padecimiento en caso de accidente describa tiempo modo y lugar donde ocurrió la lesión": clean(clinico.get("etiologia")) or "En estudio.",
        "Diagnóstico indicando si es unilateral o bilateral derecho o izquierdo": diagnostico,
        "Código ICD": clean(clinico.get("codigo_icd")),
        "Estadificación TNM": clean(clinico.get("estadificacion_tnm")),
        "Señale los datos relevantes de exploración física": first_value(
            clinico,
            "exploracion_fisica",
            "exploración_fisica",
        ),
        "Describa los estudios de laboratorio yo gabinete que realizaron para confirmar el diagnóstico con su interpretación": estudios_texto,
        "Tratamiento propuesto quirúrgico no quirúrgico": plan,
        "Detalle de evolución": clean(clinico.get("detalle_evolucion")) or observaciones,
        "Si tiene alguna observación adicional favor de agregarla aquí": observaciones,
        "Técnica detallada explique  en qué consiste la cirugía planeada": clean(clinico.get("tecnica_detallada")),
        "Tiempo esperado de hospitalización de acuerdo con el procedimiento programado": clean(clinico.get("tiempo_hospitalizacion")),
        "Tipo de participación": clean(medico.get("tipo_participacion")) or "Medico tratante",
        "Nombre": clean(medico.get("nombre")),
        "Especialidad": clean(medico.get("especialidad")) or "Coloproctologia",
        "Cédula profesional": clean(medico.get("cedula_profesional")),
        "Cédula de especialidad": clean(medico.get("cedula_especialidad")),
        "Teléfono": clean(medico.get("telefono")),
        "Lugar y fechaRow1": clean(administrativo.get("lugar_fecha")) or f"Tuxtla Gutierrez, Chiapas, {time.strftime('%Y-%m-%d')}",
    }


def reset_and_mark_page1_checkboxes(writer: PdfWriter) -> None:
    page1 = writer.pages[0]
    annots_obj = page1.get("/Annots") or []
    annots = annots_obj.get_object() if hasattr(annots_obj, "get_object") else annots_obj
    for annot_ref in annots:
        annot = annot_ref.get_object()
        if annot.get("/T") is not None:
            continue
        ap = annot.get("/AP")
        if ap and ap.get("/N"):
            annot[NameObject("/AS")] = NameObject("/Off")

    def set_checkbox(index: int, state: str) -> None:
        if index < len(annots):
            annots[index].get_object()[NameObject("/AS")] = NameObject(state)

    set_checkbox(7, "/S")   # Masculino
    set_checkbox(12, "/E")  # Enfermedad
    set_checkbox(19, "/C")  # Consultorio
    set_checkbox(78, "/n")  # Referido: No


def fill_pdf(template: Path, output: Path, values: dict[str, str]) -> None:
    reader = PdfReader(str(template))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    if writer._root_object.get("/AcroForm"):
        writer._root_object["/AcroForm"].update(
            {NameObject("/NeedAppearances"): BooleanObject(True)}
        )

    for page in writer.pages:
        writer.update_page_form_field_values(page, values, auto_regenerate=False)

    reset_and_mark_page1_checkboxes(writer)

    with output.open("wb") as fh:
        writer.write(fh)


def public_base_url(request: Request) -> str:
    configured = os.getenv("PUBLIC_BASE_URL")
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/formats")
def formats() -> dict[str, Any]:
    return {"formats": all_formats()}


@app.post("/fill-pdf")
def fill_pdf_endpoint(payload: FillRequest, request: Request) -> dict[str, Any]:
    apply_raw_extractions(payload)
    requested_format = requested_format_name(payload)
    format_id, format_info = resolve_format(requested_format)
    if not format_info:
        supported = [fmt["canonical_name"] for fmt in all_formats()]
        return {
            "ok": False,
            "status": "unsupported_format",
            "formato_pdf": requested_format,
            "pdf_url": "",
            "whatsapp_text": (
                "No pude generar el PDF porque este formato de aseguradora aun no "
                f"esta configurado: {requested_format or 'sin formato especificado'}. "
                f"Formatos disponibles: {', '.join(supported)}."
            ),
            "supported_formats": supported,
        }

    template = Path(format_info["template"])
    if not template.exists():
        return {
            "ok": False,
            "status": "missing_template",
            "formato_pdf": format_info["canonical_name"],
            "pdf_url": "",
            "whatsapp_text": (
                "No pude generar el PDF porque falta subir la plantilla oficial "
                f"del formato {format_info['canonical_name']}."
            ),
        }

    values = build_axa_values(payload)
    fingerprint = hashlib.sha1(
        json.dumps(payload.model_dump(), sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]
    paciente_id = clean(payload.paciente.get("paciente_id")) or "SIN_ID"
    safe_patient = re.sub(r"[^A-Za-z0-9_-]+", "_", paciente_id)
    safe_format = re.sub(r"[^A-Za-z0-9_-]+", "_", format_info["canonical_name"])
    filename = f"{safe_patient}_{fingerprint}_{safe_format}.pdf"
    output = GENERATED_DIR / filename

    fill_pdf(template, output, values)

    base_url = public_base_url(request)
    return {
        "ok": True,
        "status": "generated",
        "formato_pdf": format_info["canonical_name"],
        "carrier": format_info["carrier"],
        "filename": filename,
        "pdf_url": f"{base_url}/files/{filename}",
        "whatsapp_text": (
            f"Formato generado: {format_info['canonical_name']}\n"
            f"Paciente: {clean(payload.paciente.get('nombre')) or clean(payload.paciente.get('paciente_id'))}\n"
            f"PDF: {base_url}/files/{filename}\n\n"
            "Pendiente de firma del medico y del asegurado si aplica."
        ),
        "missing_for_signature": [
            "firma del medico",
            "firma del asegurado",
        ],
    }


@app.get("/files/{filename}")
def get_file(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    path = GENERATED_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=safe_name,
    )
