#!/usr/bin/env python3
"""
AWS CDK application for Prior Authorization System - Consolidated Version.

This version uses a single stack to avoid circular dependency issues.
"""

import os
from aws_cdk import App, Environment, Tags
from constructs import Construct

from stacks.consolidated_stack import ConsolidatedStack


class PriorAuthApp(Construct):
    """Main CDK application for Prior Authorization System"""
    
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Environment configuration
        env = Environment(
            account=os.getenv('CDK_DEFAULT_ACCOUNT'),
            region=os.getenv('CDK_DEFAULT_REGION', 'us-east-1')
        )
        
        # Application configuration
        app_config = {
            'environment': os.getenv('ENVIRONMENT', 'dev'),
            'app_name': 'pa-assist',
            'domain_name': os.getenv('DOMAIN_NAME'),
            'certificate_arn': os.getenv('CERTIFICATE_ARN'),
            'vpc_id': os.getenv('VPC_ID'),
            'subnet_ids': os.getenv('SUBNET_IDS', '').split(',') if os.getenv('SUBNET_IDS') else None
        }
        
        # Deploy consolidated stack
        consolidated_stack = ConsolidatedStack(
            self, f"{app_config['app_name']}-{app_config['environment']}",
            env=env,
            app_config=app_config
        )
        
        # Add common tags
        self._add_common_tags(app_config)
        
        # Store important outputs
        self.api_endpoint = consolidated_stack.api_gateway.url
    
    def _add_common_tags(self, app_config: dict) -> None:
        """Add common tags to all resources"""
        
        common_tags = {
            'Application': 'PriorAuthorizationSystem',
            'Environment': app_config['environment'],
            'Owner': 'HealthcareTeam',
            'CostCenter': 'Healthcare-IT',
            'Compliance': 'HIPAA',
            'DataClassification': 'PHI',
            'BackupRequired': 'true',
            'MonitoringRequired': 'true'
        }
        
        for key, value in common_tags.items():
            Tags.of(self).add(key, value)


def main():
    """Main function to create and deploy the CDK app"""
    
    app = App()
    
    # Create the Prior Authorization application
    prior_auth_app = PriorAuthApp(app, "PriorAuthApp")
    
    # Synthesize the CloudFormation templates
    app.synth()


if __name__ == "__main__":
    main()