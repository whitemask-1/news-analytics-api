# Docker Guide for News Analytics API

## Table of Contents
1. [What is Docker?](#what-is-docker)
2. [Key Concepts](#key-concepts)
3. [Getting Started](#getting-started)
4. [Common Commands](#common-commands)
5. [Development vs Production](#development-vs-production)
6. [Troubleshooting](#troubleshooting)

## What is Docker?

Docker is a platform that packages your application and all its dependencies into a standardized unit called a **container**. Think of it as a lightweight, portable box that contains everything your app needs to run.

### Why Use Docker?

- **Consistency**: "It works on my machine" becomes a thing of the past
- **Isolation**: Your app runs in its own environment, separate from your host system
- **Portability**: Containers run the same way on any system (Mac, Linux, Windows, cloud)
- **Reproducibility**: Anyone can run your app with a single command

## Key Concepts

### 1. Dockerfile
A text file with instructions to build a Docker image. It's like a recipe for your container.

```dockerfile
FROM python:3.11-slim    # Start with a base image
WORKDIR /app             # Set working directory
COPY . .                 # Copy files into the container
RUN pip install -r requirements.txt  # Install dependencies
CMD ["uvicorn", "app.main:app"]     # Command to run the app
```

### 2. Image
A snapshot/template of your application and its environment. Built from a Dockerfile.

### 3. Container
A running instance of an image. You can have multiple containers from the same image.

### 4. Docker Compose
A tool for defining and running multi-container applications using a YAML file.

### 5. Volume
A way to persist data and share files between your host machine and containers.

## Getting Started

### Prerequisites
Install Docker Desktop from: https://www.docker.com/products/docker-desktop

### Building Your First Container

1. **Build the Docker image:**
   ```bash
   docker build -t news-analytics-api .
   ```
   - `-t` tags the image with a name
   - `.` means use the Dockerfile in the current directory

2. **Run the container:**
   ```bash
   docker run -p 8000:8000 --env-file .env news-analytics-api
   ```
   - `-p 8000:8000` maps port 8000 from container to your machine
   - `--env-file .env` loads environment variables

3. **Test the API:**
   ```bash
   curl http://localhost:8000/api/v1/health
   ```

### Using Docker Compose (Recommended)

Docker Compose simplifies the process:

1. **Start the application:**
   ```bash
   docker-compose up
   ```
   Add `-d` to run in detached mode (background)

2. **Stop the application:**
   ```bash
   docker-compose down
   ```

3. **Rebuild and restart:**
   ```bash
   docker-compose up --build
   ```

## Common Commands

### Docker Commands

```bash
# List all images
docker images

# List running containers
docker ps

# List all containers (including stopped)
docker ps -a

# View container logs
docker logs <container_name>
docker logs -f <container_name>  # Follow logs in real-time

# Execute command in running container
docker exec -it <container_name> bash

# Stop a container
docker stop <container_name>

# Remove a container
docker rm <container_name>

# Remove an image
docker rmi <image_name>

# Clean up unused containers, images, and networks
docker system prune -a
```

### Docker Compose Commands

```bash
# Start services
docker-compose up
docker-compose up -d              # Detached mode
docker-compose up --build         # Rebuild images before starting

# Stop services
docker-compose stop               # Stop without removing
docker-compose down               # Stop and remove containers

# View logs
docker-compose logs
docker-compose logs -f            # Follow logs
docker-compose logs api           # Logs for specific service

# Restart services
docker-compose restart

# Execute command in service
docker-compose exec api bash

# View running services
docker-compose ps

# Build/rebuild services
docker-compose build
docker-compose build --no-cache   # Build without cache
```

## Development vs Production

### Development Setup (Current)

**Advantages:**
- Hot-reload enabled (code changes auto-restart the server)
- Volumes mounted for live code editing
- Debug-friendly

**docker-compose.yml features:**
```yaml
volumes:
  - ./app:/app/app                # Mount local code
command: uvicorn ... --reload     # Enable hot-reload
```

### Production Setup

For production, you'd want:

1. **No hot-reload:**
   ```yaml
   command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
   ```

2. **No volume mounts** (code baked into image)

3. **Multi-stage builds** (smaller images):
   ```dockerfile
   FROM python:3.11-slim as builder
   # Install dependencies
   
   FROM python:3.11-slim
   COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
   ```

4. **Health checks and resource limits**

5. **Use production ASGI server:**
   ```bash
   gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
   ```

## Troubleshooting

### Container won't start
```bash
# Check logs
docker logs <container_name>
docker-compose logs api

# Verify environment variables
docker-compose config
```

### Port already in use
```bash
# Find process using port 8000
lsof -i :8000

# Kill the process or use a different port
docker-compose -f docker-compose.yml up -d -p 8001:8000
```

### Changes not reflecting
```bash
# Rebuild the image
docker-compose up --build

# Or clear cache and rebuild
docker-compose build --no-cache
docker-compose up
```

### Permission issues
```bash
# On Linux, you might need to adjust permissions
chmod -R 755 ./app
```

### Can't connect to API
1. Check if container is running: `docker ps`
2. Check port mapping: `docker port <container_name>`
3. Check logs: `docker logs <container_name>`
4. Verify firewall settings

### Clean slate
```bash
# Remove everything and start fresh
docker-compose down -v
docker system prune -a
docker-compose up --build
```

## Best Practices

1. **Use .dockerignore**: Exclude unnecessary files from the image
2. **Layer optimization**: Put frequently changing code after dependencies
3. **Small base images**: Use `-slim` or `-alpine` variants
4. **One process per container**: Don't run multiple services in one container
5. **Environment variables**: Never hardcode secrets in Dockerfiles
6. **Health checks**: Always define health checks for production
7. **Logging**: Log to stdout/stderr, not files
8. **Security**: Don't run as root user in production

## Next Steps

1. **Add a database container** (PostgreSQL, MongoDB, etc.)
2. **Implement CI/CD** to automatically build and push images
3. **Deploy to ECS** (you already have the infra code!)
4. **Add monitoring** (Prometheus, Grafana)
5. **Implement secrets management** (AWS Secrets Manager)

## Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Reference](https://docs.docker.com/compose/compose-file/)
- [FastAPI in Containers](https://fastapi.tiangolo.com/deployment/docker/)
- [Dockerfile Best Practices](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)
