.PHONY: dev backend frontend install test clean

# One-command dev startup
dev:
	@echo "Starting Sentiment Options Lab..."
	@make backend &
	@sleep 3
	@make frontend

# Backend only
backend:
	cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend only
frontend:
	cd frontend && npm run dev

# Install all dependencies
install:
	@echo "Installing backend dependencies..."
	cd backend && pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	cd frontend && npm install
	@echo "Copying .env if not exists..."
	@test -f .env || cp .env.example .env
	@echo "Done! Run 'make dev' to start."

# Run backend tests
test:
	cd backend && python -m pytest tests/ -v

# Clean DB and build artifacts
clean:
	rm -f backend/sentiment_options_lab.db
	rm -rf frontend/.next frontend/node_modules/.cache
