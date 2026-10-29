# DHARTRIX AI — local setup and API keys

## Run on Windows (PowerShell)

Open VS Code in the `dhartrix_fullstack` folder (the folder containing `requirements.txt`). If Windows Application Control blocks `pip.exe`, use Python's module entry point:

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn backend.main:app --reload
```

If `.venv` is already created in the parent folder, activate that environment and run `python -m pip install -r requirements.txt` from the project folder that contains `requirements.txt`.

Open `http://127.0.0.1:8000`; API health is `http://127.0.0.1:8000/api/health`; API docs are `http://127.0.0.1:8000/docs`.

## Configure keys safely

1. Copy `.env.example` to `.env` in the same folder as `requirements.txt`.
2. Open `.env` in VS Code. Put actual secrets after `=` with no quotes unless the provider specifically requires them.
3. Save and restart the backend. Never paste keys into frontend JavaScript, screenshots, or GitHub.
4. Verify `.gitignore` contains `.env`.

### Password reset email (Gmail SMTP)

Password reset emails are sent only after SMTP is configured. Without these settings, the local prototype prints the code in the backend terminal.

1. In your Google Account, enable 2-Step Verification. Create an **App Password** for this project if your account supports it. Do not use your normal Gmail password. Google may not offer App Passwords for some account types or security configurations.
2. Copy `.env.example` to `.env` in the `dhartrix_fullstack` folder (if you have not already done so).
3. Set these values in `.env` using your own details:

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-address@gmail.com
SMTP_PASSWORD=your-16-character-app-password
SMTP_FROM=your-address@gmail.com
SMTP_TIMEOUT_SECONDS=15
```

4. Save `.env`, stop the running server with `Ctrl+C`, then restart it:

```powershell
python -m uvicorn backend.main:app --reload
```

5. Request a reset using an account's registered email or mobile number. If a mobile number is entered, the code is sent to the email address registered on that farmer account. Check Inbox and Spam/Junk. The code expires in 10 minutes.
6. If sending fails, the backend terminal will show the SMTP error; verify the host, port, App Password and sender address. Do not share `.env` or commit it to GitHub.

This prototype does not send SMS. Before public deployment, add rate limiting, abuse protection, verified email ownership and production-grade monitoring.

### QpiAI Opt

Set `QPIAI_OPT_TOKEN=your_token_from_your_QpiAI_Opt_account`. The project checks whether a token exists. Remote submission intentionally remains gated until `QPIAI_OPT_CREATE_PAYLOAD_JSON` matches the exact current request schema in the official account/API docs. Do not guess a payload. A successful create response is not proof the solver completed; record job status and returned solution separately.

Official docs: https://opt-api-docs.qpiai.tech/docs/introduction/overview

### QpiAI Quantum Cloud

Set `QPIAI_QCLOUD_API_KEY=your_key_from_your_QCloud_account`, then install the optional SDK:

```powershell
python -m pip install -r requirements-qpiai.txt
```

The GHZ smoke test is an SDK/connectivity check, not a plant-disease model or agricultural quantum advantage demonstration. It may use account resources/credits; check your account before running it.

Official docs: https://docs.qcloud.qpiai.tech/

### Live AI assistant

Set `OPENAI_API_KEY=your_API_key` and optionally `OPENAI_MODEL=gpt-4.1-mini`. Restart the backend. The server sends farmer questions to the configured model. API usage is separate from a ChatGPT subscription and may incur charges. Do not expose the key to the browser. Without the key, the app clearly labels the response as a rule-based fallback rather than live AI.

### Weather and climate

Current weather and 7-day forecast use Open-Meteo and do not require a key for this prototype. GPS requires browser permission and works on localhost or HTTPS. Weather is forecast-grid data, not a field sensor reading. The threshold alerts are simple advisory heuristics, not official cyclone alerts. Follow IMD and local emergency authorities.

## Feature status and limitations

- Account register/login: local SQLite database, password hashing, session token. Prototype only; add HTTPS, rate limits, account recovery, CSRF/session hardening, database backups and security review before production.
- Farm fields, nutrient logs, bookings, community practices and preferences: stored in the browser's localStorage in this prototype. They are not synced between devices or protected as server-side records. Do not store sensitive personal data there.
- Email/SMS/WhatsApp alerts: preferences are saved only; message delivery needs provider integration, credentials, consent and verified recipients.
- Disease CSV: reference lookup only. Uploaded CSV is processed in the browser and is not a trained image classifier.
- Organic guidance: general educational practices; verify rates and practices locally. It does not diagnose disease or prescribe pesticide doses.
- Sensor recommendations: surface soil-moisture sensors cannot map a whole farm or determine groundwater depth by themselves. Use multiple calibrated probes and professional hydrogeological assessment for borewell siting.
- Translation: the core navigation has starter translations for Hindi, Kannada, Telugu and Tamil. This is not a complete translation of every screen; unlisted languages/content may remain in English. Review translations with fluent speakers before deployment.
