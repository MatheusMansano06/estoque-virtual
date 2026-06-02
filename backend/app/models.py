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
