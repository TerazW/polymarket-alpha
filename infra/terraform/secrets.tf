# =============================================================================
# Market Sensemaking - Secrets Manager
# =============================================================================

# -----------------------------------------------------------------------------
# Database Credentials
# -----------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "db_credentials" {
  name        = "${var.project_name}/db-credentials"
  description = "Database credentials for Market Sensemaking"

  tags = {
    Name = "${var.project_name}-db-credentials"
  }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id

  secret_string = jsonencode({
    username = var.db_username
    password = random_password.db_password.result
    host     = aws_db_instance.main.address
    port     = 5432
    dbname   = var.db_name
  })
}

# -----------------------------------------------------------------------------
# API Keys (placeholder - add actual secrets as needed)
# -----------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "api_keys" {
  name        = "${var.project_name}/api-keys"
  description = "API keys and JWT secrets"

  tags = {
    Name = "${var.project_name}-api-keys"
  }
}

resource "random_password" "jwt_secret" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret_version" "api_keys" {
  secret_id = aws_secretsmanager_secret.api_keys.id

  secret_string = jsonencode({
    jwt_secret = random_password.jwt_secret.result
  })
}
