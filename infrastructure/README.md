# Prior Authorization System - Infrastructure

This directory contains the AWS CDK infrastructure code for the Prior Authorization System.

## Structure

```
infrastructure/
├── app_consolidated.py          # Main CDK application (consolidated stack)
├── cdk.json                    # CDK configuration
├── requirements.txt            # Python dependencies
├── deploy.ps1                  # PowerShell deployment script
├── deploy.sh                   # Bash deployment script
└── stacks/
    ├── __init__.py
    └── consolidated_stack.py   # Single consolidated stack with all resources

src/                            # Lambda function source code
├── common/                     # Shared utilities and models
│   ├── models.py              # Data models and schemas
│   └── utils.py               # Common utility functions
├── extractor/                 # Medical records extraction
│   └── handler.py
├── knowledge/                 # Policy knowledge base
│   └── handler.py
├── selector/                  # Policy selection
│   └── handler.py
├── reviewer/                  # Medical record review
│   └── handler.py
└── api/                       # API Gateway integration
    └── handler.py
```

## Deployment

### Quick Deployment
```bash
# Using the consolidated app directly
cdk deploy --app "python app_consolidated.py" --require-approval never
```

### Using Deployment Scripts
```bash
# PowerShell (Windows)
./deploy.ps1 -Environment dev -Region us-east-1

# Bash (Linux/Mac)
./deploy.sh dev us-east-1
```

## Architecture

The consolidated stack creates all resources in a single CloudFormation stack:

- **Security**: KMS keys, IAM roles
- **Storage**: S3 buckets, DynamoDB tables
- **Compute**: Lambda functions, Step Functions
- **API**: API Gateway with REST endpoints
- **Frontend**: CloudFront distribution with S3 hosting
- **Monitoring**: CloudWatch dashboard, SNS topics

### Lambda Function Configuration

All Lambda functions are configured with:
- **Runtime**: Python 3.11
- **Code Location**: `src/` directory (relative to project root)
- **Handler Format**: `{module}.handler.lambda_handler` (e.g., `selector.handler.lambda_handler`)
- **Common Layer**: Shared dependencies from `src/common/` directory
- **Asset Bundling**: CDK automatically packages code from correct paths

## Outputs

After deployment, the following resources are available:

- **API Endpoint**: REST API for document processing
- **Frontend URL**: CloudFront distribution for the web interface
- **S3 Buckets**: 
  - Documents bucket for uploaded files
  - Policies bucket for payor policies
- **DynamoDB Tables**: For extraction results and metadata

## Environment Variables

Set these before deployment:
- `CDK_DEFAULT_ACCOUNT`: Your AWS account ID
- `CDK_DEFAULT_REGION`: Target AWS region (default: us-east-1)
- `ENVIRONMENT`: Environment name (default: dev)

## Notes

- This uses a consolidated stack approach to avoid circular dependencies
- All resources are HIPAA-compliant with encryption at rest
- The frontend is deployed via CloudFront with Origin Access Identity (no public S3 access)
- Lambda asset paths use `src/` relative to project root for consistent deployment
- Handler paths follow Python module structure: `{module}.handler.lambda_handler`

## Troubleshooting

### Lambda Import Errors
If you encounter "Unable to import module" errors:
1. Verify handler path format: `{module}.handler.lambda_handler`
2. Check asset path in CDK: should be `src/{module}` relative to project root
3. Ensure common layer is properly attached to functions requiring shared code
4. Review CloudWatch logs at `/aws/lambda/prior-auth-{function-name}`

### CDK Deployment Issues
- Use `cdk synth` to validate CloudFormation template before deployment
- Check `cdk.out/` directory for synthesized assets
- Verify Lambda code is packaged correctly in asset directories
- Force redeployment by updating function descriptions if code changes aren't detected