# GHActivity Pipeline - CDK Deployment Script
# This script deploys the complete infrastructure using AWS CDK

param(
    [string]$Region = "eu-central-1",
    [string]$BucketName = "ghactivity-data",
    [switch]$SkipDocker,
    [switch]$DestroyOnly
)

$ErrorActionPreference = "Stop"

# Colors for output
function Write-Step { param($msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "✓ $msg" -ForegroundColor Green }
function Write-Warning { param($msg) Write-Host "⚠ $msg" -ForegroundColor Yellow }

# Get AWS Account ID
$AccountId = aws sts get-caller-identity --query Account --output text
Write-Host "`nAWS Account: $AccountId"
Write-Host "Region: $Region"
Write-Host "Bucket Name: $BucketName-$AccountId"

# Destroy mode
if ($DestroyOnly) {
    Write-Step "Destroying CDK Stack..."
    Push-Location $PSScriptRoot
    cdk destroy --all --force
    Pop-Location
    Write-Success "Stack destroyed!"
    exit 0
}

# Step 1: Install CDK dependencies
Write-Step "Installing CDK dependencies..."
Push-Location $PSScriptRoot
pip install -r requirements.txt -q
Write-Success "Dependencies installed"

# Step 2: Bootstrap CDK (if needed)
Write-Step "Checking CDK bootstrap..."
$bootstrapStatus = aws cloudformation describe-stacks --stack-name CDKToolkit --region $Region 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warning "CDK not bootstrapped. Bootstrapping now..."
    cdk bootstrap aws://$AccountId/$Region
    Write-Success "CDK bootstrapped"
} else {
    Write-Success "CDK already bootstrapped"
}

# Step 3: Create ECR repository first (needed for Docker push)
Write-Step "Ensuring ECR repository exists..."
$ecrExists = aws ecr describe-repositories --repository-names ghactivity-aws --region $Region 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Creating ECR repository..."
    aws ecr create-repository --repository-name ghactivity-aws --region $Region | Out-Null
    Write-Success "ECR repository created"
} else {
    Write-Success "ECR repository exists"
}

# Step 4: Build and push Docker image
if (-not $SkipDocker) {
    Write-Step "Building Docker image..."
    Push-Location "$PSScriptRoot\.."
    docker build --platform linux/amd64 --provenance=false -t ghactivity-aws .
    Write-Success "Docker image built"

    Write-Step "Logging into ECR..."
    aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin "$AccountId.dkr.ecr.$Region.amazonaws.com"
    Write-Success "Logged into ECR"

    Write-Step "Pushing Docker image to ECR..."
    docker tag ghactivity-aws:latest "$AccountId.dkr.ecr.$Region.amazonaws.com/ghactivity-aws:latest"
    docker push "$AccountId.dkr.ecr.$Region.amazonaws.com/ghactivity-aws:latest"
    Write-Success "Docker image pushed"
    Pop-Location
} else {
    Write-Warning "Skipping Docker build (--SkipDocker flag)"
}

# Step 5: Deploy CDK stack
Write-Step "Deploying CDK stack..."
Push-Location $PSScriptRoot
cdk deploy --all --require-approval never --context region=$Region --context bucket_name=$BucketName
Write-Success "CDK stack deployed"
Pop-Location

# Step 6: Initialize DynamoDB bookmark
Write-Step "Initializing job bookmark in DynamoDB..."
$startDate = (Get-Date).AddDays(-7).ToString("yyyy-MM-dd")
$item = @{
    job_id = @{ S = "ghactivity_ingest" }
    job_description = @{ S = "Ingest ghactivity data to s3" }
    is_active = @{ S = "Y" }
    baseline_days = @{ N = "7" }
    job_run_bookmark_details = @{
        M = @{
            last_run_file_name = @{ S = "$startDate-0.json.gz" }
        }
    }
} | ConvertTo-Json -Depth 10 -Compress

aws dynamodb put-item --table-name jobs --item $item --region $Region
Write-Success "Job bookmark initialized (starting from $startDate)"

# Summary
Write-Host "`n" + "="*60 -ForegroundColor Green
Write-Host "DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host "="*60 -ForegroundColor Green
Write-Host ""
Write-Host "Resources created:"
Write-Host "  • S3 Bucket: $BucketName-$AccountId"
Write-Host "  • DynamoDB Tables: jobs, job_run_details"
Write-Host "  • ECR Repository: ghactivity-aws"
Write-Host "  • Lambda Functions: ghactivity-ingestor, ghactivity-transformer"
Write-Host ""
Write-Host "Test the pipeline:"
Write-Host "  aws lambda invoke --function-name ghactivity-ingestor --payload '{}' response.json --region $Region"
Write-Host ""
Write-Host "Cleanup:"
Write-Host "  .\deploy.ps1 -DestroyOnly"
Write-Host ""
