locals {
  name = "${var.project}-${var.env}"
}

# S3 bucket for avatars/media
resource "aws_s3_bucket" "media" {
  bucket        = "${local.name}-media"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "v" {
  bucket = aws_s3_bucket.media.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "enc" {
  bucket = aws_s3_bucket.media.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "cors" {
  bucket = aws_s3_bucket.media.id
  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST"]
    allowed_origins = ["http://localhost:3000"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

# Cognito User Pool
resource "aws_cognito_user_pool" "main" {
  name = "${local.name}-users"

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_numbers   = true
    require_uppercase = true
    require_symbols   = false
  }

  auto_verified_attributes = ["email"]

  schema {
    name                     = "email"
    attribute_data_type      = "String"
    required                 = true
    mutable                  = true
  }

  schema {
    name                     = "name"
    attribute_data_type      = "String"
    required                 = true
    mutable                  = true
  }

  schema {
    name                     = "phone_number"
    attribute_data_type      = "String"
    required                 = false
    mutable                  = true
  }
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.name}-web-client"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret = false
  explicit_auth_flows = [
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_USER_PASSWORD_AUTH"
  ]
  callback_urls = var.callback_urls
  logout_urls   = var.callback_urls
  supported_identity_providers = ["COGNITO"]
}

# AppSync GraphQL API (stub)
resource "aws_appsync_graphql_api" "api" {
  name                = "${local.name}-api"
  authentication_type = "AMAZON_COGNITO_USER_POOLS"

  user_pool_config {
    aws_region     = var.aws_region
    user_pool_id   = aws_cognito_user_pool.main.id
    default_action = "ALLOW"
  }

  log_config {
    field_log_level = "ERROR"
  }
}

resource "aws_appsync_graphql_schema" "schema" {
  api_id = aws_appsync_graphql_api.api.id
  definition = <<EOF
type User {
  id: ID!
  email: String!
  name: String!
  avatar: String
}

type Query {
  _health: String
}

schema {
  query: Query
}
EOF
}

# Store outputs in SSM Parameter Store
resource "aws_ssm_parameter" "params" {
  for_each = {
    COGNITO_USER_POOL_ID   = aws_cognito_user_pool.main.id
    COGNITO_APP_CLIENT_ID  = aws_cognito_user_pool_client.web.id
    S3_BUCKET_NAME         = aws_s3_bucket.media.bucket
    APPSYNC_API_URL        = aws_appsync_graphql_api.api.uris["GRAPHQL"]
    AWS_REGION             = var.aws_region
  }
  name      = "/${local.name}/${each.key}"
  type      = "String"
  value     = each.value
  overwrite = true
}