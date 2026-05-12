# Prior Authorization System - CDK Deployment Script (PowerShell)
# This script deploys the complete AWS infrastructure for the Prior Authorization System

param(
    [string]$Environment = "dev",
    [string]$Region = "us-east-1", 
    [string]$Profile = "default"
)

$ErrorActionPreference = "Stop"

Write-Host "🚀 Deploying Prior Authorization System Infrastructure" -ForegroundColor Green
Write-Host "Environment: $Environment" -ForegroundColor Yellow
Write-Host "Region: $Region" -ForegroundColor Yellow
Write-Host "Profile: $Profile" -ForegroundColor Yellow

# Check if AWS CLI is configured
try {
    aws sts get-caller-identity --profile $Profile | Out-Null
} catch {
    Write-Host "❌ AWS CLI not configured or invalid profile: $Profile" -ForegroundColor Red
    exit 1
}

# Check if CDK is installed
if (!(Get-Command cdk -ErrorAction SilentlyContinue)) {
    Write-Host "❌ AWS CDK not installed. Please install with: npm install -g aws-cdk" -ForegroundColor Red
    exit 1
}

# Set environment variables
$env:CDK_DEFAULT_ACCOUNT = (aws sts get-caller-identity --profile $Profile --query Account --output text)
$env:CDK_DEFAULT_REGION = $Region
$env:ENVIRONMENT = $Environment

Write-Host "Account: $env:CDK_DEFAULT_ACCOUNT" -ForegroundColor Cyan
Write-Host "Region: $env:CDK_DEFAULT_REGION" -ForegroundColor Cyan

# Install Python dependencies
Write-Host "📦 Installing Python dependencies..." -ForegroundColor Blue
pip install -r requirements.txt

# Bootstrap CDK (if not already done)
Write-Host "🔧 Bootstrapping CDK..." -ForegroundColor Blue
cdk bootstrap "aws://$env:CDK_DEFAULT_ACCOUNT/$env:CDK_DEFAULT_REGION" --profile $Profile

# Synthesize CloudFormation templates
Write-Host "🔨 Synthesizing CloudFormation templates..." -ForegroundColor Blue
cdk synth --profile $Profile

# Deploy consolidated stack
Write-Host "🚀 Deploying consolidated stack..." -ForegroundColor Green
cdk deploy "PriorAuthApp/prior-auth-$Environment" --profile $Profile --require-approval never --outputs-file deployment-outputs.json

Write-Host "✅ Deployment completed successfully!" -ForegroundColor Green

# Display important outputs
Write-Host ""
Write-Host "📋 Deployment Summary:" -ForegroundColor Cyan
Write-Host "=====================" -ForegroundColor Cyan

if (Test-Path "deployment-outputs.json") {
    $outputs = Get-Content "deployment-outputs.json" | ConvertFrom-Json
    $stackName = "PriorAuthApppriorauthdev86BFBE68"  # This will be the actual stack name
    
    if ($outputs.$stackName.APIEndpointOutput) {
        Write-Host "API Endpoint: $($outputs.$stackName.APIEndpointOutput)" -ForegroundColor White
    }
    
    if ($outputs.$stackName.FrontendURLOutput) {
        Write-Host "Frontend URL: $($outputs.$stackName.FrontendURLOutput)" -ForegroundColor White
    }
    
    if ($outputs.$stackName.DocumentsBucketOutput) {
        Write-Host "Documents Bucket: $($outputs.$stackName.DocumentsBucketOutput)" -ForegroundColor White
    }
    
    if ($outputs.$stackName.PoliciesBucketOutput) {
        Write-Host "Policies Bucket: $($outputs.$stackName.PoliciesBucketOutput)" -ForegroundColor White
    }
}

Write-Host ""
Write-Host "🔐 Security Notes:" -ForegroundColor Cyan
Write-Host "==================" -ForegroundColor Cyan
Write-Host "- All data is encrypted at rest using customer-managed KMS keys" -ForegroundColor White
Write-Host "- API Gateway enforces HTTPS and includes rate limiting" -ForegroundColor White
Write-Host "- Lambda functions use least-privilege IAM roles" -ForegroundColor White
Write-Host "- CloudWatch logging is enabled for audit trails" -ForegroundColor White
Write-Host "- DynamoDB tables have point-in-time recovery enabled" -ForegroundColor White

Write-Host ""
Write-Host "📊 Next Steps:" -ForegroundColor Cyan
Write-Host "==============" -ForegroundColor Cyan
Write-Host "1. Upload policy documents to the policies S3 bucket" -ForegroundColor White
Write-Host "2. Configure Bedrock Knowledge Base data source" -ForegroundColor White
Write-Host "3. Set up SNS alert subscriptions" -ForegroundColor White
Write-Host "4. Test the system with sample documents" -ForegroundColor White
Write-Host "5. Configure custom domain (if needed)" -ForegroundColor White

Write-Host ""
Write-Host "🔧 Useful Commands:" -ForegroundColor Cyan
Write-Host "==================" -ForegroundColor Cyan
Write-Host "View logs: aws logs tail /aws/lambda/prior-auth-* --follow --profile $Profile" -ForegroundColor White
Write-Host "Monitor Step Functions: aws stepfunctions list-executions --state-machine-arn <arn> --profile $Profile" -ForegroundColor White
if ($apiUrl) {
    Write-Host "Check API health: curl $apiUrl/health" -ForegroundColor White
}

Write-Host ""
Write-Host "Deployment completed at $(Get-Date)" -ForegroundColor Green