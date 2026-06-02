# ESTOQUE VIRTUAL - Sistema de Entrada de NF-e

Sistema web para processamento de Notas Fiscais Eletrônicas (NF-e), criação de estoque virtual e integração com Olist/Mercado Livre.

## 🎯 Fases do Projeto

### Fase 1: Upload e Leitura de NF-e ✅ (Atual)
- Upload de XML ou PDF da NF-e
- Extração automática de dados (nfelib para XML, OCR para PDF)
- Criação de estoque virtual
- Interface para confirmação/edição de quantidades
- Alertas de divergências

### Fase 2: Estoque Virtual Quarentena
- Aguardar conferência física
- Conferência manual e validação

### Fase 3: Vinculação ao Anúncio
- Auto-vinculação com anúncios conhecidos
- Vinculação manual com aprovação

### Fase 4: Lançamento via Olist
- Integração com API Olist
- Atualização automática de estoque em marketplaces

## 📦 Estrutura do Projeto

```
ESTOQUE_VIRTUAL/
├── backend/                    # FastAPI
│   ├── app/
│   │   ├── main.py
│   │   ├── models/            # SQLAlchemy models
│   │   ├── schemas/           # Pydantic schemas
│   │   ├── routes/            # API endpoints
│   │   ├── services/          # Business logic
│   │   └── utils/             # Helpers (NF-e parser, OCR)
│   ├── database.py
│   ├── requirements.txt
│   └── venv/
├── frontend/                   # React
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

## 🚀 Quick Start

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## 🔑 API Chaves
- Olist: (configurar em .env)
- Mercado Livre: (configurar em .env)

## 📝 Notas
- SQLite para MVP, migrar para PostgreSQL em produção
- OCR opcional, XML é prioridade
