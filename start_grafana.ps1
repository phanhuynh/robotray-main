# Quick Grafana Setup Script for Mining High Voltage Data

# Check if Docker is installed
$dockerVersion = docker --version 2>$null
if ($null -eq $dockerVersion) {
    Write-Host "❌ Docker is not installed!" -ForegroundColor Red
    Write-Host "Download Docker Desktop: https://www.docker.com/products/docker-desktop" -ForegroundColor Yellow
    exit
}

Write-Host "✓ Docker found: $dockerVersion" -ForegroundColor Green

# Check if Grafana container exists
$grafanaExists = docker ps -a --filter "name=grafana" --format "{{.Names}}" | Select-String "grafana"

if ($grafanaExists) {
    Write-Host "`nGrafana container already exists."
    $running = docker ps --filter "name=grafana" --format "{{.Names}}" | Select-String "grafana"
    
    if ($running) {
        Write-Host "✓ Grafana is already running on http://localhost:3000" -ForegroundColor Green
    } else {
        Write-Host "Starting existing Grafana container..."
        docker start grafana
        Write-Host "✓ Grafana started on http://localhost:3000" -ForegroundColor Green
    }
} else {
    Write-Host "`nStarting new Grafana container..."
    docker run -d -p 3000:3000 --name grafana grafana/grafana
    Write-Host "✓ Grafana started on http://localhost:3000" -ForegroundColor Green
}

Write-Host "`n" + "="*60
Write-Host "GRAFANA SETUP COMPLETE" -ForegroundColor Cyan
Write-Host "="*60
Write-Host "`n📊 Access Grafana: http://localhost:3000"
Write-Host "👤 Default login: admin / admin"
Write-Host "📝 Setup guide: See GRAFANA_SETUP.md"
Write-Host "`n🔄 Next steps:"
Write-Host "   1. Run the notebook cells to export data and start API server"
Write-Host "   2. Add JSON API data source in Grafana (Settings → Data Sources)"
Write-Host "   3. Create a new dashboard and add panels"
Write-Host "`n"
