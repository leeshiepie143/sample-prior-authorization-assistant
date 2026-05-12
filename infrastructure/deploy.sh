#!/bin/bash

# Prior Authorization System - CDK Deployment Script
# This script deploys the complete AWS infrastructure for the Prior Authorization System

set -e

# Configuration
ENVIRONMENT=${1:-dev}
REGION=${2:-us-east-1}
PROFILE=${3:-default}

echo "🚀 Deploying Prior Authorization System Infrastructure"
echo "Environment: $ENVIRONMENT"
echo "Region: $REGION"
echo "Profile: $PROFILE"

# Check if AWS CLI is configured
if ! aws sts get-caller-identity --profile "$PROFILE" > /dev/null 2>&1; then
    echo "❌ AWS CLI not configured or invalid profile: $PROFILE"
    exit 1
fi

# Check if CDK is installed
if ! command -v cdk &> /dev/null; then
    echo "❌ AWS CDK not installed. Please install with: npm install -g aws-cdk"
    exit 1
fi

# Set environment variables
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)
export CDK_DEFAULT_REGION=$REGION
export ENVIRONMENT=$ENVIRONMENT

echo "Account: $CDK_DEFAULT_ACCOUNT"
echo "Region: $CDK_DEFAULT_REGION"

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

# Bootstrap CDK (if not already done)
echo "🔧 Bootstrapping CDK..."
cdk bootstrap "aws://$CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION" --profile "$PROFILE"

# Synthesize CloudFormation templates
echo "🔨 Synthesizing CloudFormation templates..."
cdk synth --profile "$PROFILE"

# Deploy consolidated stack
echo "🚀 Deploying consolidated stack..."
cdk deploy "PriorAuthApp/prior-auth-$ENVIRONMENT" \
    --profile "$PROFILE" \
    --require-approval never \
    --outputs-file deployment-outputs.json

echo "✅ Deployment completed successfully!"

# Display important outputs
echo ""
echo "📋 Deployment Summary:"
echo "====================="

if [ -f deployment-outputs.json ]; then
    # Extract outputs from the consolidated stack
    API_URL=$(jq -r '.PriorAuthApppriorauthdev86BFBE68.APIEndpointOutput // "Not available"' < deployment-outputs.json)
    FRONTEND_URL=$(jq -r '.PriorAuthApppriorauthdev86BFBE68.FrontendURLOutput // "Not available"' < deployment-outputs.json)
    DOCS_BUCKET=$(jq -r '.PriorAuthApppriorauthdev86BFBE68.DocumentsBucketOutput // "Not available"' < deployment-outputs.json)
    POLICIES_BUCKET=$(jq -r '.PriorAuthApppriorauthdev86BFBE68.PoliciesBucketOutput // "Not available"' < deployment-outputs.json)
    
    echo "API Endpoint: $API_URL"
    echo "Frontend URL: $FRONTEND_URL"
    echo "Documents Bucket: $DOCS_BUCKET"
    echo "Policies Bucket: $POLICIES_BUCKET"
fi

echo ""
echo "🔐 Security Notes:"
echo "=================="
echo "- All data is encrypted at rest using customer-managed KMS keys"
echo "- API Gateway enforces HTTPS and includes rate limiting"
echo "- Lambda functions use least-privilege IAM roles"
echo "- CloudWatch logging is enabled for audit trails"
echo "- DynamoDB tables have point-in-time recovery enabled"

echo ""
echo "📊 Next Steps:"
echo "=============="
echo "1. Upload policy documents to the policies S3 bucket"
echo "2. Configure Bedrock Knowledge Base data source"
echo "3. Set up SNS alert subscriptions"
echo "4. Test the system with sample documents"
echo "5. Configure custom domain (if needed)"

echo ""
echo "🔧 Useful Commands:"
echo "=================="
echo "View logs: aws logs tail /aws/lambda/prior-auth-* --follow --profile $PROFILE"
echo "Monitor Step Functions: aws stepfunctions list-executions --state-machine-arn <arn> --profile $PROFILE"
echo "Check API health: curl $API_URL/health"

echo ""
echo "Deployment completed at $(date)"