# Company Document Chatbot MVP

Production-oriented FastAPI chatbot using PostgreSQL/pgvector retrieval with switchable offline mock, OpenAI, and Amazon Bedrock providers. Mock mode is the default and makes no external AI calls. Documents and application history stay in PostgreSQL. Provider, embedding model, and dimensions are recorded for every document so vectors from different embedding spaces are never searched together.

## Local setup (Windows PowerShell)

Prerequisites: Python 3.12 and Docker Desktop.

```powershell
Copy-Item .env.example .env
# Keep AI_PROVIDER_MODE=mock and OPENAI_API_KEY empty; set a random ADMIN_API_KEY (24+ characters)
$env:POSTGRES_PASSWORD = "choose-a-local-password"
# Use the same password in DATABASE_URL if running Python outside Docker.
docker compose up -d db
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
alembic upgrade head
pytest
uvicorn app.main:app --reload
```

Open http://localhost:8000. API documentation is at http://localhost:8000/api/docs.
The visually separate document dashboard is at http://localhost:8000/admin. Sign in with `ADMIN_API_KEY`; the key is exchanged for a signed, HttpOnly, same-site session and is not stored in page HTML, JavaScript, browser storage, logs, or URLs.

## Browser voice support

The chat UI supports optional, browser-only voice input and playback at no API cost. Click the microphone to start speech recognition, choose English (India) or Hindi (India), review the recognized text in the input, and send it normally. Use the speaker beside an assistant response to read it aloud; voice, language, speed, and stop controls are above the composer.

- Voice input requires the Web Speech Recognition API (`SpeechRecognition` or `webkitSpeechRecognition`). Chromium-based browsers generally provide the best support; availability varies by browser and operating system.
- Response playback requires the Web Speech/SpeechSynthesis API. Available voices come from the browser or operating system, so an exact `en-IN` or `hi-IN` voice may not always be installed.
- Microphone access requires a secure context (`https://`) or `http://localhost` and is requested only after clicking the microphone button.
- Audio is never uploaded to this application backend. Web Speech Recognition is browser-managed and, depending on the browser, the browser vendor may process speech remotely under its own terms.
- If an API is unsupported or microphone permission is denied, the UI shows a notice and text chat remains fully usable.

To run everything in containers, set `DATABASE_URL` in `.env` to the `db` hostname shown in `.env.example`, then:

```powershell
docker compose up --build
```

## API examples

```powershell
curl.exe http://localhost:8000/health
curl.exe http://localhost:8000/ready
curl.exe -X POST http://localhost:8000/api/admin/documents -H "X-Admin-API-Key: YOUR_ADMIN_KEY" -F "file=@.\company-faq.txt;type=text/plain"
curl.exe http://localhost:8000/api/admin/documents -H "X-Admin-API-Key: YOUR_ADMIN_KEY"
curl.exe -X POST http://localhost:8000/api/admin/documents/DOCUMENT_UUID/reindex -H "X-Admin-API-Key: YOUR_ADMIN_KEY"
curl.exe -X POST http://localhost:8000/api/admin/documents/reindex-incompatible -H "X-Admin-API-Key: YOUR_ADMIN_KEY"
curl.exe -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" -d '{"message":"What services do you provide?"}'
curl.exe -X POST http://localhost:8000/api/leads -H "Content-Type: application/json" -d '{"name":"Alex","company":"Example Ltd","email":"alex@example.com","phone":"+91 9876543210","requirement":"Please contact me about implementation."}'
```

### Careers applications

The public careers form submits candidates to `POST /api/careers/applications` as multipart form data. It accepts PDF or DOCX resumes up to `MAX_RESUME_MB` (5 MB by default), creates an `ITS-CAR-...` reference, and always stores the initial status as `new_hr_review`. The service does not automatically shortlist or reject candidates.

Set the optional SMTP variables in `.env.example` to notify `HR_NOTIFICATION_EMAIL` and attach the submitted resume. If SMTP is not configured, the application is still saved in PostgreSQL.

For the ITSIPL WordPress Careers page, copy `wordpress/itsipl-careers-chatbot.html` into a Custom HTML block. The `?mode=careers` parameter opens the HR form automatically and displays the recruitment-routing notice.

## Configuration

`AI_PROVIDER_MODE` accepts `mock` (default), `openai`, or `bedrock`. Mock mode uses deterministic local embeddings and returns a clearly labelled sample answer composed from retrieved document excerpts; it needs no AI key and makes no external AI calls. Selecting OpenAI or Bedrock without its required configuration returns a safe readiness/service error without stopping the application.

