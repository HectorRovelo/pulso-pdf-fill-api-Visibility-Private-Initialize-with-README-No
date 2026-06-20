# Pulso AI PDF Fill API

Servicio publico para que Make llame un endpoint y genere PDFs de aseguradora.

## Endpoints

### Health

```http
GET /health
```

Respuesta:

```json
{"status":"ok"}
```

### Llenar PDF

```http
POST /fill-pdf
Content-Type: application/json
```

Body esperado:

```json
{
  "formato_pdf": "AXA-Informe-Medico-GMM-FEB22",
  "paciente": {
    "paciente_id": "CP-0001",
    "nombre": "Carlos Mendoza Ruiz",
    "edad": "58",
    "fecha_nacimiento": "1968-02-14",
    "sexo": "Masculino",
    "telefono": "+5219611126128"
  },
  "administrativo": {
    "aseguradora": "AXA",
    "poliza": "GMM-CP0001-8452",
    "vigencia": "2026-12-31",
    "tramite": "Preautorizacion colonoscopia con biopsia",
    "formato_recomendado": "AXA - Informe Medico GMM FEB22",
    "estado_pago": "Pendiente de autorizacion con AXA"
  },
  "clinico": {
    "diagnostico": "Sospecha de lesion rectal/rectosigmoidea",
    "antecedentes": "HTA controlada; estrenimiento intermitente.",
    "sintomas_actuales": "Rectorragia, tenesmo y perdida de peso.",
    "estudios": "Colonoscopia completa prioritaria con biopsia.",
    "plan": "Colonoscopia completa con toma de biopsias.",
    "medicamentos": "Losartan 50 mg cada 24 h.",
    "alergias": "Niega alergias medicamentosas conocidas.",
    "observaciones": "Solicitud para preautorizacion de procedimiento."
  },
  "medico": {
    "nombre": "",
    "especialidad": "Coloproctologia",
    "cedula_profesional": "",
    "cedula_especialidad": "",
    "telefono": ""
  }
}
```

Respuesta:

```json
{
  "ok": true,
  "status": "generated",
  "formato_pdf": "AXA-Informe-Medico-GMM-FEB22",
  "carrier": "AXA",
  "filename": "CP-0001_xxxxx_AXA_Informe_Medico_GMM_FEB22.pdf",
  "pdf_url": "https://TU-SERVICIO/files/CP-0001_xxxxx_AXA_Informe_Medico_GMM_FEB22.pdf",
  "whatsapp_text": "Formato generado: AXA-Informe-Medico-GMM-FEB22\nPaciente: Carlos Mendoza Ruiz\nPDF: https://TU-SERVICIO/files/CP-0001_xxxxx_AXA_Informe_Medico_GMM_FEB22.pdf\n\nPendiente de firma del medico y del asegurado si aplica.",
  "missing_for_signature": [
    "firma del medico",
    "firma del asegurado"
  ]
}
```

Si el formato aun no esta configurado, el servicio no truena Make. Responde:

```json
{
  "ok": false,
  "status": "unsupported_format",
  "formato_pdf": "MetLife - Formato X",
  "pdf_url": "",
  "whatsapp_text": "No pude generar el PDF porque este formato de aseguradora aun no esta configurado..."
}
```

### Catalogo de formatos

```http
GET /formats
```

Devuelve los formatos ya soportados por el servicio.

## Despliegue en Render

1. Subir este repositorio o esta carpeta a GitHub.
2. Crear un nuevo Web Service en Render.
3. Root directory: `services/pdf_fill_api`
4. Environment: Docker.
5. Agregar variable de entorno:

```text
PUBLIC_BASE_URL=https://TU-SERVICIO.onrender.com
```

6. Deploy.
7. Probar:

```text
https://TU-SERVICIO.onrender.com/health
```

## Configuracion en Make

En el modulo HTTP despues de `JSON Create JSON`:

- Method: `POST`
- URL: `https://TU-SERVICIO.onrender.com/fill-pdf`
- Body content type: `application/json`
- Body: salida `JSON string` del modulo JSON anterior.

Despues de este HTTP, el WhatsApp debe enviar el campo:

```text
HTTP fill-pdf -> whatsapp_text
```

Asi Make no cambia cuando se agreguen nuevas aseguradoras. Si el PDF se genero, `whatsapp_text` incluye el link; si falta una plantilla, explica que formato falta.

## Agregar otro seguro sin tocar Make

1. Subir el PDF oficial a `services/pdf_fill_api/templates/`.
2. Agregar una entrada en `FORMAT_REGISTRY` dentro de `app.py`.
3. Crear o ajustar la funcion de mapeo de campos si el PDF usa campos distintos.
4. Desplegar de nuevo el servicio.

Make sigue mandando el mismo JSON al mismo endpoint `/fill-pdf`.
