#!/bin/bash

# Deployment script for Google Cloud
# Usage: ./deploy.sh [backend|frontend|all]

set -e

PROJECT_ID="${GOOGLE_PROJECT_ID:-your-project-id}"
REGION="${GOOGLE_REGION:-us-central1}"
SERVICE_NAME="hootie-backend"

deploy_backend() {
    echo "🚀 Deploying backend to Cloud Run..."
    cd server_py
    
    # Check if .env.production exists
    if [ ! -f .env.production ]; then
        echo "⚠️  Warning: .env.production not found. Using environment variables from gcloud."
    fi
    
    # Deploy to Cloud Run
    gcloud run deploy $SERVICE_NAME \
        --source . \
        --region $REGION \
        --platform managed \
        --allow-unauthenticated \
        --memory 2Gi \
        --cpu 2 \
        --timeout 300 \
        --max-instances 10 \
        --project $PROJECT_ID
    
    # Get service URL
    BACKEND_URL=$(gcloud run services describe $SERVICE_NAME \
        --region $REGION \
        --project $PROJECT_ID \
        --format 'value(status.url)')
    
    echo "✅ Backend deployed: $BACKEND_URL"
    echo "BACKEND_URL=$BACKEND_URL" > ../.env.deploy
    
    cd ..
}

deploy_frontend() {
    echo "🚀 Deploying frontend to Firebase Hosting..."
    
    # Check if backend URL is available
    if [ -f .env.deploy ]; then
        source .env.deploy
    else
        echo "⚠️  Backend URL not found. Getting from Cloud Run..."
        BACKEND_URL=$(gcloud run services describe $SERVICE_NAME \
            --region $REGION \
            --project $PROJECT_ID \
            --format 'value(status.url)')
    fi
    
    if [ -z "$BACKEND_URL" ]; then
        echo "❌ Error: Backend URL not found. Deploy backend first."
        exit 1
    fi
    
    cd web
    
    # Update API URL
    echo "VITE_API_URL=$BACKEND_URL" > .env.production
    
    # Build
    echo "📦 Building frontend..."
    npm install
    npm run build
    
    # Deploy
    echo "🌐 Deploying to Firebase..."
    firebase deploy --only hosting --project $PROJECT_ID
    
    echo "✅ Frontend deployed!"
    cd ..
}

# Main
case "${1:-all}" in
    backend)
        deploy_backend
        ;;
    frontend)
        deploy_frontend
        ;;
    all)
        deploy_backend
        deploy_frontend
        ;;
    *)
        echo "Usage: $0 [backend|frontend|all]"
        exit 1
        ;;
esac

echo "🎉 Deployment complete!"

