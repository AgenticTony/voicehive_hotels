output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_app_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "s3_bucket_name" {
  value = aws_s3_bucket.media.bucket
}

output "appsync_api_url" {
  value = aws_appsync_graphql_api.api.uris["GRAPHQL"]
}