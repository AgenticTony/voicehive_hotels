# Development environment configuration for VoiceHive Hotels
# EU-WEST-1 (Ireland) for GDPR compliance

environment = "development"
aws_region  = "eu-west-1"

# VPC Configuration
vpc_cidr = "10.0.0.0/16"
private_subnet_cidrs = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
public_subnet_cidrs  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

# EKS Node Groups - Minimal for development
node_groups = {
  general = {
    desired = 2
    min     = 1
    max     = 3
  }
  gpu = {
    desired = 1  # Minimal GPU nodes for dev
    min     = 0
    max     = 2
  }
}

# RDS Configuration - Smaller instance for dev
rds_instance_class = "db.t3.medium"

# ElastiCache Redis - Smaller instance for dev
redis_node_type = "cache.t3.micro"

# Data retention - Shorter for dev environment
recording_retention_days   = 7
transcript_retention_days  = 30

# Disable deletion protection in dev
enable_deletion_protection = false

# Additional tags
tags = {
  CostCenter = "Development"
  Team       = "VoiceHive"
}
