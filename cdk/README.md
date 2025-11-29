# AWS CDK Deployment for GHActivity Pipeline

This CDK project deploys the complete infrastructure for the GitHub Activity data pipeline.

## What Gets Created

| Resource | Name | Description |
|----------|------|-------------|
| **S3 Bucket** | `ghactivity-data-{account}` | Data storage (landing + raw zones) |
| **DynamoDB** | `jobs` | Job bookmark tracking |
| **DynamoDB** | `job_run_details` | Audit log of runs |
| **ECR Repository** | `ghactivity-aws` | Docker images for Lambda |
| **Lambda** | `ghactivity-ingestor` | Downloads data from gharchive.org |
| **Lambda** | `ghactivity-transformer` | Converts JSON to Parquet |
| **IAM Role** | `ghactivity-lambda-role-cdk` | Permissions for Lambda |
| **S3 Trigger** | - | Auto-triggers transformer on new files |

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CDK DEPLOYED ARCHITECTURE                            │
└─────────────────────────────────────────────────────────────────────────────┘

  gharchive.org                    AWS Cloud (eu-central-1)
       │                    ┌─────────────────────────────────────────┐
       │                    │                                         │
       ▼                    │   ┌─────────────┐    ┌─────────────┐   │
  ┌─────────┐              │   │  DynamoDB   │    │    ECR      │   │
  │  JSON   │───────┐      │   │  (bookmark) │    │  (images)   │   │
  │  .gz    │       │      │   └──────┬──────┘    └──────┬──────┘   │
  └─────────┘       │      │          │                  │          │
                    ▼      │          ▼                  ▼          │
              ┌──────────────────────────────────────────────────┐  │
              │              Lambda Ingestor                     │  │
              │         (reads bookmark, downloads file)         │  │
              └────────────────────┬─────────────────────────────┘  │
                                   │                                │
                                   ▼                                │
              ┌──────────────────────────────────────────────────┐  │
              │                    S3 Bucket                     │  │
              │   landing/ghactivity/2025-11-21-0.json.gz       │  │
              └────────────────────┬─────────────────────────────┘  │
                                   │ S3 Event Trigger              │
                                   ▼                                │
              ┌──────────────────────────────────────────────────┐  │
              │             Lambda Transformer                   │  │
              │        (converts JSON.gz to Parquet)             │  │
              └────────────────────┬─────────────────────────────┘  │
                                   │                                │
                                   ▼                                │
              ┌──────────────────────────────────────────────────┐  │
              │                    S3 Bucket                     │  │
              │   raw/ghactivity/2025-11-21-0.parquet           │  │
              └──────────────────────────────────────────────────┘  │
                    │                                               │
                    └───────────────────────────────────────────────┘
```

## Prerequisites

1. **Node.js** (for CDK CLI): https://nodejs.org/
2. **AWS CDK CLI**:
   ```bash
   npm install -g aws-cdk
   ```
3. **Python 3.9+**
4. **AWS CLI configured** with appropriate credentials

## Quick Start

### Step 1: Install CDK Dependencies

```powershell
cd cdk
pip install -r requirements.txt
```

### Step 2: Bootstrap CDK (First time only)

```powershell
cdk bootstrap aws://YOUR_ACCOUNT_ID/eu-central-1
```

### Step 3: Build and Push Docker Image

Before deploying Lambda functions, the Docker image must exist in ECR:

```powershell
# Go back to main project directory
cd ..

# Build the Docker image
docker build --platform linux/amd64 --provenance=false -t ghactivity-aws .

# Login to ECR
aws ecr get-login-password --region eu-central-1 | docker login --username AWS --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.eu-central-1.amazonaws.com

# Tag and push
docker tag ghactivity-aws:latest YOUR_ACCOUNT_ID.dkr.ecr.eu-central-1.amazonaws.com/ghactivity-aws:latest
docker push YOUR_ACCOUNT_ID.dkr.ecr.eu-central-1.amazonaws.com/ghactivity-aws:latest
```

### Step 4: Deploy Everything

```powershell
cd cdk

# Preview what will be created
cdk diff

# Deploy!
cdk deploy --all
```

### Step 5: Initialize Job Bookmark

After deployment, initialize the bookmark in DynamoDB:

```powershell
$startDate = (Get-Date).AddDays(-7).ToString("yyyy-MM-dd")
aws dynamodb put-item `
    --table-name jobs `
    --item "{\"job_id\": {\"S\": \"ghactivity_ingest\"}, \"job_description\": {\"S\": \"Ingest ghactivity data to s3\"}, \"is_active\": {\"S\": \"Y\"}, \"baseline_days\": {\"N\": \"7\"}, \"job_run_bookmark_details\": {\"M\": {\"last_run_file_name\": {\"S\": \"$startDate-0.json.gz\"}}}}" `
    --region eu-central-1
```

### Step 6: Test the Pipeline

```powershell
# Invoke the ingestor
aws lambda invoke --function-name ghactivity-ingestor --payload '{}' response.json --region eu-central-1
cat response.json

# Check S3 for files
aws s3 ls s3://ghactivity-data-YOUR_ACCOUNT_ID/landing/ghactivity/ --region eu-central-1
aws s3 ls s3://ghactivity-data-YOUR_ACCOUNT_ID/raw/ghactivity/ --region eu-central-1
```

## Cleanup

To remove all resources:

```powershell
cdk destroy --all
```

This will delete:
- S3 bucket (including all objects)
- DynamoDB tables
- Lambda functions
- ECR repository
- IAM role

## Customization

Edit `cdk.json` to change:
- `region`: AWS region (default: eu-central-1)
- `bucket_name`: S3 bucket prefix (default: ghactivity-data)

Or pass context at deploy time:
```powershell
cdk deploy --context region=us-east-1 --context bucket_name=my-custom-bucket
```

## Comparison: Manual vs CDK

| Task | Manual Commands | CDK |
|------|-----------------|-----|
| Create S3 bucket | `aws s3 mb...` | ✅ Included |
| Create DynamoDB tables | `aws dynamodb create-table...` (x2) | ✅ Included |
| Create ECR repo | `aws ecr create-repository...` | ✅ Included |
| Create IAM role | `aws iam create-role...` + policies | ✅ Included |
| Create Lambda functions | `aws lambda create-function...` (x2) | ✅ Included |
| Add S3 trigger | `aws s3api put-bucket-notification...` | ✅ Included |
| **Total commands** | ~15 commands | **1 command** |

## Troubleshooting

### "No ECR image found"
The Docker image must be pushed to ECR before deploying Lambda functions.
Run the Docker build/push commands in Step 3 first.

### "Bootstrap required"
Run `cdk bootstrap` if you see this error - it sets up CDK resources in your account.

### "Stack already exists"
If you deployed manually before, you may have naming conflicts.
Either delete the manual resources or update the CDK resource names.
