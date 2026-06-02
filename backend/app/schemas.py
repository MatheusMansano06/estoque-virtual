from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List

class ItemEstoqueBase(BaseModel):
    codigo_produto: str
    descricao: str
    quantidade_nf: float
    preco_unitario: float

class ItemEstoqueCreate(ItemEstoqueBase):
    pass

class ItemEstoqueUpdate(BaseModel):
    quantidade_confirmada: Optional[float] = None
    divergencia: Optional[str] = None

class ItemEstoqueResponse(ItemEstoqueBase):
    id: int
    nf_id: int
    quantidade_confirmada: Optional[float]
    status: str
    divergencia: Optional[str]
    data_criacao: datetime

    class Config:
        from_attributes = True

class NotaFiscalBase(BaseModel):
    numero_nf: str
    serie: str
    fornecedor: str
    tipo_documento: str

class NotaFiscalCreate(NotaFiscalBase):
    pass

class NotaFiscalResponse(NotaFiscalBase):
    id: int
    data_emissao: datetime
    data_upload: datetime
    arquivo_original: str
    status: str
    erros: Optional[str]
    itens: List[ItemEstoqueResponse]

    class Config:
        from_attributes = True

class NotaFiscalUploadResponse(BaseModel):
    id: int
    numero_nf: str
    status: str
    itens_encontrados: int
    erros: Optional[str]

class AnuncioResponse(BaseModel):
    id: int
    codigo_externo: str
    titulo: str
    marketplace: str
    preco: float
    estoque_atual: int

    class Config:
        from_attributes = True
