
param(
    [Parameter(Position=0)]
    [ValidateSet("up","down","restart","ps","logs","worker-logs","test","frontend","install-frontend","docs","dashboard")]
    [string]$Task = "up"
)

switch ($Task) {
    "up" {
        docker compose up --build -d
    }
    "down" {
        docker compose down
    }
    "restart" {
        docker compose down
        docker compose up --build -d
    }
    "ps" {
        docker compose ps
    }
    "logs" {
        docker compose logs -f
    }
    "worker-logs" {
        docker compose logs -f worker
    }
    "test" {
        .\.venv312\Scripts\python.exe -m pytest -q
    }
    "frontend" {
        Set-Location frontend
        npm run dev
    }
    "install-frontend" {
        Set-Location frontend
        npm install
    }
    "docs" {
        Start-Process "http://localhost:8000/docs"
    }
    "dashboard" {
        Start-Process "http://localhost:5173"
    }
}
