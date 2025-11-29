"""
GHActivity Pipeline Stack

This stack creates all AWS resources needed for the data pipeline:
- S3 bucket with landing/ and raw/ prefixes
- DynamoDB tables for job tracking (jobs, job_run_details)
- ECR repository for Lambda container images
- Lambda functions (ingestor, transformer)
- IAM roles and policies
- S3 event notifications to trigger transformer
"""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    Size,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
    aws_ecr as ecr,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_s3_notifications as s3n,
)
from constructs import Construct


class GHActivityPipelineStack(Stack):
    """Main stack for the GHActivity data pipeline."""

    def __init__(
        self, 
        scope: Construct, 
        construct_id: str, 
        bucket_name: str,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ========================================
        # S3 BUCKET
        # ========================================
        # Creates: s3://ghactivity-data-{account}/
        #   - landing/ghactivity/  (raw JSON.gz files)
        #   - raw/ghactivity/      (Parquet files)
        
        self.data_bucket = s3.Bucket(
            self, "DataBucket",
            bucket_name=f"{bucket_name}-{self.account}",
            removal_policy=RemovalPolicy.DESTROY,  # For easy cleanup during development
            auto_delete_objects=True,  # Delete objects when bucket is destroyed
            versioned=False,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # ========================================
        # DYNAMODB TABLES
        # ========================================
        
        # Jobs table - stores job configuration and current bookmark
        # This is the "counter" that tracks which file was last processed
        self.jobs_table = dynamodb.Table(
            self, "JobsTable",
            table_name="jobs",
            partition_key=dynamodb.Attribute(
                name="job_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Job run details table - audit log of all job runs
        self.job_run_details_table = dynamodb.Table(
            self, "JobRunDetailsTable",
            table_name="job_run_details",
            partition_key=dynamodb.Attribute(
                name="job_id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="job_run_time",
                type=dynamodb.AttributeType.NUMBER
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ========================================
        # ECR REPOSITORY
        # ========================================
        
        self.ecr_repo = ecr.Repository(
            self, "LambdaRepo",
            repository_name="ghactivity-aws",
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
        )

        # ========================================
        # IAM ROLE FOR LAMBDA
        # ========================================
        
        self.lambda_role = iam.Role(
            self, "LambdaRole",
            role_name="ghactivity-lambda-role-cdk",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        # Grant permissions
        self.data_bucket.grant_read_write(self.lambda_role)
        self.jobs_table.grant_read_write_data(self.lambda_role)
        self.job_run_details_table.grant_read_write_data(self.lambda_role)

        # ========================================
        # LAMBDA FUNCTIONS
        # ========================================
        
        # Note: Lambda functions use container images from ECR
        # The image must be built and pushed separately before deploying
        # Use: docker build and docker push (see README)
        
        # Ingestor Lambda - downloads data from gharchive.org to S3
        self.ingestor_lambda = lambda_.DockerImageFunction(
            self, "IngestorLambda",
            function_name="ghactivity-ingestor",
            code=lambda_.DockerImageCode.from_ecr(
                repository=self.ecr_repo,
                tag_or_digest="latest"
            ),
            role=self.lambda_role,
            timeout=Duration.minutes(5),
            memory_size=512,
            environment={
                "BUCKET_NAME": self.data_bucket.bucket_name,
                "DYNAMODB_TABLE": self.jobs_table.table_name,
            },
        )

        # Transformer Lambda - converts JSON to Parquet
        self.transformer_lambda = lambda_.DockerImageFunction(
            self, "TransformerLambda",
            function_name="ghactivity-transformer",
            code=lambda_.DockerImageCode.from_ecr(
                repository=self.ecr_repo,
                tag_or_digest="latest"
            ),
            role=self.lambda_role,
            timeout=Duration.minutes(10),
            memory_size=3008,  # Needs more memory for Parquet conversion
            ephemeral_storage_size=Size.mebibytes(2048),  # 2GB temp storage
            environment={
                "BUCKET_NAME": self.data_bucket.bucket_name,
            },
        )

        # ========================================
        # S3 EVENT TRIGGER
        # ========================================
        
        # When a file lands in landing/ghactivity/, trigger the transformer
        self.data_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.transformer_lambda),
            s3.NotificationKeyFilter(prefix="landing/ghactivity/")
        )

        # ========================================
        # OUTPUTS
        # ========================================
        
        CfnOutput(self, "BucketName", 
            value=self.data_bucket.bucket_name,
            description="S3 bucket for data storage"
        )
        
        CfnOutput(self, "ECRRepository", 
            value=self.ecr_repo.repository_uri,
            description="ECR repository URI for pushing Docker images"
        )
        
        CfnOutput(self, "IngestorLambdaArn", 
            value=self.ingestor_lambda.function_arn,
            description="Ingestor Lambda function ARN"
        )
        
        CfnOutput(self, "TransformerLambdaArn", 
            value=self.transformer_lambda.function_arn,
            description="Transformer Lambda function ARN"
        )
        
        CfnOutput(self, "LambdaRoleArn",
            value=self.lambda_role.role_arn,
            description="IAM role ARN for Lambda functions"
        )
