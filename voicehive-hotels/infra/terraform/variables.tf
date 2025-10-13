variable "aws_region" {
  description = "AWS region for deployment (must be EU for GDPR compliance)"
  type        = string
  default     = "eu-west-1"
  
  validation {
    condition     = can(regex("^eu-", var.aws_region))
    error_message = "AWS region must be in EU for GDPR compliance (e.g., eu-west-1, eu-central-1)"
  }
}

variable "environment" {
  description = "Environment name (development, staging, production)"
  type        = string
  
  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "Environment must be development, staging, or production"
  }
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets"
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed to access EKS cluster API endpoint (security best practice - never use 0.0.0.0/0)"
  type        = list(string)
  default     = []

  validation {
    condition     = !contains(var.allowed_cidr_blocks, "0.0.0.0/0")
    error_message = "EKS cluster endpoint must not allow access from 0.0.0.0/0 (entire internet). Specify specific CIDR blocks only."
  }
}

variable "node_groups" {
  description = "EKS node group configurations"
  type = object({
    general = object({
      desired = number
      min     = number
      max     = number
    })
    gpu = object({
      desired = number
      min     = number
      max     = number
    })
  })
  default = {
    general = {
      desired = 3
      min     = 3
      max     = 10
    }
    gpu = {
      desired = 2
      min     = 1
      max     = 5
    }
  }
}

variable "rds_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.r5.xlarge"
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type"
  type        = string
  default     = "cache.r6g.large"
}

variable "recording_retention_days" {
  description = "Number of days to retain call recordings (GDPR compliance)"
  type        = number
  default     = 30
}

variable "transcript_retention_days" {
  description = "Number of days to retain transcripts (GDPR compliance)"
  type        = number
  default     = 90
}

variable "enable_deletion_protection" {
  description = "Enable deletion protection for critical resources"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
