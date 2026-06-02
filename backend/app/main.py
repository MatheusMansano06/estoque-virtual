from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse, FileResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from sqlalchemy.orm import Session
from database import engine, Base, SessionLocal
import os
import json
from datetime import datetime
import uuid

from app.models import NotaFiscal, ItemEstoque
from app.utils.nfe_parser import NFeParsing

# Create tables
Base.metadata.create_all(bind=engine)

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

async def root(request: Request):
    return JSONResponse({"message": "Estoque Virtual API - Phase 1"})

async def upload_nfe(request: Request):
    """Upload and process NF-e (XML or PDF)"""
    form = await request.form()
    file = form['file']

    if not file.filename:
        return JSONResponse({"error": "No file provided"}, status_code=400)

    file_ext = file.filename.split(".")[-1].lower()

    if file_ext not in ['xml', 'pdf']:
        return JSONResponse({"error": "Apenas XML ou PDF permitidos"}, status_code=400)

    content = await file.read()

    try:
        if file_ext == "xml":
            result = NFeParsing.parse_xml(content)
        else:
            # Save temp file for OCR processing
            temp_path = os.path.join(UPLOAD_DIR, file.filename)
            with open(temp_path, "wb") as f:
                f.write(content)
            result = NFeParsing.parse_pdf_ocr(temp_path)

        if not result.get("sucesso"):
            return JSONResponse({"error": result.get('erro')}, status_code=400)

        db = SessionLocal()
        try:
            # Create NF record
            nf = NotaFiscal(
                numero_nf=result.get("numero_nf", ""),
                serie=result.get("serie", "1"),
                fornecedor=result.get("fornecedor", ""),
                data_emissao=result.get("data_emissao"),
                arquivo_original=file.filename,
                tipo_documento="nfe" if file_ext == "xml" else "pdf",
                status="processado",
                xml_processado=content.decode('utf-8', errors='ignore') if file_ext == "xml" else None
            )

            db.add(nf)
            db.flush()

            # Create items
            for item in result.get("itens", []):
                estoque_item = ItemEstoque(
                    nf_id=nf.id,
                    codigo_produto=item.get("codigo", ""),
                    descricao=item.get("descricao", ""),
                    quantidade_nf=item.get("quantidade", 0.0),
                    preco_unitario=item.get("preco", 0.0),
                    status="quarentena"
                )
                db.add(estoque_item)

            db.commit()

            return JSONResponse({
                "id": nf.id,
                "numero_nf": nf.numero_nf,
                "status": "processado",
                "itens_encontrados": len(result.get("itens", [])),
                "erros": None
            })

        finally:
            db.close()

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

async def get_nfs(request: Request):
    """List all NFs with pagination"""
    skip = int(request.query_params.get("skip", 0))
    limit = int(request.query_params.get("limit", 10))

    db = SessionLocal()
    try:
        nfs = db.query(NotaFiscal).offset(skip).limit(limit).all()
        total = db.query(NotaFiscal).count()

        items = []
        for nf in nfs:
            items.append({
                "id": nf.id,
                "numero_nf": nf.numero_nf,
                "serie": nf.serie,
                "fornecedor": nf.fornecedor,
                "data_emissao": nf.data_emissao.isoformat() if nf.data_emissao else None,
                "data_upload": nf.data_upload.isoformat() if nf.data_upload else None,
                "arquivo_original": nf.arquivo_original,
                "status": nf.status,
                "erros": nf.erros,
                "itens": [
                    {
                        "id": item.id,
                        "codigo_produto": item.codigo_produto,
                        "descricao": item.descricao,
                        "quantidade_nf": item.quantidade_nf,
                        "quantidade_confirmada": item.quantidade_confirmada,
                        "preco_unitario": item.preco_unitario,
                        "status": item.status,
                        "divergencia": item.divergencia,
                        "data_criacao": item.data_criacao.isoformat() if item.data_criacao else None,
                    }
                    for item in nf.itens
                ]
            })

        return JSONResponse({
            "total": total,
            "skip": skip,
            "limit": limit,
            "items": items
        })
    finally:
        db.close()

async def get_nf(request: Request):
    """Get NF details with items"""
    nf_id = int(request.path_params['nf_id'])

    db = SessionLocal()
    try:
        nf = db.query(NotaFiscal).filter(NotaFiscal.id == nf_id).first()

        if not nf:
            return JSONResponse({"error": "NF não encontrada"}, status_code=404)

        return JSONResponse({
            "id": nf.id,
            "numero_nf": nf.numero_nf,
            "serie": nf.serie,
            "fornecedor": nf.fornecedor,
            "data_emissao": nf.data_emissao.isoformat() if nf.data_emissao else None,
            "data_upload": nf.data_upload.isoformat() if nf.data_upload else None,
            "arquivo_original": nf.arquivo_original,
            "status": nf.status,
            "erros": nf.erros,
            "itens": [
                {
                    "id": item.id,
                    "codigo_produto": item.codigo_produto,
                    "descricao": item.descricao,
                    "quantidade_nf": item.quantidade_nf,
                    "quantidade_confirmada": item.quantidade_confirmada,
                    "preco_unitario": item.preco_unitario,
                    "status": item.status,
                    "divergencia": item.divergencia,
                    "data_criacao": item.data_criacao.isoformat() if item.data_criacao else None,
                }
                for item in nf.itens
            ]
        })
    finally:
        db.close()

routes = [
    Route("/", root, methods=["GET"]),
    Route("/api/upload-nfe", upload_nfe, methods=["POST"]),
    Route("/api/notas-fiscais", get_nfs, methods=["GET"]),
    Route("/api/notas-fiscais/{nf_id}", get_nf, methods=["GET"]),
]

app = Starlette(routes=routes)

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
