"""
Research masivo de prospects usando la API de Gemini (grounding con Google Search).
Version para correr dentro del Claude Routine: la API key viene de la variable
de entorno GEMINI_API_KEY, nunca hardcodeada.

Cuota gratis (Ago 2026): 5,000 grounding calls/mes en modelos Gemini 3.x,
con limite base de ~1,000 requests/dia y 5-15 requests por minuto.
300 prospects a 12 por minuto tardan ~25 minutos, muy dentro de cuota.

Uso:
  export GEMINI_API_KEY=xxxxx   (en el routine esto ya viene del ambiente)
  python research_prospects_gemini.py

Entrada:  prospects_input.csv con columnas name,company,linkedin_url
Salida:   research_output.jsonl (un JSON por linea, append-safe)
"""

import os
import time
import json
import csv
import requests

API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-2.5-flash"  # verificar nombre vigente; alternativa: gemini-2.5-flash
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"

PROMPT_TEMPLATE = """
Investiga a {name}, de la empresa {company} (LinkedIn: {linkedin_url}).

Busca informacion real y actual. NO inventes datos si no los encuentras;
la ausencia de datos es en si misma un hallazgo importante.

Recolecta especificamente:
1. ROL: es founder/CEO dueno, o empleado (ecosystem lead, BD, PM)?
2. DINERO: funding real (montos, inversionistas, fechas), pricing publico del
   producto, revenue/ARR declarado, clientes nombrados, anos operando la empresa,
   trayectoria profesional previa (empresas, seniority, exits).
3. SENALES DE ALERTA DE DINERO: inversionistas con nombre similar al founder,
   valuaciones desproporcionadas a la etapa, press releases en distribucion pagada
   (PRNewswire etc) sin prensa real, estimaciones automaticas de revenue.
4. CONTENIDO: seguidores del PERFIL PERSONAL (no de la pagina de empresa),
   cadencia de posts (fechas de los ultimos), calidad/temas del contenido,
   si tiene newsletter (donde vive, cuantos suscriptores, fecha de la ultima
   edicion publicada).
5. GATES DE PERFIL: es estudiante actual (graduacion futura)? Tiene otro empleo
   full-time en paralelo? La empresa fue fundada hace pocos meses? Dejo su empleo
   hace poco para fundar?
6. ACTIVOS ANCLABLES: posts especificos, articulos, paginas de producto, o datos
   concretos con URL que se puedan mostrar en pantalla en un video.

Responde SOLO con un JSON valido con estas claves:
- rol: string
- senal_dinero: string con toda la evidencia encontrada
- alertas_dinero: string (o "ninguna")
- seguidores_personales: string (numero o "no encontrado")
- cadencia_posts: string con fechas concretas
- newsletter: string (existe? donde? subs? ultima edicion?)
- gates_perfil: string con los gates detectados (o "ninguno")
- activos_anclables: lista de strings, cada uno con descripcion + URL
- resumen: string de 3-4 frases con lo mas relevante

No incluyas texto fuera del JSON.
"""


def research_prospect(name, company, linkedin_url):
    prompt = PROMPT_TEMPLATE.format(name=name, company=company, linkedin_url=linkedin_url)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
    }
    for attempt in range(2):
        try:
            r = requests.post(URL, json=payload, timeout=60)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            wait = 2 ** attempt
            print(f"  Rate limit, esperando {wait}s...")
            time.sleep(wait)
        else:
            return {"error": r.status_code, "detail": r.text[:300]}
    return {"error": "max_retries_exceeded"}


def extract_text(gemini_response):
    try:
        return gemini_response["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return None


def run_batch(input_csv="prospects_input.csv", output_jsonl="research_output.jsonl", requests_per_minute=12):
    if not API_KEY:
        raise SystemExit("Falta la variable de entorno GEMINI_API_KEY")
    delay = 60 / requests_per_minute
    processed = 0
    with open(input_csv, newline="", encoding="utf-8") as f_in, \
         open(output_jsonl, "a", encoding="utf-8") as f_out:
        reader = csv.DictReader(f_in)
        for row in reader:
            name = (row.get("name") or "").strip()
            company = (row.get("company") or "").strip()
            linkedin_url = (row.get("linkedin_url") or "").strip()
            if not name:
                continue

            raw = research_prospect(name, company, linkedin_url)
            text = extract_text(raw)

            record = {
                "name": name,
                "company": company,
                "linkedin_url": linkedin_url,
                "research_text": text,
                "error": raw.get("error") if isinstance(raw, dict) else None,
            }
            f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
            f_out.flush()

            processed += 1
            status = "OK" if text else f"ERROR ({record['error']})"
            print(f"[{processed}] {name} ({company}) -> {status}")

            time.sleep(delay)

    print(f"\nListo. {processed} prospects procesados en {output_jsonl}")


if __name__ == "__main__":
    run_batch()
