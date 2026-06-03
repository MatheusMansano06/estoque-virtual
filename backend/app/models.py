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
    cnpj = Column(String(20), nullable=True)
    endereco = Column(String(255), nullable=True)
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


class KitOlist(Base):
    """
    Configuração de kits: armazena qual SKU é um kit e quais SKUs compõem ele.
    Exemplo: V+RL3 é um kit composto por [V+RL3REPARO, V+RL3V]
    """
    __tablename__ = "kits_olist"

    id = Column(Integer, primary_key=True)
    # SKU do kit (ex: V+RL3)
    sku_kit = Column(String(100), unique=True, index=True)
    nome_kit = Column(String(255))  # Nome descritivo do kit
    # SKUs dos componentes separados por | (ex: "V+RL3REPARO|V+RL3V")
    skus_componentes = Column(String(500))  # Armazenar como string separada por |
    quantidade_componentes = Column(Integer)  # Quantos itens compõem o kit
    ativo = Column(Integer, default=1)  # 1=ativo, 0=inativo
    criado_em = Column(DateTime, default=datetime.utcnow)
    atualizado_em = Column(DateTime, default=datetime.utcnow)


class HistoricoVendas(Base):
    """
    Histórico de vendas/pedidos da Olist.
    Rastreia cada venda para calcular frequência, tendências e previsões de estoque.
    """
    __tablename__ = "historico_vendas"

    id = Column(Integer, primary_key=True)
    olist_sku = Column(String(100), index=True)
    olist_produto_id = Column(String(100))
    data_venda = Column(DateTime, index=True)
    quantidade = Column(Integer)
    preco_unitario = Column(Float)
    receita = Column(Float)
    marketplace = Column(String(50), default="olist")
    pedido_id = Column(String(100), nullable=True)
    data_sincronizacao = Column(DateTime, default=datetime.utcnow)
    criado_em = Column(DateTime, default=datetime.utcnow)


class FornecedorConfiguracao(Base):
    """
    Configuração e histórico de cada fornecedor.
    Rastreia lead time, contato e frequência de compra.
    """
    __tablename__ = "fornecedor_configuracao"

    id = Column(Integer, primary_key=True)
    nome_fornecedor = Column(String(255), unique=True, index=True)
    cnpj = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    telefone = Column(String(20), nullable=True)
    lead_time_dias_medio = Column(Float, nullable=True)
    lead_time_min = Column(Float, nullable=True)
    lead_time_max = Column(Float, nullable=True)
    numero_compras = Column(Integer, default=0)
    ativo = Column(Integer, default=1)
    data_ultima_compra = Column(DateTime, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    atualizado_em = Column(DateTime, default=datetime.utcnow)


class HistoricoPrecos(Base):
    """
    Histórico de preços por fornecedor e produto.
    Permite identificar tendências de preço e comparação entre fornecedores.
    """
    __tablename__ = "historico_precos"

    id = Column(Integer, primary_key=True)
    fornecedor = Column(String(255), index=True)
    codigo_produto_fornecedor = Column(String(100), index=True)
    descricao = Column(String(255), nullable=True)
    preco_unitario = Column(Float, index=True)
    quantidade = Column(Integer, nullable=True)
    data = Column(DateTime, index=True)
    nf_id = Column(Integer, ForeignKey("notas_fiscais.id"), nullable=True)
    data_criacao = Column(DateTime, default=datetime.utcnow)


class Recomendacao(Base):
    """
    Recomendações de recompra calculadas automaticamente.
    Cache das recomendações para performance e histórico.
    """
    __tablename__ = "recomendacoes"

    id = Column(Integer, primary_key=True)
    olist_sku = Column(String(100), index=True)
    codigo_produto_interno = Column(String(100), nullable=True)
    nome_produto = Column(String(255))
    estoque_atual = Column(Integer)
    quantidade_recomendada = Column(Integer)
    fornecedor_recomendado = Column(String(255))
    preco_unitario = Column(Float)
    custo_total = Column(Float)
    frequencia_venda_diaria = Column(Float)
    dias_ate_faltar = Column(Float)
    urgencia = Column(String(20))  # "critico", "moderado", "ok"
    motivo = Column(Text, nullable=True)
    data_calculo = Column(DateTime, default=datetime.utcnow)
    data_vencimento = Column(DateTime, nullable=True)
    fornecedores_alternativos = Column(Text, nullable=True)  # JSON string
    status_acao = Column(String(50), default="novo")  # "novo", "comprado", "descartado", "vencido"
    data_atualizacao = Column(DateTime, default=datetime.utcnow)
    criado_em = Column(DateTime, default=datetime.utcnow)
