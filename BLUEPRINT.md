🌟 Blueprint definitiva — “STIGA Product Finder”
1. Obiettivo & Scope

Goal: consigliare prodotti di “Taglio dell’erba” in base alle esigenze reali dell’utente.

Sottocategorie attuali: robot tagliaerba, tagliaerba, trattorini frontali, trattorini da giardino, trattorini assiali, tagliaerba elicoidali.

Lingue: Italiano + Inglese.

Ambiente: ChatKit embedded su staging Framer con backend su IntentifAI.

2. Dati & Schema prodotto

Fonte dati: scraping della categoria “Taglio dell’erba” → JSON normalizzato.

Campi principali:

{
  "id": "stiga-a-1500",
  "name": "STIGA A 1500",
  "category": "robot",
  "pdp_url": "https://www.stiga.com/it/2r7102028-st1-stiga-a-1500.html",
  "image_url": "https://.../a1500.jpg",
  "price_eur": 1899,
  "coverage_m2": 1500,
  "max_slope_pct": 45,
  "perimeter_type": "virtual|wire|both",
  "battery": { "type": "Li-ion", "capacity_ah": 5.0, "voltage_v": 25.2 },
  "powertrain": { "motor": "brushless", "power_kw": 1.2 },
  "cutting": {
    "width_cm": 18,
    "height_min_mm": 20,
    "height_max_mm": 60,
    "height_adjust": "electronic|manual",
    "blade_type": "pivoting_4",
    "organized_cut": true
  },
  "zones": { "managed": 2, "virtual_exclusion": true },
  "runtime_per_cycle_min": 40,
  "charging": { "auto": true, "short_path": true },
  "sensors": { "rain": true, "lift": true, "obstacle": true, "tilt": true },
  "sound": { "lwa_guaranteed_db": 59, "lwa_measured_db": 57 },
  "features": ["app","gps","rtk","antitheft","epower"],
  "wireless": true,
  "power_source": "battery|wire|gasoline"
}

3. UX di raccolta esigenze — adattivo
Core (sempre)

Area prato (m²)

Tipo di perimetro (virtuale / filo / nessuna preferenza)

Pendenza massima (%)

Follow-up dinamici (max 3 se necessario)

Budget indicativo

Rumorosità desiderata

Multi-zona

Alimentazione/potenza (batteria / filo / benzina)

Feature extra (RTK, antitheft, app, gps, epower)

Regole

Se l’utente fornisce già tutto → salta le domande.

Dopo le 3 core, se risultati troppo ampi o scarsi → chiedi fino a 3 follow-up.

Domande max totali: 6.

Bilingue: IT default, EN se input in inglese.

4. Matching & Scoring
Filtri duri

coverage_m2 >= area

max_slope_pct >= pendenza

se perimetro = virtuale → perimeter_type ∈ {virtual,both}

se alimentazione dichiarata → power_source combacia (battery/wire/gasoline)

Punteggio 0–100

Copertura 0–35

Pendenza 0–15

Budget 0–15

Rumore 0–15

Multi-zona 0–5

Alimentazione coerente +5

Feature extra fino a 10 (1 punto a feature max 10)

Bonus +5 se wireless richiesto e disponibile

Fallback:

se 0 match → suggerisci rilassare vincoli (budget +15% → ignora rumorosità → perimetro both).

5. Card Template definitivo
{
  "title": "STIGA A 1500",
  "subtitle": "Perfetto per giardini fino a 1500 m² con pendenza 45%",
  "image_url": "https://.../a1500.jpg",
  "price": { "label": "1899 €", "note": "Prezzo indicativo" },
  "specs": [
    { "label_it": "Copertura", "label_en": "Coverage", "value": "1500 m²" },
    { "label_it": "Pendenza max", "label_en": "Max slope", "value": "45%" },
    { "label_it": "Perimetro", "label_en": "Perimeter", "value": "Virtuale" },
    { "label_it": "Rumorosità", "label_en": "Noise", "value": "57 dB(A)" },
    { "label_it": "Larghezza taglio", "label_en": "Cutting width", "value": "18 cm" },
    { "label_it": "Alimentazione", "label_en": "Power source", "value": "Batteria" },
    { "label_it": "Autonomia per ciclo", "label_en": "Runtime per cycle", "value": "40 min" }
  ],
  "pros": ["Motore brushless silenzioso","Gestione multi-zona","Controllo da app con RTK"],
  "cons": ["Prezzo superiore alla media","Richiede settaggio iniziale"],
  "score": 92.5,
  "links": {
    "pdp": { "label_it": "Vedi scheda prodotto", "label_en": "View product page", "url": "https://..." },
    "compare": { "label_it": "Confronta", "label_en": "Compare", "action": "add_to_compare" },
    "lead": { "label_it": "Richiedi consulenza", "label_en": "Request consultation", "action": "open_lead_form" }
  }
}


Card list (Top 5): immagine 3:2, titolo, 3 specs chiave, badge punteggio, CTA “PDP/Confronta”.

Vista confronto: tabella con tutte le specs principali + prezzo.

6. API search_products

GET /products/search

Query: surface_m2, slope_pct, perimeter, budget_band, noise_pref, multizone, power_source, features, limit

Output: come sopra.

7. Prompt agente (IT / EN)

Sei il consulente STIGA per il taglio dell’erba. Raccogli fino a 6 info (core: area, perimetro, pendenza; follow-up se servono: budget, rumorosità, multi-zona, alimentazione, feature extra).
Chiama search_products.
Mostra Top 5 in card con: immagine, prezzo, specs, motivazione, pro/contro, link PDP.
Offri confronto modelli.
Se zero match → chiedi di rilassare vincoli.
CTA finali: “Prenota consulenza”, “Richiedi preventivo”.
Bilingue, tono tecnico ma semplice.

8. Lead & Privacy

Form: nome, email, telefono obbligatori + consenso marketing opzionale.

Endpoint: POST /leads.

GDPR note con link informativa.

9. Branding & Embed

ChatKit con colori STIGA (giallo/nero/bianco), logo.

Framer staging.

Dominio whitelist + CORS sicuro.

10. Telemetria

Log: query, filtri usati, click PDP, uso confronto, lead.

KPI: CTR PDP, % comparatore, tasso lead.

Monitoraggio qualità con grading settimanale.

11. Edge cases

Area troppo piccola o enorme → messaggio dedicato.

Pendenza >60% → avviso limiti.

Prezzo mancante → mostra “Prezzo indicativo”.

Catalogo vuoto → fallback e contatto assistenza.
