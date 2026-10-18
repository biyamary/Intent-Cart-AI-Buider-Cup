# Gemini through Vertex AI

IntentCart supports the Gemini Developer API (API key) and Vertex AI (Application
Default Credentials, or ADC). The setting applies to both ADK agents and the
Gemini diagnostic script.

## Local authentication

Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install), then
follow Google's [local ADC instructions](https://cloud.google.com/docs/authentication/set-up-adc-local-dev-environment):

```powershell
gcloud auth application-default login --project=shopping-assistant-512002
gcloud auth application-default set-quota-project shopping-assistant-512002
```

Complete the browser sign-in with an account that can use this project. ADC is
stored in your user profile, outside the repository. Leave
`GOOGLE_APPLICATION_CREDENTIALS` unset when using this local user login, because
that variable overrides the ADC file. `gcloud auth login` alone does not create ADC.
If Google reports that the `cloud-platform` scope was not consented, repeat the
login and select the Google Cloud access permission on the browser consent screen.

The project needs billing enabled, the Vertex AI API (`aiplatform.googleapis.com`)
enabled, and the signed-in account needs Vertex AI access (typically
`roles/aiplatform.user`) plus `serviceusage.services.use` for the quota project
(included in `roles/serviceusage.serviceUsageConsumer`). If the API is disabled,
an authorized project administrator can enable it:

```powershell
gcloud auth login
gcloud services enable aiplatform.googleapis.com --project=shopping-assistant-512002
```

For the portable CLI installed in this workspace, run from the repository root:

```powershell
$gcloud = Join-Path (Get-Location) '.cache/google-cloud/google-cloud-sdk/bin/gcloud.cmd'
& $gcloud auth application-default login --project=shopping-assistant-512002
& $gcloud auth application-default set-quota-project shopping-assistant-512002
```

## Backend settings

In `backend/.env`:

```dotenv
AGENT_MODE=gemini
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=shopping-assistant-512002
GOOGLE_CLOUD_LOCATION=global
GEMINI_MODEL=gemini-3.5-flash
GEMINI_LITE_MODEL=gemini-3.5-flash
```

These model IDs match this workspace's configured models. Verify availability
for your project; choose explicit IDs from the
[Vertex AI model catalog](https://cloud.google.com/vertex-ai/generative-ai/docs/learn/models).
`global` is the default endpoint. Select a supported regional endpoint if required
by your application's data-location requirements.

`GOOGLE_API_KEY` is not required in Vertex AI mode. Authentication for the app's
users (`AUTH_MODE`) and its data store (`STORE_BACKEND`) are independent settings.
Keep their existing values if you only want to change the model backend.

Restart the API after changing `.env`. From `backend/`, verify one small synthetic
generation request using the configured provider:

```powershell
uv run python -m scripts.diagnose_gemini
# If GEMINI_LITE_MODEL differs:
uv run python -m scripts.diagnose_gemini --lite
# Optional: verify Google Search grounding before enabling it:
uv run python -m scripts.diagnose_gemini --search
# Optional: two-turn ADK conversation:
uv run python -m scripts.smoke_stylist
```

These live checks can incur normal model charges. They use synthetic prompts.
`scripts/check_google_key.py` remains a Gemini Developer API key checker; use
`scripts.diagnose_gemini` for Vertex AI.

For missing or expired credentials, repeat the ADC login. For HTTP 403, check
the enabled API, project access and billing. For HTTP 404, check model ID and
location. For HTTP 429, review the project's Vertex AI quotas and capacity in
Google Cloud Console.
