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
        orm_mode = True

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
        orm_mode = True

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
        orm_mode = True


# Schemas para Recomendações de Recompra
class FornecedorAlternativoResponse(BaseModel):
    nome: str
    preco_unitario: float
    lead_time_dias: int
    frequencia_compra: int
    motivo_nao_recomendado: Optional[str] = None


class RecomendacaoResponse(BaseModel):
    id: int
    urgencia: str
    sku_olist: str
    nome_produto: str
    estoque_atual: int
    quantidade_recomendada: int
    dias_ate_faltar: float
    frequencia_venda_diaria: float
    fornecedor_recomendado: str
    preco_unitario: float
    custo_total: float
    motivo: Optional[str]
    fornecedores_alternativos: List[FornecedorAlternativoResponse] = []

    class Config:
        orm_mode = True


class AnaliseDemandaResponse(BaseModel):
    vendas_ultimos_7_dias: int
    vendas_ultimos_14_dias: int
    vendas_ultimos_30_dias: int
    media_diaria: float
    desvio_padrao: float
    tendencia: str
    crescimento_semana_anterior: float
    previsao_proximos_7_dias: int


class EstoqueAtualResponse(BaseModel):
    quantidade: int
    valor_total_custo: float
    valor_total_venda: float
    cobertura_dias: float
    status: str


class FornecedorDetalhesResponse(BaseModel):
    nome: str
    preco_unitario: float
    lead_time_dias: int
    frequencia_compra: int
    ultima_compra: Optional[datetime]
    historico_precos: List[dict]
    tendencia_preco: str
    motivo_recomendacao: Optional[str] = None


class RecomendacaoDetalhadaResponse(BaseModel):
    sku: str
    nome: str
    analise_demanda: AnaliseDemandaResponse
    estoque_atual: EstoqueAtualResponse
    fornecedores: List[FornecedorDetalhesResponse]
    recomendacao_final: dict  # {"comprar_quantidade", "fornecedor", "preco_unitario", "custo_total", "prazo_entrega_dias", "data_chegada_estimada", "estoque_sera_zero_em", "cobertura_apos_compra", "margem_estimada_30_dias", "roi_30_dias"}


class ConfirmarCompraRequest(BaseModel):
    quantidade: int
    fornecedor: str
    observacoes: Optional[str] = None


class ConfirmarCompraResponse(BaseModel):
    status: str
    id_pedido: Optional[int] = None
    mensagem: str
