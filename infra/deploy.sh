#!/bin/bash
# Belief Reaction System - AWS Deployment Script
# Usage: ./deploy.sh [environment] [action]
#   environment: development | staging | production (default: production)
#   action: build | push | deploy | all (default: all)

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENVIRONMENT="${1:-production}"
ACTION="${2:-all}"

# AWS Configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo '')}"
ECR_REPOSITORY="belief-reaction-api"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo 'latest')}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi

    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI is not installed"
        exit 1
    fi

    if [ -z "$AWS_ACCOUNT_ID" ]; then
        log_error "Cannot determine AWS Account ID. Please configure AWS CLI or set AWS_ACCOUNT_ID"
        exit 1
    fi

    log_info "Prerequisites OK"
    log_info "  AWS Account: $AWS_ACCOUNT_ID"
    log_info "  AWS Region: $AWS_REGION"
    log_info "  Environment: $ENVIRONMENT"
    log_info "  Image Tag: $IMAGE_TAG"
}

# Build Docker image
build_image() {
    log_info "Building Docker image..."

    cd "$PROJECT_ROOT/backend"

    docker build \
        -t "$ECR_REPOSITORY:$IMAGE_TAG" \
        -t "$ECR_REPOSITORY:latest" \
        --build-arg ENVIRONMENT="$ENVIRONMENT" \
        .

    log_info "Docker image built successfully"
}

# Push to ECR
push_to_ecr() {
    log_info "Pushing image to ECR..."

    ECR_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

    # Login to ECR
    log_info "Logging in to ECR..."
    aws ecr get-login-password --region "$AWS_REGION" | \
        docker login --username AWS --password-stdin "$ECR_URI"

    # Tag and push
    docker tag "$ECR_REPOSITORY:$IMAGE_TAG" "$ECR_URI/$ECR_REPOSITORY:$IMAGE_TAG"
    docker tag "$ECR_REPOSITORY:latest" "$ECR_URI/$ECR_REPOSITORY:latest"

    log_info "Pushing $ECR_URI/$ECR_REPOSITORY:$IMAGE_TAG"
    docker push "$ECR_URI/$ECR_REPOSITORY:$IMAGE_TAG"

    log_info "Pushing $ECR_URI/$ECR_REPOSITORY:latest"
    docker push "$ECR_URI/$ECR_REPOSITORY:latest"

    log_info "Image pushed to ECR successfully"
}

# Deploy to ECS
deploy_to_ecs() {
    log_info "Deploying to ECS..."

    CLUSTER_NAME="belief-reaction-$ENVIRONMENT"
    SERVICE_NAME="belief-reaction-api-$ENVIRONMENT"

    # Force new deployment
    log_info "Forcing new deployment for service $SERVICE_NAME..."
    aws ecs update-service \
        --cluster "$CLUSTER_NAME" \
        --service "$SERVICE_NAME" \
        --force-new-deployment \
        --region "$AWS_REGION"

    log_info "Waiting for deployment to stabilize..."
    aws ecs wait services-stable \
        --cluster "$CLUSTER_NAME" \
        --services "$SERVICE_NAME" \
        --region "$AWS_REGION"

    log_info "Deployment completed successfully!"
}

# Deploy CloudFormation stack
deploy_infrastructure() {
    log_info "Deploying CloudFormation stack..."

    STACK_NAME="belief-reaction-$ENVIRONMENT"

    # Check if stack exists
    if aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" &> /dev/null; then
        log_info "Updating existing stack..."
        ACTION="update-stack"
    else
        log_info "Creating new stack..."
        ACTION="create-stack"
    fi

    log_warn "Please ensure you have set the required parameters:"
    log_warn "  - VpcId"
    log_warn "  - SubnetIds"
    log_warn "  - DatabaseUrl"
    log_info ""
    log_info "Example:"
    log_info "  aws cloudformation $ACTION \\"
    log_info "    --stack-name $STACK_NAME \\"
    log_info "    --template-body file://$SCRIPT_DIR/cloudformation.yml \\"
    log_info "    --parameters \\"
    log_info "      ParameterKey=Environment,ParameterValue=$ENVIRONMENT \\"
    log_info "      ParameterKey=VpcId,ParameterValue=vpc-xxx \\"
    log_info "      ParameterKey=SubnetIds,ParameterValue='subnet-xxx,subnet-yyy' \\"
    log_info "      ParameterKey=DatabaseUrl,ParameterValue='postgresql://...' \\"
    log_info "      ParameterKey=ImageTag,ParameterValue=$IMAGE_TAG \\"
    log_info "    --capabilities CAPABILITY_NAMED_IAM \\"
    log_info "    --region $AWS_REGION"
}

# Show usage
show_usage() {
    echo "Usage: $0 [environment] [action]"
    echo ""
    echo "Environments:"
    echo "  development  - Development environment"
    echo "  staging      - Staging environment"
    echo "  production   - Production environment (default)"
    echo ""
    echo "Actions:"
    echo "  build        - Build Docker image only"
    echo "  push         - Push image to ECR only"
    echo "  deploy       - Deploy to ECS only (requires existing image)"
    echo "  infra        - Show CloudFormation deployment instructions"
    echo "  all          - Build, push, and deploy (default)"
    echo ""
    echo "Environment variables:"
    echo "  AWS_REGION      - AWS region (default: us-east-1)"
    echo "  AWS_ACCOUNT_ID  - AWS account ID (auto-detected)"
    echo "  IMAGE_TAG       - Docker image tag (default: git short hash)"
}

# Main
main() {
    case "$ACTION" in
        build)
            check_prerequisites
            build_image
            ;;
        push)
            check_prerequisites
            push_to_ecr
            ;;
        deploy)
            check_prerequisites
            deploy_to_ecs
            ;;
        infra)
            check_prerequisites
            deploy_infrastructure
            ;;
        all)
            check_prerequisites
            build_image
            push_to_ecr
            deploy_to_ecs
            ;;
        help|--help|-h)
            show_usage
            ;;
        *)
            log_error "Unknown action: $ACTION"
            show_usage
            exit 1
            ;;
    esac
}

main
