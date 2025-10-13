# Production environment configuration for VoiceHive Hotels
# EU-WEST-1 (Ireland) for GDPR compliance - Primary region

environment = "production"
aws_region  = "eu-west-1"

# VPC Configuration
vpc_cidr = "10.2.0.0/16"
private_subnet_cidrs = ["10.2.1.0/24", "10.2.2.0/24", "10.2.3.0/24"]
public_subnet_cidrs  = ["10.2.101.0/24", "10.2.102.0/24", "10.2.103.0/24"]

# EKS Node Groups - Full scale for production
node_groups = {
  general = {
    desired = 6
    min     = 3
    max     = 10
  }
  gpu = {
    desired = 3
    min     = 2
    max     = 5
  }
}

# RDS Configuration - High performance
rds_instance_class = "db.r5.xlarge"

# ElastiCache Redis - High availability
redis_node_type = "cache.r6g.large"

# Data retention - GDPR compliant
recording_retention_days   = 30
transcript_retention_days  = 90

# Enable deletion protection
enable_deletion_protection = true

# EKS API Endpoint Security - Production requires maximum security
# CRITICAL: Must be configured with actual authorized CIDR blocks before deployment
# Never deploy without proper IP restrictions!
allowed_cidr_blocks = [
  # "192.0.2.0/24",    # Example: Replace with actual office IP range
  # "203.0.113.0/24",  # Example: Replace with actual VPN CIDR range
  # "198.51.100.0/24", # Example: Replace with actual admin access range
  "10.2.0.0/16"        # Allow VPC internal access only as absolute fallback
]

# Additional tags
tags = {
  CostCenter = "Production"
  Team       = "VoiceHive"
  SLA        = "99.95"
  GDPR       = "Compliant"
}
