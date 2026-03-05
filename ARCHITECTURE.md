# Architecture

## Components

### 1. Backend (FastAPI)
- Handles ingestion, RAG, and health intelligence logic.
- Connects to PostgreSQL for structured data and vector embeddings.
- Interfaces with Ollama for LLM and embeddings.

### 2. Frontend (Streamlit)
- Interactive UI for dashboard, chat, and data upload.

### 3. Database (PostgreSQL + pgvector)
- Stores patient records, lab results, and family history.
- `pgvector` enables semantic search over medical guidelines and parsed data.

### 4. Ingestion Pipeline
- `pdfplumber` for parsing medical reports.
- Custom parsers for Samsung Health data.
- Normalization engine for lab results.
