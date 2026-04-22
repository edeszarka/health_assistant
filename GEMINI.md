# 🏥 Health Assistant - Gemini CLI Context

This project is a local-first personal health intelligence assistant that uses AI to analyze lab results, track vitals, and provide health insights.

## Project Overview
- **Architecture**: Microservices-based with a FastAPI backend, Streamlit frontend, and PostgreSQL (with pgvector) database.
- **Core Technologies**:
    - **Backend**: Python 3.12, FastAPI, SQLAlchemy (Async), Alembic, Pydantic v2.
    - **AI/LLM**: LangChain, Ollama (qwen3:4b for chat, nomic-embed-text for embeddings).
    - **Frontend**: Streamlit, Pandas, Plotly.
    - **Database**: PostgreSQL 16 + `pgvector` for semantic search/RAG.
    - **Parsing**: `pdfplumber` (Labs), `pyzipper` (Zepp Life), custom Samsung Health parsers.
- **Key Features**:
    - Lab PDF ingestion with automatic normalization (Hungarian/Latin to English).
    - Blood pressure tracking and classification (AHA 2017).
    - Family history recording with ICD-10 support.
    - RAG-augmented chat using personal health data.
    - Preventive screening recommendations based on USPSTF guidelines and MedlinePlus.

## Building and Running

### Docker (Recommended)
```bash
cp .env.example .env  # Set POSTGRES_PASSWORD
docker-compose up -d
```
- **Frontend**: http://localhost:8501
- **Backend API**: http://localhost:8000/docs

### Local Development (Manual)
1. **Backend**:
   ```bash
   cd backend
   pip install -r requirements.txt
   # Set environment variables: DATABASE_URL, OLLAMA_BASE_URL
   uvicorn main:app --reload
   ```
2. **Frontend**:
   ```bash
   cd frontend
   pip install -r requirements.txt
   # Set environment variable: BACKEND_URL
   streamlit run app.py
   ```

### Testing
```bash
cd backend
pytest tests/ -v
```

## Development Conventions

### Data Models
- **Database**: Defined in `backend/models/db_models.py` using SQLAlchemy 2.0.
- **API**: Defined in `backend/models/api_models.py` using Pydantic v2.
- **Migrations**: Use Alembic (`cd backend && alembic revision --autogenerate -m "..."`).

### Extending the System
- **Lab Normalization**: Add new Hungarian/Latin mapping strings to `KNOWN_MAPPINGS` in `backend/ingestion/lab_normalizer.py`.
- **Screening Rules**: Add new recommendation tuples to `SCREENING_RULES` in `backend/services/screening_service.py`.
- **New Routers**: Register new FastAPI routers in `backend/main.py`.

### Privacy and Security
- All AI processing must remain local via Ollama.
- External API calls (MedlinePlus) must only send anonymized condition names, never personal data.
- Secrets must be managed via `.env` and never committed to version control.

## Directory Structure Highlights
- `backend/ingestion/`: Parsers for various data formats.
- `backend/services/`: Core business logic (RAG, Risk Engines, Screening).
- `backend/routers/`: FastAPI endpoints.
- `data_sample/`: JSON-based guidelines and sample data.
- `frontend/pages/`: Streamlit multi-page application structure.
