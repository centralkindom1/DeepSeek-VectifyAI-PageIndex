# Deployment Instructions

## Overview
This document provides comprehensive instructions for deploying the DeepSeek-VectifyAI-PageIndex application.

## Prerequisites
- Python 3.8 or higher
- pip or poetry for dependency management
- Git for version control
- Docker (optional, for containerized deployment)
- Access to required API keys and credentials

## Environment Setup

### 1. Clone the Repository
```bash
git clone https://github.com/centralkindom1/DeepSeek-VectifyAI-PageIndex.git
cd DeepSeek-VectifyAI-PageIndex
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

## Configuration

### Environment Variables
Create a `.env` file in the root directory with the following variables:
```
DEEPSEEK_API_KEY=your_api_key_here
VECTIFY_API_KEY=your_api_key_here
DATABASE_URL=your_database_url
LOG_LEVEL=INFO
```

### Configuration Files
Update configuration files in the `config/` directory:
- `config.yaml` - Application settings
- `logging.yaml` - Logging configuration

## Deployment Methods

### Local Development Deployment
```bash
python -m app.main
```

### Production Deployment

#### Using Gunicorn (Recommended for Production)
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 app.main:app
```

#### Using Docker
```bash
# Build Docker image
docker build -t deepseek-vectifyai-pageindex:latest .

# Run Docker container
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  --name deepseek-app \
  deepseek-vectifyai-pageindex:latest
```

#### Using Docker Compose
```bash
docker-compose up -d
```

## Database Migration

### Initialize Database
```bash
python -m app.scripts.init_db
```

### Run Migrations
```bash
python -m alembic upgrade head
```

## Health Checks

### Verify Deployment
```bash
curl http://localhost:8000/health
```

### View Logs
```bash
# Local deployment
tail -f logs/app.log

# Docker deployment
docker logs -f deepseek-app
```

## Performance Optimization

- Configure appropriate number of worker processes based on CPU cores
- Set up load balancing for multi-instance deployments
- Enable caching for frequently accessed data
- Monitor memory and CPU usage

## Security Considerations

- Use HTTPS/TLS in production
- Implement proper API authentication and authorization
- Keep dependencies updated
- Use secure secret management for API keys
- Enable CORS only for trusted domains
- Implement rate limiting

## Troubleshooting

### Common Issues

#### Port Already in Use
```bash
# Find process using port 8000
lsof -i :8000

# Kill the process
kill -9 <PID>
```

#### Database Connection Issues
- Verify DATABASE_URL is correct
- Check database server is running
- Confirm credentials are accurate

#### Missing Dependencies
```bash
pip install --upgrade -r requirements.txt
```

## Monitoring and Maintenance

### Set Up Monitoring
- Configure health check endpoints
- Set up log aggregation
- Monitor API performance metrics
- Track error rates and response times

### Regular Maintenance
- Review and rotate logs regularly
- Update dependencies periodically
- Perform database backups
- Monitor resource utilization

## Rollback Procedures

If deployment fails:
```bash
# Revert to previous version
git revert <commit-hash>

# Restart application
# (Follow deployment instructions above)
```

## Support and Further Reading

For additional information and support:
- Check the main [README.md](../README.md)
- Review project documentation
- Open an issue on GitHub for problems

---
Last Updated: 2025-12-25
