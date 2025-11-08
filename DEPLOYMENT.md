# Google Cloud Deployment Guide

This guide will help you deploy the Hootie AI language tutor to Google Cloud Platform for public access.

## Architecture

- **Backend**: FastAPI server deployed on Cloud Run
- **Frontend**: React/Vite app deployed on Firebase Hosting (or Cloud Storage + Cloud CDN)

## Prerequisites

1. Google Cloud account with billing enabled
2. `gcloud` CLI installed and authenticated
3. `docker` installed (for local testing)
4. `firebase-tools` installed (for frontend deployment)

## Step 1: Set Up Google Cloud Project

```bash
# Set your project ID
export PROJECT_ID="your-project-id"
export REGION="us-central1"  # or your preferred region

# Set the project
gcloud config set project $PROJECT_ID

# Enable required APIs
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable aiplatform.googleapis.com  # For Vertex AI
```

## Step 2: Configure Environment Variables

Create a `.env.production` file in `server_py/` directory:

```bash
cd server_py
cat > .env.production << EOF
PROVIDER=google
GOOGLE_API_KEY=your-google-api-key
GOOGLE_PROJECT_ID=$PROJECT_ID
GOOGLE_LOCATION=$REGION
GOOGLE_MODEL=gemini-2.5-flash-lite
ALLOWED_ORIGINS=https://your-frontend-domain.web.app,https://your-frontend-domain.firebaseapp.com
EOF
```

**Important**: Never commit `.env.production` to git! It contains secrets.

## Step 3: Deploy Backend to Cloud Run

### Option A: Using gcloud CLI (Recommended)

```bash
cd server_py

# Build and deploy
gcloud run deploy hootie-backend \
  --source . \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --max-instances 10 \
  --set-env-vars PROVIDER=google,GOOGLE_API_KEY=your-key,GOOGLE_PROJECT_ID=$PROJECT_ID,GOOGLE_LOCATION=$REGION,GOOGLE_MODEL=gemini-2.5-flash-lite \
  --set-secrets GOOGLE_APPLICATION_CREDENTIALS=tts-gcloud:latest

# Get the service URL
export BACKEND_URL=$(gcloud run services describe hootie-backend --region $REGION --format 'value(status.url)')
echo "Backend URL: $BACKEND_URL"
```

### Option B: Using Docker (Alternative)

```bash
cd server_py

# Build Docker image
docker build -t gcr.io/$PROJECT_ID/hootie-backend:latest .

# Push to Google Container Registry
docker push gcr.io/$PROJECT_ID/hootie-backend:latest

# Deploy to Cloud Run
gcloud run deploy hootie-backend \
  --image gcr.io/$PROJECT_ID/hootie-backend:latest \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --set-env-vars PROVIDER=google,GOOGLE_API_KEY=your-key,GOOGLE_PROJECT_ID=$PROJECT_ID,GOOGLE_LOCATION=$REGION
```

**Note**: For production, use Google Secret Manager for API keys instead of environment variables.

## Step 4: Set Up Google Cloud Service Account for Vertex AI

If you're using Vertex AI for image generation:

```bash
# Create service account (if not exists)
gcloud iam service-accounts create hootie-vertex-ai \
  --display-name "Hootie Vertex AI Service Account"

# Grant necessary permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:hootie-vertex-ai@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Create and download key
gcloud iam service-accounts keys create tts-gcloud.json \
  --iam-account=hootie-vertex-ai@$PROJECT_ID.iam.gserviceaccount.com

# Upload to Secret Manager
gcloud secrets create tts-gcloud-json --data-file=tts-gcloud.json

# Grant Cloud Run access to the secret
gcloud secrets add-iam-policy-binding tts-gcloud-json \
  --member="serviceAccount:$(gcloud run services describe hootie-backend --region $REGION --format 'value(spec.template.spec.serviceAccountName)')" \
  --role="roles/secretmanager.secretAccessor"
```

## Step 5: Deploy Frontend to Firebase Hosting

### Install Firebase CLI

```bash
npm install -g firebase-tools
firebase login
```

### Initialize Firebase

```bash
cd web

# Initialize Firebase (if not already done)
firebase init hosting

# Select:
# - Use an existing project (select your project)
# - Public directory: dist
# - Single-page app: Yes
# - Set up automatic builds: No
```

### Build and Deploy

```bash
cd web

# Update API URL in .env.production
echo "VITE_API_URL=$BACKEND_URL" > .env.production

# Build the app
npm install
npm run build

# Deploy to Firebase
firebase deploy --only hosting
```

The frontend will be available at: `https://your-project-id.web.app`

## Step 6: Update CORS Settings

After deploying, update the backend's allowed origins:

```bash
gcloud run services update hootie-backend \
  --region $REGION \
  --update-env-vars ALLOWED_ORIGINS=https://your-project-id.web.app,https://your-project-id.firebaseapp.com
```

## Step 7: Test the Deployment

1. Visit your Firebase Hosting URL: `https://your-project-id.web.app`
2. Test the chat functionality
3. Test quiz generation
4. Check Cloud Run logs if needed: `gcloud run services logs read hootie-backend --region $REGION`

## Monitoring and Logs

```bash
# View logs
gcloud run services logs read hootie-backend --region $REGION --limit 50

# View service details
gcloud run services describe hootie-backend --region $REGION
```

## Cost Optimization

- **Cloud Run**: Pay only for requests (very cost-effective for low traffic)
- **Firebase Hosting**: Free tier includes 10GB storage and 360MB/day transfer
- **Vertex AI**: Pay per API call (check pricing)

## Troubleshooting

### Backend Issues

1. **502 Bad Gateway**: Check logs, increase memory/CPU
2. **Timeout**: Increase timeout (max 300s for Cloud Run)
3. **CORS errors**: Verify ALLOWED_ORIGINS includes your frontend URL

### Frontend Issues

1. **API calls failing**: Verify VITE_API_URL is set correctly
2. **Build errors**: Check Node.js version (should be 18+)

## Security Notes

- ✅ Cloud Run service is publicly accessible (no login required)
- ✅ CORS is configured to allow only your frontend domain
- ⚠️ API keys are in environment variables (consider Secret Manager for production)
- ⚠️ No authentication on backend (add if needed for production)

## Next Steps

1. Set up custom domain (optional)
2. Configure Cloud CDN for better performance
3. Set up monitoring and alerts
4. Configure auto-scaling limits

