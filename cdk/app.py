#!/usr/bin/env python3
"""
AWS CDK App for GHActivity Data Pipeline

This CDK app deploys the complete infrastructure for the GitHub Activity
data pipeline, including:
- S3 bucket for data storage (landing and raw zones)
- DynamoDB tables for job tracking
- ECR repository for Docker images
- Lambda functions for ingestion and transformation
- IAM roles and policies
- S3 event triggers

Usage:
    cdk deploy --all        # Deploy everything
    cdk destroy --all       # Clean up everything
"""

import aws_cdk as cdk
from stacks.pipeline_stack import GHActivityPipelineStack

app = cdk.App()

# Get configuration from context or use defaults
account = app.node.try_get_context("account") or None
region = app.node.try_get_context("region") or "eu-central-1"
bucket_name = app.node.try_get_context("bucket_name") or "ghactivity-data"

# Create the main pipeline stack
GHActivityPipelineStack(
    app, 
    "GHActivityPipeline",
    bucket_name=bucket_name,
    env=cdk.Environment(
        account=account,
        region=region
    ),
    description="End-to-end data pipeline for GitHub Activity data ingestion and transformation"
)

app.synth()
