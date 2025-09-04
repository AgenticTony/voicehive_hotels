# Backend configuration for Terraform state
# This file configures where Terraform stores its state

terraform {
  backend "s3" {
    bucket         = "voicehive-terraform-state"
    key            = "infrastructure/terraform.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "voicehive-terraform-locks"
    encrypt        = true
    
    # Enable versioning and server-side encryption
    versioning = true
    
    # Add tags for compliance
    tags = {
      Project     = "VoiceHive-Hotels"
      ManagedBy   = "Terraform"
      GDPR        = "Compliant"
      Environment = "Shared"
    }
  }
}

# Create the S3 bucket and DynamoDB table for state management
# These resources should be created manually or with a bootstrap script
# to avoid chicken-and-egg problems
