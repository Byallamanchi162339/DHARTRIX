# DHARTRIX AI — Smart Agriculture Prototype

A no-drone agricultural dashboard with crop-photo intake, weather/forecast, place search, field records, soil/input history, organic-practice guidance, sensor-installation requests, farmer knowledge sharing, an AI assistant integration, and QpiAI Opt/QCloud lab panel.

## Run locally on Windows

Open this folder in VS Code, then use PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000. Use `python -m pip` if Windows blocks direct `pip.exe` invocation. Full instructions and API key setup are in `docs/SETUP_AND_KEYS.md`.

## Features

- Farmer account register/login (local SQLite; prototype security only).
- Profile asks for name, email, optional phone, state, district, village/area, language, experience level, and optional sensor interest. Subscription/payment is skippable; no payment is taken.
- Live Open-Meteo current weather and 7-day forecast using GPS or searched places, with basic weather-risk heuristics. Open-Meteo does not need a key here.
- Crop image preview plus CSV disease-reference search. **No trained image classifier is included**, so no diagnosis is invented.
- Soil test and prior input history (nutrients/fertilizers/pesticides/organic input, quantity and dates).
- General beginner-friendly organic farming and compost steps with safety limitations.
- Sensor-installation request form; not a confirmed booking or payment integration.
- Farmer practice posts with typing and optional browser speech recognition.
- AI assistant: uses a configured OpenAI API key for live model responses; otherwise clearly labels its cautious rule-based fallback. Browser speech recognition and speech synthesis depend on browser/language support.
- QpiAI Opt local QUBO formulation and status; remote submission remains gated until a docs-verified payload is configured.
- Optional QpiAI Quantum Cloud GHZ SDK smoke test, not an agricultural quantum algorithm.

## Important limits

The app is a hackathon prototype, not a validated agronomy/diagnostic service. Field, nutrient, booking, and community records are local browser storage and do not sync between devices. Auth records are local SQLite and need security hardening before production. Email/SMS/WhatsApp alert preferences are stored but message delivery is not connected. The disease CSV tool searches text rows only; it does not detect disease from image pixels. GPS and weather require permission/network. Weather thresholds are not official cyclone warnings; follow IMD/local authorities. Sensor data cannot establish borewell suitability or groundwater depth without appropriate instrumentation and professional hydrogeological assessment.

## API routes

- `GET /api/health`
- `GET /api/weather?latitude=13.08&longitude=77.60`
- `GET /api/places?q=Yelahanka`
- `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout`
- `POST /api/assistant/chat`
- `GET /api/qpiai/opt/status`, `POST /api/qpiai/opt/qubo`, `POST /api/qpiai/opt/submit`
- `GET /api/qpiai/cloud/status`, `POST /api/qpiai/cloud/smoke-test`

## Bundled crop-health dataset and enhancement layer

The file `data/DHARTRIX_India_1000_Crop_Health_Records.csv` is bundled with the project. It is searched through `GET /api/crop-health?crop=Rice&q=blast`; the frontend Disease Detection page includes a search form for it. No user-side CSV upload is required. The records are reference/demo data and are not independently field-validated diagnoses or approved chemical application rates.

Additional interface updates in this build:
- Weather backend requests up to 15 forecast days and includes daily maximum wind/gust fields when supported by the weather provider.
- Added local Farmer Profile and Farmer Recommendations pages.
- Added a light/dark appearance preference.
- Removed the API configuration guide panel from Settings.
- Expanded common crop and soil-type choices in Soil Analysis.

Prototype limits remain: place lookup requires internet access and can be rate-limited by the geocoding provider; complete village boundaries/listing for every Indian district is not bundled. Weather forecasts are not official cyclone warnings—check IMD/local authorities. Farmer recommendations currently search practices saved in the same browser, not a shared multi-user cloud database. Full page-by-page translation and a trained image classifier are not included; AI-generated answers in a selected language require a configured AI service, and crop-health dataset results are reference records only. QpiAI remote optimization/quantum execution should be considered active only when credentials are configured and successful provider responses are returned.

## Additional non-QpiAI updates (October 2026)
- Sensor installation form now uses state selection, attempts district loading from the bundled external district-list source when online, supports village/locality entry, and captures browser GPS with permission.
- Weather search can disambiguate a place using village/locality + district + state and reports location lookup failures with actionable guidance. Forecast UI requests up to 15 days with daily rainfall probability/amount, wind and gust data from Open-Meteo.
- Irrigation inputs use farmer-friendly wording.
- Organic guidance adds crop-group checklists for common Indian crops while avoiding invented chemical/fertilizer dosage. Use soil tests and local extension/product-label guidance for exact quantities.
- Registration language is persisted locally for subsequent sessions. Existing UI translations cover navigation and selected common labels; they do not constitute a complete translation of every page.
- The existing bundled crop-health dataset search, profile, recommendations page and theme settings are retained.

