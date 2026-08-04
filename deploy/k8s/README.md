# Django SaaS - Kubernetes Deployment

## Prerequisites

- Kubernetes cluster (v1.24+)
- kubectl configured to access the cluster
- nginx Ingress controller installed
- Container image `djangosaas:latest` available in cluster registry

## Quick Start

### 1. Update secrets

Edit `secret.yaml` and replace all placeholder values:

```yaml
stringData:
  SECRET_KEY: "<your-random-secret-key>"
  DB_PASSWORD: "<your-db-password>"
  JWT_SIGNING_KEY: "<your-jwt-signing-key>"
  API_SECRET_KEY: "<your-api-secret-key>"
```

### 2. Update Ingress hostname

Edit `web.yaml` and change `api.example.com` to your actual domain.

### 3. Deploy in order

```bash
# Create namespace first
kubectl apply -f namespace.yaml

# Config and secrets
kubectl apply -f configmap.yaml
kubectl apply -f secret.yaml

# Infrastructure (PostgreSQL, Redis)
kubectl apply -f postgres.yaml
kubectl apply -f redis.yaml

# Wait for DB to be ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/component=postgres -n django-saas --timeout=120s

# Application
kubectl apply -f web.yaml
kubectl apply -f celery-worker.yaml
kubectl apply -f celery-beat.yaml
kubectl apply -f flower.yaml

# Autoscaling
kubectl apply -f hpa.yaml
```

Or apply all at once:

```bash
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml -f secret.yaml -f postgres.yaml -f redis.yaml
sleep 30  # Wait for DB
kubectl apply -f web.yaml -f celery-worker.yaml -f celery-beat.yaml -f flower.yaml -f hpa.yaml
```

### 4. Verify deployment

```bash
kubectl get all -n django-saas
kubectl get hpa -n django-saas
```

### 5. Check health

```bash
kubectl port-forward svc/web 8000:80 -n django-saas
curl http://localhost:8000/api/health/
```

## Architecture

| Component | Kind | Replicas | Purpose |
|-----------|------|----------|---------|
| postgres | StatefulSet | 1 | Database (PVC 10Gi) |
| redis | Deployment | 1 | Message broker & cache |
| web | Deployment | 2 | Django API (gunicorn) |
| celery-worker | Deployment | 2 | Background task processing |
| celery-beat | Deployment | 1 | Periodic task scheduler |
| flower | Deployment | 1 | Celery monitoring dashboard |

## Resource Limits

| Component | CPU Limit | Memory Limit |
|-----------|----------|-------------|
| web | 500m | 512Mi |
| celery-worker | 1000m | 1Gi |
| celery-beat | 250m | 256Mi |
| flower | 250m | 256Mi |
| postgres | 500m | 512Mi |
| redis | 250m | 256Mi |

## HPA Configuration

| Target | Min | Max | CPU Target | Memory Target |
|--------|-----|-----|------------|--------------|
| web | 2 | 10 | 70% | 80% |
| celery-worker | 2 | 8 | 70% | 80% |

## Teardown

```bash
kubectl delete -f hpa.yaml
kubectl delete -f flower.yaml -f celery-beat.yaml -f celery-worker.yaml -f web.yaml
kubectl delete -f redis.yaml -f postgres.yaml
kubectl delete -f secret.yaml -f configmap.yaml
kubectl delete -f namespace.yaml
```

> Note: Deleting the namespace removes all resources including PVCs. PostgreSQL data will be permanently lost.
