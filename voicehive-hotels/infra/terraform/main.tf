terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.11"
    }
  }
  
  backend "s3" {
    bucket         = "voicehive-terraform-state"
    key            = "infrastructure/terraform.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "voicehive-terraform-locks"
    encrypt        = true
  }
}

# Provider configuration
provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = {
      Project     = "VoiceHive-Hotels"
      Environment = var.environment
      ManagedBy   = "Terraform"
      GDPR        = "Compliant"
    }
  }
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_id]
    command     = "aws"
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_id]
      command     = "aws"
    }
  }
}

# Data sources
data "aws_availability_zones" "available" {
  state = "available"
}

# VPC Module
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"
  
  name = "voicehive-${var.environment}"
  cidr = var.vpc_cidr
  
  azs             = slice(data.aws_availability_zones.available.names, 0, 3)
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs
  
  enable_nat_gateway   = true
  single_nat_gateway   = var.environment != "production"
  enable_dns_hostnames = true
  enable_dns_support   = true
  
  # VPC Flow Logs for compliance
  enable_flow_log                      = true
  create_flow_log_cloudwatch_iam_role  = true
  create_flow_log_cloudwatch_log_group = true
  
  tags = {
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  }
  
  public_subnet_tags = {
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
    "kubernetes.io/role/elb"                      = "1"
  }
  
  private_subnet_tags = {
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
    "kubernetes.io/role/internal-elb"             = "1"
  }
}

# EKS Module
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.0"
  
  cluster_name    = local.cluster_name
  cluster_version = "1.28"
  
  cluster_endpoint_private_access = true
  cluster_endpoint_public_access  = true

  # SECURITY: Restrict public access to specific CIDR blocks only
  # This prevents unauthorized access from the entire internet
  cluster_endpoint_public_access_cidrs = var.allowed_cidr_blocks
  
  # Encryption for compliance
  cluster_encryption_config = [{
    provider_key_arn = aws_kms_key.eks.arn
    resources        = ["secrets"]
  }]
  
  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets
  
  # Enable IRSA for pod IAM roles
  enable_irsa = true
  
  # Cluster addons
  cluster_addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent = true
    }
  }
  
  # Node groups
  eks_managed_node_groups = {
    # General compute nodes
    general = {
      desired_size = var.node_groups.general.desired
      min_size     = var.node_groups.general.min
      max_size     = var.node_groups.general.max
      
      instance_types = ["m5.xlarge"]
      
      labels = {
        workload = "general"
      }
      
      taints = []
    }
    
    # GPU nodes for AI workloads
    gpu = {
      desired_size = var.node_groups.gpu.desired
      min_size     = var.node_groups.gpu.min
      max_size     = var.node_groups.gpu.max
      
      instance_types = ["g4dn.xlarge"]
      
      labels = {
        workload = "gpu"
        "nvidia.com/gpu" = "true"
      }
      
      taints = [{
        key    = "nvidia.com/gpu"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]
      
      # Install NVIDIA drivers
      pre_bootstrap_user_data = <<-EOT
        #!/bin/bash
        curl -fsSL https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
        distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
        curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.repo | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
        sudo apt-get update && sudo apt-get install -y nvidia-docker2
        sudo systemctl restart docker
      EOT
    }
  }
  
  # Security groups
  node_security_group_additional_rules = {
    ingress_self_all = {
      description = "Node to node all ports/protocols"
      protocol    = "-1"
      from_port   = 0
      to_port     = 0
      type        = "ingress"
      self        = true
    }
  }
  
  tags = {
    GithubOrg = "voicehive"
  }
}

# KMS key for EKS encryption
resource "aws_kms_key" "eks" {
  description             = "EKS cluster encryption key"
  deletion_window_in_days = 10
  enable_key_rotation     = true
  
  tags = {
    Name = "voicehive-eks-${var.environment}"
  }
}

resource "aws_kms_alias" "eks" {
  name          = "alias/voicehive-eks-${var.environment}"
  target_key_id = aws_kms_key.eks.key_id
}