Limitations: village and district lookup requires internet access and provider availability; the list source is not an official exhaustive census directory. Weather forecast data are not official cyclone warnings; follow IMD/local authority alerts. Farmer recommendations are local-browser records unless a shared backend is deployed. QpiAI files and functionality were intentionally left unchanged in this update.


## Additional non-QpiAI refinements
- Place lookup retries broader query forms when detailed village/district/state searches return no results.
- Sensor booking offers online locality suggestions while typing; manual entry and GPS remain available.
- Weather page links to official IMD severe-weather/cyclone bulletins. Open-Meteo's 15-day forecast is not an official warning.
- QpiAI files and integration were not intentionally modified in this update.

## Important prototype limits
- Geographic search requires internet and OpenStreetMap Nominatim; it is not a complete offline list of every Indian village.
- Farmer recommendations saved in browser storage are local to that browser unless a shared database is deployed.
- Full translation of every page and all scheduled-language options is not complete; existing interface translations apply only where provided.
- Image uploads do not diagnose disease without a validated image model. Dataset results are reference records, not confirmed diagnoses.


## Latest requested non-QpiAI updates
- Farmer Knowledge Exchange now posts to a SQLite-backed `/api/farmer-practices` endpoint, and Farmer Recommendations searches the shared backend records (shared for users connecting to this same server/database).
- The cyclone checker no longer reports a false “no warning” when only landing pages were checked; if it cannot verify a location-specific active warning, it says so and links official IMD sources.
- Place lookup uses online geocoding and retries broader queries; this is not an exhaustive offline census of all villages.
- Translation coverage remains limited to the interface dictionary entries that exist; a complete reliable translation of every page requires a full reviewed translation catalog or an explicitly configured translation service.
- Official location-specific cyclone warnings require an authoritative alert feed; this build does not claim to have one.


## Login with email/mobile and forgot password
- Login accepts either the registered email address or registered mobile number, plus the password.
- Registration now asks for a mobile number so phone-number login and recovery can work.
- Forgot Password creates a one-time 6-digit reset code that expires after 10 minutes; reset codes are single-use and existing sessions are revoked after a password reset.
- **Local prototype limitation:** no email/SMS provider is configured. The reset code is printed in the backend terminal (the PowerShell window running Uvicorn). Do not deploy this reset flow publicly until you connect a verified email/SMS provider and remove terminal-code delivery.


## Password reset email setup
See `docs/SETUP_AND_KEYS.md` → **Password reset email (Gmail SMTP)**. Real email delivery requires your own SMTP credentials in a local `.env` file. The app never includes email credentials in frontend code.


## Location, soil types, and bundled crop-health reference updates
- Added a shared state/district/village selector that can be applied to weather and field forms.
- Added a GPS detection button in the top bar. Browsers require user permission; GPS is not silently guaranteed. Reverse-geocoded place names depend on the online geocoding service.
- Weather page district and village suggestions now use the selected state/district context. Place suggestions are internet-backed and may not contain every village in India.
- Standardized soil-type choices across Soil Analysis, Dashboard/Field Management, and Organic Farming.
- Removed the disease-reference CSV upload UI. The crop-health CSV is bundled in `data/` and queried through `/api/crop-health`.
- Leaf-image upload performs a crop-specific bundled-reference lookup, but it does **not** diagnose the image. A validated image-classification model is still required for actual disease prediction.


### Multilingual interface
The language selector translates the supported common interface labels into Hindi, Kannada, Telugu, Tamil, Malayalam, Marathi, Bengali, Gujarati, Punjabi, Odia and Urdu. The selected interface language is saved in this browser. Some long guidance, disease-reference records, live API messages, and dynamic server responses may remain in English unless the backend/provider returns a translation. The farmer assistant sends the selected language to the backend where supported.


## Facility dispatch terminal logs

The QpiAI Lab page includes a Facility Dispatch demo button. It calls `POST /api/qubo/dispatch`, which prints request/constraint/result logs to the backend terminal. The included dispatch example uses a local classical exhaustive search and is clearly labelled as such; it does not claim a remote QpiAI quantum solve. To verify the endpoint independently, open `/docs` while the backend is running and use `POST /api/qubo/dispatch`.


District dropdown fix: Indian district lists now include a bundled local fallback for common state/UT selections, so state-to-district selection does not depend on the geocoding service. Village suggestions still use online place search and require internet access.
