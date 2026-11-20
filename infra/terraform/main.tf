terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # В продакшене state хранится удалённо в S3 с блокировкой через DynamoDB:
  # backend "s3" {
  #   bucket         = "fintech-qa-terraform-state"
  #   key            = "prod/terraform.tfstate"
  #   region         = "eu-west-1"
  #   dynamodb_table = "terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "eu-west-1"
}

variable "environment" {
  type    = string
  default = "staging"
}

# 1. S3 Bucket для хранения QA-отчётов и аудиторских логов
resource "aws_s3_bucket" "qa_reports" {
  bucket_prefix = "fintech-qa-reports-${var.environment}-"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "qa_reports_enc" {
  bucket = aws_s3_bucket.qa_reports.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 2. IAM Role для ECS-контейнера (принцип Least Privilege)
resource "aws_iam_role" "ecs_task_role" {
  name = "fintech-api-task-role-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "s3_write_only" {
  name = "allow-s3-report-upload"
  role = aws_iam_role.ecs_task_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:PutObject", "s3:GetObject"]
      Resource = "${aws_s3_bucket.qa_reports.arn}/*"
    }]
  })
}

# 3. VPC Security Group (фаервол: разрешаем только порт 8000)
resource "aws_security_group" "api_sg" {
  name        = "fintech-api-sg-${var.environment}"
  description = "Allow inbound HTTP traffic on port 8000"

  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# 4. ECS Fargate Task Definition для деплоя Docker-контейнера
resource "aws_ecs_task_definition" "fintech_api" {
  family                   = "fintech-api-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([{
    name      = "fintech-api"
    image     = "ghcr.io/anavauquelin/fintech-api-qa-suite:latest"
    essential = true
    portMappings = [{
      containerPort = 8000
      protocol      = "tcp"
    }]
  }])
}