# RDS PostgreSQL
module "rds" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 6.0"
  
  identifier = "voicehive-${var.environment}"
  
  engine            = "postgres"
  engine_version    = "15"
  instance_class    = var.rds_instance_class
  allocated_storage = 100
  
  db_name  = "voicehive"
  username = "voicehive"
  port     = "5432"
  
  vpc_security_group_ids = [aws_security_group.rds.id]
  
  maintenance_window = "Mon:00:00-Mon:03:00"
  backup_window      = "03:00-06:00"
  
  backup_retention_period = 30
  
  enabled_cloudwatch_logs_exports = ["postgresql"]
  
  create_db_subnet_group = true
  subnet_ids             = module.vpc.private_subnets
  
  # Encryption for GDPR
  storage_encrypted = true
  kms_key_id       = aws_kms_key.rds.arn
  
  # High availability
  multi_az = var.environment == "production"
  
  deletion_protection = var.environment == "production"
  
  tags = {
    Name = "voicehive-${var.environment}"
  }
}

# RDS security group
resource "aws_security_group" "rds" {
  name_prefix = "voicehive-rds-${var.environment}-"
  vpc_id      = module.vpc.vpc_id
  
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "voicehive-rds-${var.environment}"
  }
}

# KMS key for RDS encryption
resource "aws_kms_key" "rds" {
  description             = "RDS encryption key"
  deletion_window_in_days = 10
  enable_key_rotation     = true
  
  tags = {
    Name = "voicehive-rds-${var.environment}"
  }
}

# S3 buckets for recordings and transcripts
resource "aws_s3_bucket" "recordings" {
  bucket = "voicehive-recordings-${var.environment}-${data.aws_caller_identity.current.account_id}"
  
  tags = {
    Name = "VoiceHive Recordings"
    GDPR = "Contains PII"
  }
}

resource "aws_s3_bucket_versioning" "recordings" {
  bucket = aws_s3_bucket.recordings.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "recordings" {
  bucket = aws_s3_bucket.recordings.id
  
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "recordings" {
  bucket = aws_s3_bucket.recordings.id
  
  rule {
    id = "delete-old-recordings"
    
    filter {}
    
    transition {
      days          = 7
      storage_class = "GLACIER_IR"
    }
    
    expiration {
      days = var.recording_retention_days
    }
    
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "recordings" {
  bucket = aws_s3_bucket.recordings.id
  
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# KMS key for S3 encryption
resource "aws_kms_key" "s3" {
  description             = "S3 encryption key"
  deletion_window_in_days = 10
  enable_key_rotation     = true
  
  tags = {
    Name = "voicehive-s3-${var.environment}"
  }
}

# ElastiCache Redis cluster
resource "aws_elasticache_subnet_group" "redis" {
  name       = "voicehive-redis-${var.environment}"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_elasticache_replication_group" "redis" {
  automatic_failover_enabled = true
  replication_group_id       = "voicehive-${var.environment}"
  description               = "Redis cluster for VoiceHive"
  node_type                 = var.redis_node_type
  number_cache_clusters     = var.environment == "production" ? 3 : 1
  port                      = 6379
  
  subnet_group_name = aws_elasticache_subnet_group.redis.name
  security_group_ids = [aws_security_group.redis.id]
  
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  
  tags = {
    Name = "voicehive-redis-${var.environment}"
  }
}

resource "aws_security_group" "redis" {
  name_prefix = "voicehive-redis-${var.environment}-"
  vpc_id      = module.vpc.vpc_id
  
  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "voicehive-redis-${var.environment}"
  }
}

# Data source for AWS account ID
data "aws_caller_identity" "current" {}

# Local values
locals {
  cluster_name = "voicehive-${var.environment}"
}

# Outputs
output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "cluster_name" {
  value = module.eks.cluster_id
}

output "rds_endpoint" {
  value = module.rds.db_instance_endpoint
}

output "redis_endpoint" {
  value = aws_elasticache_replication_group.redis.configuration_endpoint_address
}

output "recordings_bucket" {
  value = aws_s3_bucket.recordings.id
}
