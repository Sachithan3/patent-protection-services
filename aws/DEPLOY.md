# ClaimGuard AI — AWS Deployment Guide (ap-southeast-2)

## Architecture

```
Users → EC2 (Docker: FastAPI on :80 → :8000, Elastic IP)
              ↓ (VPC-internal, private DNS)
        RDS PostgreSQL 16 + pgvector (db.t3.micro, publicly accessible)
              ↑
        Secrets Manager (DB credentials + Gemini key)
        S3 (CSV data ingestion)
        ECR (container image)
```

Ingestion runs as a **CodeBuild** job (S3 CSV → embeddings → RDS), because the
RDS endpoint's port 5432 is not reachable from the local workstation.

### Why EC2 instead of App Runner

An AWS Organizations **service control policy (SCP)** explicitly denies
`apprunner:CreateService` (and all App Runner auto-scaling operations) in this
account, so App Runner cannot be used. EC2 (`t3.micro`, free-tier eligible) is
the cheapest working alternative and, unlike App Runner, does not require a NAT
gateway to reach the internet or the Gemini API.

## Components

| Resource | Purpose |
|---|---|
| VPC + 2 public subnets + IGW | Networking |
| EC2 `t3.micro` + Elastic IP | Application host (Docker container) |
| Security group (port 80 open) | Public HTTP access |
| IAM role/profile | ECR pull, Secrets Manager, S3, CloudWatch Logs |
| RDS `db.t3.micro` PostgreSQL 16.15 + pgvector | Vector store |
| ECR `claimguard-api` | Container image registry |
| Secrets Manager | DB credentials + Gemini API key |
| S3 `claimguard-data-<acct>-<region>` | CSV data + CodeBuild source |
| CodeBuild `claimguard-build` | Builds/pushes the image |
| CodeBuild `claimguard-ingest` | Loads patents into RDS |

## Step 1: Set the Gemini API key

```bash
aws secretsmanager put-secret-value \
  --secret-id claimguard/gemini-api-key \
  --secret-string '{"api_key":"YOUR_ACTUAL_GEMINI_API_KEY"}'
```

## Step 2: Deploy infrastructure + data tier

```bash
aws cloudformation create-stack \
  --stack-name claimguard-ai \
  --template-body file://aws/cloudformation.yaml \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=Environment,ParameterValue=production \
    ParameterKey=DbInstanceClass,ParameterValue=db.t3.micro \
    ParameterKey=DeployApp,ParameterValue=false

aws cloudformation wait stack-create-complete --stack-name claimguard-ai
```

> `DeployApp=false` is used because the EC2 host pulls an image that must exist
> in ECR first. Set it to `true` in the second phase (Step 5).

## Step 3: Build and push the container image (cloud-side)

Local Docker is optional — CodeBuild builds the image:

```bash
# Package the source and upload it
python - <<'PY'
import os, zipfile
exclude = {'.venv','.git','__pycache__','data','logs'}
with zipfile.ZipFile('/tmp/claimguard-src.zip','w',zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in exclude]
        for f in files:
            if f.endswith('.pyc') or f == '.env': continue
            p = os.path.join(root, f); z.write(p, os.path.relpath(p,'.'))
PY
BUCKET=claimguard-data-<acct>-<region>
aws s3 cp /tmp/claimguard-src.zip s3://$BUCKET/source/claimguard-src.zip

aws codebuild start-build --project-name claimguard-build
```

## Step 4: Load patent data

```bash
aws s3 cp data/Patents_data_withclaims.csv s3://$BUCKET/
aws codebuild start-build --project-name claimguard-ingest
```

## Step 5: Deploy the application host

```bash
aws cloudformation update-stack \
  --stack-name claimguard-ai \
  --template-body file://aws/cloudformation.yaml \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=Environment,ParameterValue=production \
    ParameterKey=DbInstanceClass,ParameterValue=db.t3.micro \
    ParameterKey=DeployApp,ParameterValue=true \
    ParameterKey=AppInstanceType,ParameterValue=t3.micro

aws cloudformation wait stack-update-complete --stack-name claimguard-ai
```

## Step 6: Verify

```bash
APP_IP=$(aws cloudformation describe-stacks --stack-name claimguard-ai \
  --query 'Stacks[0].Outputs[?OutputKey==`AppPublicIp`].OutputValue' --output text)
curl http://$APP_IP/api/v1/health
curl http://$APP_IP/docs
```

Container logs: CloudWatch log group `/claimguard/app`.

## Cost (ap-southeast-2, approximate)

| Service | Monthly |
|---|---|
| EC2 t3.micro (free tier) + EIP | ~AU$4 |
| RDS db.t3.micro, 20 GB gp3, single-AZ | ~AU$30 |
| Secrets Manager (2 secrets) | ~AU$1.50 |
| S3 + CloudWatch + CodeBuild | ~AU$3 |
| **Total** | **~AU$40** |

## Teardown

```bash
aws cloudformation delete-stack --stack-name claimguard-ai
aws cloudformation wait stack-delete-complete --stack-name claimguard-ai
aws ecr delete-repository --repository-name claimguard-api --force
aws codebuild delete-project --name claimguard-build
aws codebuild delete-project --name claimguard-ingest
```
