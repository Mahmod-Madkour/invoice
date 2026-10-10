# Fallback: deploying on Google Cloud Run

Use this only if the Oracle setup ([DEPLOY_ORACLE.md](DEPLOY_ORACLE.md)) is not possible. Cloud Run
runs the same Docker image without a server to manage, and gives you a free HTTPS address like
`https://invoice-abc123-uc.a.run.app`. Caddy and DuckDNS are not needed.

> ## ⚠️ Read this first: Cloud Run can cost money
>
> Cloud Run has a monthly **free allowance**, but using it **requires a billing account with a card
> (a "Paid" account)**. Anything above the free allowance is **charged to that card** — there is no
> automatic stop. The settings below (one instance at most, small memory, billing only while a request
> runs) keep a small app far inside the free allowance, but you are responsible for watching it.
>
> Always create a **budget alert** (step 2). **A budget only sends e-mails — it does not cap spending.**

---

## 1. Prepare Google Cloud

1. Create an account and a project at <https://console.cloud.google.com> and attach a billing account
   (Billing → Link a billing account).
2. Install the Google Cloud CLI (`gcloud`): <https://cloud.google.com/sdk/docs/install>. Then, in a
   terminal:

   ```bash
   gcloud init                                   # log in and pick the project
   gcloud config set project YOUR_PROJECT_ID
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
   ```

3. Pick a region close to your users, e.g. `europe-west1`, `me-central1` or `us-central1`.
   Prices differ slightly by region; check the Cloud Run pricing page for the current free allowance.

## 2. Create a budget alert (do not skip)

Console → **Billing → Budgets & alerts → Create budget**: scope = this project, amount = e.g. **1 USD**
(or your local equivalent), alert thresholds at 50 %, 90 % and 100 %, e-mail to you. Remember: this
warns you, it does not stop anything.

## 3. Deploy

Run this **in the project folder** on your computer. Option A builds the image on Google's servers
from the source (simplest); option B builds it locally.

### Option A — deploy from source (recommended)

```bash
gcloud run deploy invoice \
  --source . \
  --region YOUR_REGION \
  --allow-unauthenticated \
  --max-instances 1 \
  --memory 512Mi \
  --cpu 1 \
  --set-env-vars MAX_CONCURRENT_RENDERS=1
```

(PowerShell: put the whole command on one line, or replace each trailing `\` with a backtick `` ` ``.)

Google Cloud Build builds the image from the `Dockerfile` (an amd64 image, which is what Cloud Run
runs). Files listed in `.gitignore` — including your `.env` and `samples/` — are not uploaded.
When it finishes, it prints the **Service URL**.

### Option B — build an amd64 image yourself and push it

```bash
gcloud artifacts repositories create invoice --repository-format=docker --location=YOUR_REGION
gcloud auth configure-docker YOUR_REGION-docker.pkg.dev

docker build --platform linux/amd64 --target prod \
  -t YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/invoice/invoice-app:1 .
docker push YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/invoice/invoice-app:1

gcloud run deploy invoice \
  --image YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/invoice/invoice-app:1 \
  --region YOUR_REGION --allow-unauthenticated \
  --max-instances 1 --memory 512Mi --cpu 1 \
  --set-env-vars MAX_CONCURRENT_RENDERS=1
```

### What the settings mean

| Setting | Why |
|---|---|
| `--max-instances 1` | Never more than one copy running — caps cost and keeps the in-memory limits meaningful. |
| `--memory 512Mi`, `--cpu 1` | Small and cheap. A 1000-item PDF needs about 280 MB. |
| `MAX_CONCURRENT_RENDERS=1` | One PDF at a time, so two large invoices never exceed 512 MiB together. |
| Request-based billing | The default: you pay (from the free allowance) only while a request is running. **Do not** switch on "instance-based billing" / "CPU always allocated" (`--no-cpu-throttling`). |
| Port | Cloud Run sets the `PORT` variable (8080) and the container listens on it automatically. |
| HTTPS | The `*.run.app` URL already has a valid certificate. |

Other settings from [.env.example](../.env.example) can be added the same way, e.g.
`--set-env-vars MAX_CONCURRENT_RENDERS=1,APP_PASSWORD=something-long`.

## 4. Verify

Open the Service URL, add a few items, click **إنشاء PDF** — the PDF downloads. The very first request
after a quiet period takes a few extra seconds (Cloud Run starts the container on demand).

## 5. Update, logs, removal

```bash
# Update: run the same deploy command again (Option A or B).

# Logs (one line per request, never invoice contents)
gcloud run services logs read invoice --region YOUR_REGION --limit 50

# Remove the service
gcloud run services delete invoice --region YOUR_REGION
```

Each deployment stores an image in **Artifact Registry** (repository `cloud-run-source-deploy` for
option A, `invoice` for option B). Storage above the small free amount is billed, so delete old images
from time to time: Console → **Artifact Registry** → repository → select old images → **Delete**.

## Differences from the Oracle setup

- **No Caddy in front.** The app itself enforces the 256 KB body limit, the item limit, the render
  limit and the security headers. Google adds HTTPS.
- **The per-IP rate limit is weaker.** Cloud Run passes the visitor's address in the
  `X-Forwarded-For` header, but keeps any value the visitor sent in front of it, and the app (with
  `FORWARDED_ALLOW_IPS=*`) reads the first entry. A visitor who deliberately fakes that header can get
  around the 10-PDFs-per-minute limit. The other limits — one instance, one render at a time, 256 KB
  and 1000 items per request — still cap how much work and cost anyone can cause. If this matters,
  prefer the Oracle + Caddy setup, where the header cannot be faked.
- The service scales to zero when idle, so there is nothing to keep "busy" (no idle reclamation).
