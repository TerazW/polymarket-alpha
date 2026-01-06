# Market Sensemaking - Terraform Infrastructure

## Prerequisites

1. **AWS Account** - Register at https://aws.amazon.com
2. **AWS CLI** - Install from https://aws.amazon.com/cli/
3. **Terraform** - Install from https://terraform.io/downloads

## Quick Start

### 1. Configure AWS Credentials

```bash
# Option A: Environment variables
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"

# Option B: AWS CLI configuration
aws configure
```

### 2. Initialize Terraform

```bash
cd infra/terraform
terraform init
```

### 3. Plan Deployment

```bash
# Staging
terraform plan -var-file=environments/staging.tfvars

# Production
terraform plan -var-file=environments/production.tfvars
```

### 4. Apply Infrastructure

```bash
# Staging
terraform apply -var-file=environments/staging.tfvars

# Production
terraform apply -var-file=environments/production.tfvars
```

## Post-Deployment Steps

### 1. SSL Certificate Validation

After `terraform apply`, you'll see DNS validation records in the outputs:

```
acm_certificate_validation_options = [
  {
    name  = "_xxxxx.marketsensemaking.com."
    type  = "CNAME"
    value = "_xxxxx.acm-validations.aws."
  }
]
```

Add these CNAME records to your Cloudflare DNS.

### 2. Configure DNS

Add the ALB DNS name to Cloudflare:

```
Type: CNAME
Name: api
Target: <alb_dns_name from outputs>
Proxy: OFF (for WebSocket support)
```

### 3. Push Docker Images

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

# Build and push images
docker build -f infra/Dockerfile.api -t market-sensemaking/api .
docker tag market-sensemaking/api:latest <ecr-url>/market-sensemaking/api:latest
docker push <ecr-url>/market-sensemaking/api:latest

# Repeat for collector, reactor, tile-worker
```

### 4. Run Database Migrations

Connect to RDS and run init.sql:

```bash
psql -h <rds_endpoint> -U msadmin -d market_sensemaking < infra/init.sql
```

## Architecture

```
                                 ┌─────────────────┐
                                 │   CloudFlare    │
                                 │  (DNS + CDN)    │
                                 └────────┬────────┘
                                          │
                                 ┌────────▼────────┐
                                 │      ALB        │
                                 │  (HTTPS/WSS)    │
                                 └────────┬────────┘
                                          │
          ┌───────────────────────────────┼───────────────────────────────┐
          │                      Private Subnets                          │
          │                                                               │
          │  ┌─────────┐  ┌───────────┐  ┌─────────┐  ┌─────────────┐   │
          │  │   API   │  │ Collector │  │ Reactor │  │ Tile Worker │   │
          │  │(Fargate)│  │ (Fargate) │  │(Fargate)│  │  (Fargate)  │   │
          │  └────┬────┘  └─────┬─────┘  └────┬────┘  └──────┬──────┘   │
          │       │             │             │              │          │
          │       └─────────────┼─────────────┼──────────────┘          │
          │                     │             │                          │
          │              ┌──────▼─────┐ ┌─────▼──────┐                   │
          │              │    RDS     │ │   Redis    │                   │
          │              │ (Postgres) │ │(ElastiCache)│                  │
          │              └────────────┘ └────────────┘                   │
          │                                                               │
          └───────────────────────────────────────────────────────────────┘
```

## Cost Estimate

| Resource | Staging | Production |
|----------|---------|------------|
| RDS (db.t3.micro/small) | ~$15/mo | ~$30/mo |
| ElastiCache (cache.t3.micro) | ~$12/mo | ~$12/mo |
| ECS Fargate (4 services) | ~$25/mo | ~$60/mo |
| ALB | ~$16/mo | ~$16/mo |
| NAT Gateway | ~$32/mo | ~$32/mo |
| Data Transfer | ~$5/mo | ~$10/mo |
| **Total** | **~$105/mo** | **~$160/mo** |

## Troubleshooting

### Certificate Validation Stuck

1. Verify DNS records are added correctly in Cloudflare
2. Wait up to 30 minutes for propagation
3. Check: `aws acm describe-certificate --certificate-arn <arn>`

### ECS Tasks Not Starting

1. Check CloudWatch logs: `/ecs/market-sensemaking/<service>`
2. Verify ECR images exist
3. Check security group rules

### Database Connection Issues

1. Verify security group allows ECS tasks
2. Check Secrets Manager has correct credentials
3. Test connectivity from within VPC

## Destroy Infrastructure

```bash
# WARNING: This destroys everything!
terraform destroy -var-file=environments/staging.tfvars
```

## Files

```
terraform/
├── versions.tf          # Provider versions
├── variables.tf         # Input variables
├── vpc.tf              # VPC and networking
├── security_groups.tf  # Security groups
├── rds.tf              # PostgreSQL database
├── elasticache.tf      # Redis cache
├── ecr.tf              # Container registry
├── ecs.tf              # ECS cluster and services
├── alb.tf              # Load balancer
├── secrets.tf          # Secrets Manager
├── cloudwatch.tf       # Monitoring and alerts
├── outputs.tf          # Output values
└── environments/
    ├── staging.tfvars
    └── production.tfvars
```
