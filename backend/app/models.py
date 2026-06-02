from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Enum, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime
import enum

class StatusEstoque(str, enum.Enum):
    QUARENTENA = "quarentena"
    CONFIRMADO = "confirmado"
    BLOQUEADO = "bloqueado"

class TipoDocumento(str, enum.Enum):
    NFE = "nfe"
    PDF = "pdf"

class NotaFiscal(Base):
    __tablename__ = "notas_fiscais"

    id = Column(Integer, primary_key=True)
    numero_nf = Column(String(20), unique=True, index=True)
    serie = Column(String(10))
    fornecedor = Column(String(255))
    data_emissao = Column(DateTime)
    data_upload = Column(DateTime, default=datetime.utcnow)
    arquivo_original = Column(String(255))
    tipo_documento = Column(Enum(TipoDocumento))
    xml_processado = Column(Text, nullable=True)
    status = Column(String(50), default="processando")
    erros = Column(Text, nullable=True)

    itens = relationship("ItemEstoque", back_populates="nota_fiscal", cascade="all, delete-orphan")

class ItemEstoque(Base):
    __tablename__ = "itens_estoque"

    id = Column(Integer, primary_key=True)
    nf_id = Column(Integer, ForeignKey("notas_fiscais.id"))
    codigo_produto = Column(String(100))
    descricao = Column(String(255))
    quantidade_nf = Column(Float)
    quantidade_confirmada = Column(Float, nullable=True)
    preco_unitario = Column(Float)
    status = Column(Enum(StatusEstoque), default=StatusEstoque.QUARENTENA)
    divergencia = Column(String(100), nullable=True)
    data_criacao = Column(DateTime, default=datetime.utcnow)

    # Campos para integração com Olist
    olist_produto_id = Column(String(100), nullable=True)  # ID do produto na Olist
    olist_sku = Column(String(100), nullable=True)  # SKU do anúncio na Olist
    olist_nome = Column(String(255), nullable=True)  # Nome do anúncio na Olist
    vinculado_em = Column(DateTime, nullable=True)  # Quando foi vinculado
    estoque_olist_atualizado_em = Column(DateTime, nullable=True)  # Última atualização de estoque

    nota_fiscal = relationship("NotaFiscal", back_populates="itens")

class Anuncio(Base):
    __tablename__ = "anuncios"

    id = Column(Integer, primary_key=True)
    codigo_externo = Column(String(100), unique=True)
    titulo = Column(String(255))
    descricao = Column(Text)
    marketplace = Column(String(50))  # olist, mercado_livre, etc
    preco = Column(Float)
    estoque_atual = Column(Integer, default=0)
    data_atualizacao = Column(DateTime, default=datetime.utcnow)

class ConfirmacaoEstoque(Base):
    __tablename__ = "confirmacoes_estoque"

    id = Column(Integer, primary_key=True)
    item_estoque_id = Column(Integer, ForeignKey("itens_estoque.id"))
    quantidade_confirmada = Column(Float)
    divergencia = Column(String(255), nullable=True)
    data_confirmacao = Column(DateTime, default=datetime.utcnow)
    vinculado_olist = Column(String(100), nullable=True)  # SKU do anúncio na Olist
    observacoes = Column(Text, nullable=True)


class VinculoOlist(Base):
    """
    Memória de vínculos: de-para entre a descrição/código de um produto
    na nota fiscal (que varia por fornecedor) e o anúncio na Olist.
    Um mesmo anúncio Olist pode ter vários apelidos (linhas) diferentes.
    """
    __tablename__ = "vinculos_olist"

    id = Column(Integer, primary_key=True)
    # Lado do fornecedor (vem da NF) - usado para casar em notas futuras
    nf_codigo = Column(String(100), index=True, nullable=True)
    nf_descricao = Column(String(255), index=True)
    # Lado da Olist (o anúncio que foi vinculado)
    olist_produto_id = Column(String(100))
    olist_sku = Column(String(100))
    olist_nome = Column(String(255))
    olist_preco = Column(Float, default=0)
    # Metadados
    vezes_usado = Column(Integer, default=1)
    criado_em = Column(DateTime, default=datetime.utcnow)
    atualizado_em = Column(DateTime, default=datetime.utcnow)
