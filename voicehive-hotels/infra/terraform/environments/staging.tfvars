# Staging environment configuration for VoiceHive Hotels
# EU-CENTRAL-1 (Frankfurt) for GDPR compliance

environment = "staging"
aws_region  = "eu-central-1"

# VPC Configuration
vpc_cidr = "10.1.0.0/16"
private_subnet_cidrs = ["10.1.1.0/24", "10.1.2.0/24", "10.1.3.0/24"]
public_subnet_cidrs  = ["10.1.101.0/24", "10.1.102.0/24", "10.1.103.0/24"]

# EKS Node Groups - Moderate for staging
node_groups = {
  general = {
    desired = 3
    min     = 2
    max     = 5
  }
  gpu = {
    desired = 2
    min     = 1
    max     = 3
  }
}

# RDS Configuration
rds_instance_class = "db.r5.large"

# ElastiCache Redis
redis_node_type = "cache.r6g.large"

# Data retention - Production-like
recording_retention_days   = 30
transcript_retention_days  = 90

# Enable deletion protection
enable_deletion_protection = true

# Additional tags
tags = {
  CostCenter = "Staging"
  Team       = "VoiceHive"
}