Required: `DATABASE_URL` and `ADMIN_API_KEY` (24+ characters). `OPENAI_API_KEY` is required only in OpenAI mode. The verified Bedrock configuration is Region `ap-south-1`, Nova Micro APAC inference profile `apac.amazon.nova-micro-v1:0`, Titan Text Embeddings V2 `amazon.titan-embed-text-v2:0`, and 1024 dimensions. In `ap-south-1`, use the APAC inference profile ID for Nova Micro rather than the foundation-model ID. Guardrail ID and version are optional and must be supplied together. OpenAI continues to use `OPENAI_MODEL` and `EMBEDDING_MODEL`; `text-embedding-3-small` calls explicitly request 1024 dimensions. Mock, OpenAI, and Bedrock embeddings are all standardized to 1024 dimensions.

The database uses `vector(1024)` and records provider, model, and dimensions independently. Changing the active provider or embedding model makes prior documents incompatible by design. They remain stored and visible as `requires_reindex`, but retrieval excludes them until explicitly reindexed.

## Mock to Amazon Bedrock migration

Do not enable Bedrock or add credentials until the company AWS/DevOps team has approved both the exact model IDs and AWS Region and granted model access.

1. Deploy migration `0002_embedding_compatibility` with `alembic upgrade head`. It preserves all original uploads and extracted chunk text, clears only incompatible 1536-dimensional vectors, changes the column to `vector(1024)`, recreates HNSW, and marks legacy documents `requires_reindex`.
2. Have AWS/DevOps confirm the approved Region and model access: `ap-south-1`, the APAC Nova Micro inference profile `apac.amazon.nova-micro-v1:0`, and `amazon.titan-embed-text-v2:0` at 1024 dimensions.
3. Give the workload IAM role least-privilege access to the approved model resources. The application uses boto3's default credential chain and supports ECS, EKS, EC2, and other workload IAM roles. Never put static AWS credentials in `.env`.
4. Keep guardrail values blank unless an approved guardrail is available, then set `AI_PROVIDER_MODE=bedrock` and restart. No permanent AWS credential variables are needed; an ECS deployment should use its Task IAM Role.
5. Check `/ready` and the safe status at `/admin`. No connectivity test or model invocation is performed merely by loading status.
6. From `/admin`, reindex one document first and verify chat results, then choose **Reindex incompatible**. Reindexing generates the complete replacement before changing rows and commits atomically. On failure, the original document and working vectors are preserved; retrying is safe.

For local development, boto3 may use temporary credentials created by an approved AWS browser-login flow. Keep those credentials in the standard local AWS credential chain; never copy them into `.env`, source files, container images, or commits. Production ECS tasks must use an ECS Task IAM Role. Do not mount a developer's local `.aws` directory into a production container.

Required IAM actions on only the approved Bedrock model resources:

- `bedrock:InvokeModel`
- `bedrock:InvokeModelWithResponseStream`

The current chat path uses the Bedrock Converse API without streaming, but `InvokeModelWithResponseStream` is documented for an approved future streaming rollout. Model IDs and AWS Region must be approved by the company's AWS/DevOps team.

Example IAM statement for the approved `ap-south-1` foundation models:

```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream"
  ],
  "Resource": [
    "arn:aws:bedrock:ap-south-1::foundation-model/amazon.nova-micro-v1:0",
    "arn:aws:bedrock:ap-south-1::foundation-model/amazon.titan-embed-text-v2:0"
  ]
}
```

## AWS deployment checklist

- Push the image to ECR and deploy it on ECS Fargate or App Runner behind an HTTPS load balancer.
- Use Amazon RDS for PostgreSQL with pgvector enabled; run `alembic upgrade head` as a one-off deployment task.
- Store secrets in AWS Secrets Manager or SSM Parameter Store and inject them into the task definition.
- Use a task IAM role and the AWS default credential chain for Bedrock; never bake AWS access keys into the image or environment file.
- Restrict RDS to private subnets/security groups; give the application least-privilege IAM permissions.
- Add WAF/API Gateway or load-balancer rate limits for distributed production traffic. The included in-process limiter is only a basic MVP guard and is per container.
- Send application logs (which omit document bodies and lead values) to CloudWatch; add alarms, backups, Multi-AZ as required, and an RDS Proxy if connection pressure warrants it.
- Set exact production `ALLOWED_ORIGINS`, rotate the admin key, configure health checks (`/health`) and readiness checks (`/ready`), and run load/security tests before launch.

The MVP stores original documents in PostgreSQL. For larger scale, an approved follow-up can move originals to encrypted S3 while retaining metadata and vectors in PostgreSQL.
