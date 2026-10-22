# ClaimGuard AI — AWS Deployment Guide (ap-southeast-2)

## Architecture

```
Users → EC2 (Docker: FastAPI on :80 → :8000, Elastic IP)
              ↓ (VPC-internal, private DNS)
        RDS PostgreSQL 16 + pgvector (db.t3.micro, VPC-only)
              ↑
        Secrets Manager (DB credentials + Gemini key)
        S3 (CSV data ingestion)
        ECR (container image)
```

The database security group allows **port 5432 only from the application host's
security group** — there is no `0.0.0.0/0` ingress. Ingestion is therefore an
*in-VPC* operation (see Step 4), not a job against a public endpoint.

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
| RDS `db.t3.micro` PostgreSQL 16.15 + pgvector | Vector store — reachable only from the app host SG |
| ECR `claimguard-api` | Container image registry |
| Secrets Manager | DB credentials + Gemini API key |
| S3 `claimguard-data-<acct>-<region>` | CSV data + CodeBuild source |
| CodeBuild `claimguard-build` | Builds/pushes the image |
| CodeBuild `claimguard-ingest` | Legacy loader — superseded by the in-VPC method in Step 4 |

## Step 1: Set the Gemini API key

```bash
aws secretsmanager put-secret-value \
  --secret-id claimguard/gemini-api-key \
  --secret-string '{"api_key":"YOUR_ACTUAL_GEMINI_API_KEY"}'
```

## Step 2: Deploy infrastructure + data tier

The RDS master password is a **CloudFormation parameter** (`DbPassword`, with
`NoEcho`), so it is never stored in the template or the repository. Generate one
and keep it in your shell / password manager:

```bash
# 40+ char alphanumeric password (RDS forbids /  "  @ and space)
export DB_PASSWORD=$(openssl rand -base64 36 | tr -d '/+=\n')
```

```bash
aws cloudformation create-stack \
  --stack-name claimguard-ai \
  --template-body file://aws/cloudformation.yaml \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=Environment,ParameterValue=production \
    ParameterKey=DbInstanceClass,ParameterValue=db.t3.micro \
    ParameterKey=DbPassword,ParameterValue="$DB_PASSWORD" \
    ParameterKey=DeployApp,ParameterValue=false

aws cloudformation wait stack-create-complete --stack-name claimguard-ai
```

> `DeployApp=false` is used because the EC2 host pulls an image that must exist
> in ECR first. Set it to `true` in the second phase (Step 5).
>
> `DbPassword` must be re-supplied on **every** `update-stack` (Step 5).
> CloudFormation would otherwise reset the database password back to whatever the
> template specifies, so the template deliberately carries no default.

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

## Step 4: Load patent data (must run inside the VPC)

`DBSecurityGroup` accepts 5432 **only** from the app host's security group, so
ingestion cannot run from a laptop or from a non-VPC CodeBuild job. (VPC-enabled
CodeBuild would need a NAT gateway — an internet gateway can't be used, because
CodeBuild ENIs cannot be assigned public IPs.) Embedding the corpus also needs far
more RAM than the `t3.micro` app host has.

Temporarily resize the host, run the job there, then resize back:

```bash
INSTANCE_ID=<app instance id>
BUCKET=claimguard-data-<acct>-<region>
IMAGE=<acct>.dkr.ecr.ap-southeast-2.amazonaws.com/claimguard-api:latest

# 1. give the host enough RAM (the Elastic IP keeps the public address)
aws ec2 stop-instances --instance-ids $INSTANCE_ID && aws ec2 wait instance-stopped --instance-ids $INSTANCE_ID
aws ec2 modify-instance-attribute --instance-id $INSTANCE_ID --instance-type t3.medium
aws ec2 start-instances --instance-ids $INSTANCE_ID && aws ec2 wait instance-running --instance-ids $INSTANCE_ID

# 2. stage the inputs
aws s3 cp data/Patents_data_withclaims.csv s3://$BUCKET/
aws s3 cp aws/ingest_data.py s3://$BUCKET/source/aws/ingest_data.py
```

```bash
# 3. run ingestion on the host in its own container (the API is left alone)
aws ssm start-session --target $INSTANCE_ID      # opens a shell on the host
# --- on the host ---
aws s3 cp s3://$BUCKET/source/aws/ingest_data.py /tmp/ingest.py
docker run --rm \
  -e AWS_DEFAULT_REGION=ap-southeast-2 -e DB_SECRET_NAME=claimguard/db-credentials \
  -e DATABASE_PORT=5432 -e DATABASE_NAME=claimguard_db -e DATA_BUCKET=$BUCKET \
  -e DATABASE_HOST=$(aws cloudformation describe-stacks --stack-name claimguard-ai \
      --query 'Stacks[0].Outputs[?OutputKey==`RDSEndpoint`].OutputValue' --output text) \
  -v /tmp/ingest.py:/app/ingest_data.py $IMAGE python ingest_data.py
```

```bash
# 4. resize back to the free-tier size
aws ec2 stop-instances --instance-ids $INSTANCE_ID && aws ec2 wait instance-stopped --instance-ids $INSTANCE_ID
aws ec2 modify-instance-attribute --instance-id $INSTANCE_ID --instance-type t3.micro
aws ec2 start-instances --instance-ids $INSTANCE_ID && aws ec2 wait instance-running --instance-ids $INSTANCE_ID
```

> The job is idempotent — it exits without inserting if `patents` already has rows.

## Step 5: Deploy the application host

```bash
aws cloudformation update-stack \
  --stack-name claimguard-ai \
  --template-body file://aws/cloudformation.yaml \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=Environment,ParameterValue=production \
    ParameterKey=DbInstanceClass,ParameterValue=db.t3.micro \
    ParameterKey=DbPassword,ParameterValue="$DB_PASSWORD" \
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
