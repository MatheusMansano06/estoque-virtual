from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import engine, Base, get_db
import os
from dotenv import load_dotenv

from app.models import NotaFiscal, ItemEstoque
from app.schemas import NotaFiscalUploadResponse, NotaFiscalResponse
from app.utils.nfe_parser import NFeParsing

load_dotenv()

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Estoque Virtual",
    description="Sistema de entrada de estoque via NF-e",
    version="0.1.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.get("/")
async def root():
    return {"message": "Estoque Virtual API - Phase 1"}

@app.post("/api/upload-nfe", response_model=NotaFiscalUploadResponse)
async def upload_nfe(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload and process NF-e (XML or PDF)"""

    # Validate file type
    allowed_ext = {"xml", "pdf"}
    file_ext = file.filename.split(".")[-1].lower()

    if file_ext not in allowed_ext:
        raise HTTPException(status_code=400, detail="Apenas XML ou PDF permitidos")

    try:
        # Read file
        content = await file.read()

        # Parse based on type
        if file_ext == "xml":
            result = NFeParsing.parse_xml(content)
        else:  # PDF
            # Save temp file for OCR processing
            temp_path = os.path.join(UPLOAD_DIR, file.filename)
            with open(temp_path, "wb") as f:
                f.write(content)
            result = NFeParsing.parse_pdf_ocr(temp_path)

        if not result.get("sucesso"):
            raise HTTPException(status_code=400, detail=f"Erro ao processar: {result.get('erro')}")

        # Create NF record in database
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
        db.flush()  # Get the ID

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

        return NotaFiscalUploadResponse(
            id=nf.id,
            numero_nf=nf.numero_nf,
            status="processado",
            itens_encontrados=len(result.get("itens", [])),
            erros=None
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/notas-fiscais/{nf_id}", response_model=NotaFiscalResponse)
async def get_nf(nf_id: int, db: Session = Depends(get_db)):
    """Get NF details with items"""
    nf = db.query(NotaFiscal).filter(NotaFiscal.id == nf_id).first()

    if not nf:
        raise HTTPException(status_code=404, detail="NF não encontrada")

    return nf

@app.get("/api/notas-fiscais")
async def list_nfs(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """List all NFs with pagination"""
    nfs = db.query(NotaFiscal).offset(skip).limit(limit).all()
    total = db.query(NotaFiscal).count()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": nfs
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
