from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse, FileResponse, RedirectResponse, HTMLResponse, Response
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from sqlalchemy.orm import Session
from database import engine, Base, SessionLocal
import os
import json
from datetime import datetime
import uuid
import urllib.request
import urllib.parse
from dotenv import load_dotenv
from difflib import SequenceMatcher
import io

from app.models import (
    NotaFiscal, ItemEstoque, ConfirmacaoEstoque, StatusEstoque, VinculoOlist,
    Fornecedor, HistoricoCompra, ConfiguracaoEstoqueMinimo, NotificacaoFornecedor
)
from app.utils.nfe_parser import NFeParsing
from app.utils.nfe_pdf_generator import NFePDFGenerator
from app.utils.fornecedores import garantir_fornecedor, linkar_fornecedor_nf
from app.integracoes_olist import olist
from app.jobs import iniciar_scheduler

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

# Create tables
Base.metadata.create_all(bind=engine)

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Cache para armazenar access_token da Olist
olist_access_token_cache = {"token": None, "expires_at": None}

def obter_olist_access_token():
    """Obtém access_token da Olist usando OAuth"""
    global olist_access_token_cache

    from datetime import datetime, timedelta

    # Se temos token em cache e ainda está válido, usa ele
    if olist_access_token_cache["token"] and olist_access_token_cache["expires_at"]:
        if datetime.utcnow() < datetime.fromisoformat(olist_access_token_cache["expires_at"]):
            return olist_access_token_cache["token"]

    # Caso contrário, faz requisição para obter novo token
    client_id = os.getenv("OLIST_CLIENT_ID", "")
    client_secret = os.getenv("OLIST_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        return None

    try:
        url = "https://accounts.olist.com/api/v1/token"
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials"
        }

        post_data = json.dumps(data).encode('utf-8')
        headers = {
            "Content-Type": "application/json"
        }

        req = urllib.request.Request(url, data=post_data, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=10) as response:
            resposta = json.loads(response.read().decode('utf-8'))

            if "access_token" in resposta:
                token = resposta["access_token"]
                expires_in = resposta.get("expires_in", 3600)
                expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()

                olist_access_token_cache["token"] = token
                olist_access_token_cache["expires_at"] = expires_at

                print(f"[INFO] Novo token Olist obtido, expira em {expires_in}s")
                return token
    except Exception as e:
        print(f"[ERRO] Falha ao obter token Olist: {e}")
        return None

def serialize_item(item):
    """Serializa um ItemEstoque para JSON, incluindo dados Olist"""
    return {
        "id": item.id,
        "codigo_produto": item.codigo_produto,
        "descricao": item.descricao,
        "quantidade_nf": item.quantidade_nf,
        "quantidade_confirmada": item.quantidade_confirmada,
        "preco_unitario": item.preco_unitario,
        "status": item.status.value if hasattr(item.status, "value") else item.status,
        "divergencia": item.divergencia,
        "data_criacao": item.data_criacao.isoformat() if item.data_criacao else None,
        # Dados de integração Olist
        "olist_produto_id": item.olist_produto_id,
        "olist_sku": item.olist_sku,
        "olist_nome": item.olist_nome,
        "vinculado_em": item.vinculado_em.isoformat() if item.vinculado_em else None,
        "estoque_olist_atualizado_em": item.estoque_olist_atualizado_em.isoformat() if item.estoque_olist_atualizado_em else None,
    }


def serialize_nota(nf):
    """Serializa uma NotaFiscal (com itens) para JSON"""
    return {
        "id": nf.id,
        "numero_nf": nf.numero_nf,
        "serie": nf.serie,
        "fornecedor": nf.fornecedor,
        "cnpj": nf.cnpj,
        "endereco": nf.endereco,
        "data_emissao": nf.data_emissao.isoformat() if nf.data_emissao else None,
        "data_upload": nf.data_upload.isoformat() if nf.data_upload else None,
        "arquivo_original": nf.arquivo_original,
        "status": nf.status,
        "erros": nf.erros,
        "itens": [serialize_item(item) for item in nf.itens],
    }


def similaridade(str1: str, str2: str) -> float:
    """Calcula similaridade entre duas strings (0 a 1)"""
    return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()


def auto_buscar_vinculo(db: Session, item: ItemEstoque):
    """
    Busca automáticamente um vínculo para o item.
    Retorna (vinculo_encontrado, confianca)
    - Match exato por código: confiança 100%
    - Match exato por descrição: confiança 95%
    - Match por similaridade (>80%): confiança varia
    """
    # 1) Tenta match exato por código
    if item.codigo_produto:
        vinculo = db.query(VinculoOlist).filter(
            VinculoOlist.nf_codigo == item.codigo_produto
        ).order_by(VinculoOlist.vezes_usado.desc()).first()
        if vinculo:
            return vinculo, 1.0  # 100% confiança

    # 2) Tenta match exato por descrição
    if item.descricao:
        vinculo = db.query(VinculoOlist).filter(
            VinculoOlist.nf_descricao == item.descricao
        ).order_by(VinculoOlist.vezes_usado.desc()).first()
        if vinculo:
            return vinculo, 0.95  # 95% confiança

    # 3) Tenta fuzzy match por descrição (acima de 80%)
    if item.descricao:
        todos_vinculos = db.query(VinculoOlist).all()
        best_match = None
        best_score = 0
        for v in todos_vinculos:
            score = similaridade(item.descricao, v.nf_descricao)
            if score > best_score:
                best_score = score
                best_match = v
        if best_match and best_score >= 0.80:
            return best_match, best_score

    return None, 0


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
                cnpj=result.get("cnpj", ""),
                endereco=result.get("endereco", ""),
                data_emissao=result.get("data_emissao"),
                arquivo_original=file.filename,
                tipo_documento="nfe" if file_ext == "xml" else "pdf",
                status="processado",
                xml_processado=content.decode('utf-8', errors='ignore') if file_ext == "xml" else None
            )

            db.add(nf)
            db.flush()

            # Garantir que fornecedor existe e linkar à nota fiscal
            linkar_fornecedor_nf(db, nf)

            # Create items
            items_criados = []
            sugestoes_vinculacao = []

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
                db.flush()  # Para obter o ID do item
                items_criados.append(estoque_item)

            db.commit()

            # Auto-vinculação: buscar sugestões para cada item
            for estoque_item in items_criados:
                vinculo, confianca = auto_buscar_vinculo(db, estoque_item)
                if vinculo:
                    # Auto-vincular se confiança >= 95% (match exato)
                    if confianca >= 0.95:
                        estoque_item.olist_produto_id = vinculo.olist_produto_id
                        estoque_item.olist_sku = vinculo.olist_sku
                        estoque_item.olist_nome = vinculo.olist_nome
                        estoque_item.vinculado_em = datetime.utcnow()
                        db.commit()
                    else:
                        # Sugerir se confiança entre 80% e 95% (fuzzy match)
                        sugestoes_vinculacao.append({
                            "item_id": estoque_item.id,
                            "descricao": estoque_item.descricao,
                            "confianca": round(confianca * 100, 1),
                            "sugestao": {
                                "olist_produto_id": vinculo.olist_produto_id,
                                "olist_sku": vinculo.olist_sku,
                                "olist_nome": vinculo.olist_nome,
                                "olist_preco": vinculo.olist_preco,
                                "vezes_usado": vinculo.vezes_usado
                            }
                        })

            return JSONResponse({
                "id": nf.id,
                "numero_nf": nf.numero_nf,
                "status": "processado",
                "itens_encontrados": len(result.get("itens", [])),
                "sugestoes_vinculacao": sugestoes_vinculacao,
                "erros": None
            })

        finally:
            db.close()

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

async def get_nfs(request: Request):
    """List all NFs with pagination"""
    skip = int(request.query_params.get("skip", 0))
    limit = int(request.query_params.get("limit", 500))

    db = SessionLocal()
    try:
        nfs = db.query(NotaFiscal).order_by(NotaFiscal.data_upload.desc()).offset(skip).limit(limit).all()
        total = db.query(NotaFiscal).count()

        items = [serialize_nota(nf) for nf in nfs]

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

        return JSONResponse(serialize_nota(nf))
    finally:
        db.close()

async def get_estoque_virtual(request: Request):
    """Get consolidated virtual inventory - sum of all products"""
    db = SessionLocal()
    try:
        # Get all items grouped by product description
        items = db.query(ItemEstoque).all()

        # Consolidate by description
        estoque_consolidado = {}
        for item in items:
            desc = item.descricao
            if desc not in estoque_consolidado:
                estoque_consolidado[desc] = {
                    "id_item": item.id,
                    "descricao": desc,
                    "codigo_produto": item.codigo_produto,
                    "quantidade_total": 0,
                    "quantidade_confirmada": 0,
                    "preco_unitario": item.preco_unitario,
                    "notas_fiscais": []
                }

            estoque_consolidado[desc]["quantidade_total"] += item.quantidade_nf
            if item.quantidade_confirmada:
                estoque_consolidado[desc]["quantidade_confirmada"] += item.quantidade_confirmada

            # Add NF reference
            nf = item.nota_fiscal
            estoque_consolidado[desc]["notas_fiscais"].append({
                "numero_nf": nf.numero_nf,
                "serie": nf.serie,
                "fornecedor": nf.fornecedor,
                "quantidade": item.quantidade_nf
            })

        # Convert to list
        produtos = list(estoque_consolidado.values())

        return JSONResponse({
            "total_produtos": len(produtos),
            "produtos": produtos
        })
    finally:
        db.close()

async def confirmar_estoque(request: Request):
    """Confirm received quantity and register divergence"""
    db = SessionLocal()
    try:
        data = await request.json()
        item_id = data.get("item_id")
        quantidade_confirmada = data.get("quantidade_confirmada", 0)
        divergencia = data.get("divergencia", None)
        observacoes = data.get("observacoes", "")

        item = db.query(ItemEstoque).filter(ItemEstoque.id == item_id).first()
        if not item:
            return JSONResponse({"error": "Item não encontrado"}, status_code=404)

        # Update item with confirmation
        item.quantidade_confirmada = quantidade_confirmada
        item.divergencia = divergencia
        # Marcar como conferido (confirmado) quando nao ha divergencia
        if not divergencia:
            item.status = StatusEstoque.CONFIRMADO

        # Create confirmation record
        confirmacao = ConfirmacaoEstoque(
            item_estoque_id=item_id,
            quantidade_confirmada=quantidade_confirmada,
            divergencia=divergencia,
            observacoes=observacoes
        )
        db.add(confirmacao)

        # Se confirmado SEM divergência, criar entrada no histórico de compras
        if not divergencia and quantidade_confirmada > 0:
            nf = item.nota_fiscal
            if nf:
                # Encontrar ou criar fornecedor baseado no nome da NF
                fornecedor = db.query(Fornecedor).filter(
                    Fornecedor.nome == nf.fornecedor
                ).first()

                if not fornecedor:
                    # Auto-criar fornecedor se não existe
                    fornecedor = Fornecedor(
                        nome=nf.fornecedor,
                        cnpj=nf.cnpj,
                        endereco=nf.endereco,
                        ativo=1
                    )
                    db.add(fornecedor)
                    db.flush()

                # Criar entrada no histórico de compras
                historico = HistoricoCompra(
                    fornecedor_id=fornecedor.id,
                    nf_id=nf.id,
                    produto_codigo=item.codigo_produto,
                    produto_descricao=item.descricao,
                    quantidade=quantidade_confirmada,
                    nf_numero=nf.numero_nf
                )
                db.add(historico)

                # Linkar fornecedor à nota fiscal se não tiver
                if not nf.fornecedor_id:
                    nf.fornecedor_id = fornecedor.id

        db.commit()

        return JSONResponse({
            "success": True,
            "id": confirmacao.id,
            "quantidade_confirmada": quantidade_confirmada,
            "divergencia": divergencia
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()

async def get_historico_confirmacao(request: Request):
    """Get confirmation history for a product"""
    item_id = int(request.path_params.get('item_id', 0))
    db = SessionLocal()
    try:
        confirmacoes = db.query(ConfirmacaoEstoque).filter(
            ConfirmacaoEstoque.item_estoque_id == item_id
        ).order_by(ConfirmacaoEstoque.data_confirmacao.desc()).all()

        historico = [{
            "id": c.id,
            "quantidade_confirmada": c.quantidade_confirmada,
            "divergencia": c.divergencia,
            "data_confirmacao": c.data_confirmacao.isoformat() if c.data_confirmacao else None,
            "vinculado_olist": c.vinculado_olist,
            "observacoes": c.observacoes
        } for c in confirmacoes]

        return JSONResponse({
            "historico": historico,
            "total": len(historico)
        })
    finally:
        db.close()

async def registrar_divergencia(request: Request):
    """Register divergence and send WhatsApp message"""
    db = SessionLocal()
    try:
        data = await request.json()
        item_id = data.get("item_id")
        quantidade_confirmada = data.get("quantidade_confirmada", 0)
        tipo_divergencia = data.get("tipo_divergencia", "a_menos")
        observacoes = data.get("observacoes", "")
        mensagem_whatsapp = data.get("mensagem_whatsapp", "")

        item = db.query(ItemEstoque).filter(ItemEstoque.id == item_id).first()
        if not item:
            return JSONResponse({"error": "Item não encontrado"}, status_code=404)

        # Update item with confirmation
        item.quantidade_confirmada = quantidade_confirmada
        item.divergencia = tipo_divergencia
        # Mark as bloqueado when there's a divergence (needs review)
        item.status = StatusEstoque.BLOQUEADO

        # Create confirmation record
        confirmacao = ConfirmacaoEstoque(
            item_estoque_id=item_id,
            quantidade_confirmada=quantidade_confirmada,
            divergencia=tipo_divergencia,
            observacoes=observacoes
        )

        db.add(confirmacao)
        db.commit()

        numero_whatsapp = "19978149245"  # Número padrão

        # Log seguro: evita UnicodeEncodeError no console do Windows (cp1252)
        # quando a mensagem contem emojis/acentos. O envio real e feito no
        # frontend via link wa.me.
        try:
            print(f"[DIVERGENCIA] item={item_id} tipo={tipo_divergencia} "
                  f"qtd_confirmada={quantidade_confirmada} destino_whatsapp={numero_whatsapp}")
        except Exception:
            pass

        return JSONResponse({
            "sucesso": True,
            "mensagem": "Divergência registrada com sucesso",
            "numero_whatsapp": numero_whatsapp,
            "confirmacao_id": confirmacao.id
        })

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()

# ===== NOVOS ENDPOINTS =====

async def nf_tem_divergencias(request: Request):
    """Verifica se uma nota fiscal tem itens com divergência"""
    nf_id = int(request.path_params['nf_id'])
    db = SessionLocal()
    try:
        itens_com_divergencia = db.query(ItemEstoque).filter(
            ItemEstoque.nf_id == nf_id,
            ItemEstoque.divergencia != None
        ).count()

        return JSONResponse({
            "nf_id": nf_id,
            "tem_divergencias": itens_com_divergencia > 0,
            "quantidade": itens_com_divergencia
        })
    finally:
        db.close()

async def listar_divergencias(request: Request):
    """Lista todas as divergências registradas"""
    db = SessionLocal()
    try:
        divergencias = db.query(ItemEstoque, NotaFiscal).filter(
            ItemEstoque.nf_id == NotaFiscal.id,
            ItemEstoque.divergencia != None
        ).all()

        items = []
        for item, nf in divergencias:
            items.append({
                "item_id": item.id,
                "numero_nf": nf.numero_nf,
                "serie": nf.serie,
                "fornecedor": nf.fornecedor,
                "produto": item.descricao,
                "codigo": item.codigo_produto,
                "tipo_divergencia": item.divergencia,
                "quantidade_nf": item.quantidade_nf,
                "quantidade_confirmada": item.quantidade_confirmada,
                "data_registro": item.data_criacao.isoformat() if item.data_criacao else None
            })

        return JSONResponse({
            "total": len(items),
            "divergencias": items
        })
    finally:
        db.close()

async def resolver_divergencia(request: Request):
    """Marca uma divergência como resolvida"""
    db = SessionLocal()
    try:
        data = await request.json()
        item_id = data.get("item_id")

        item = db.query(ItemEstoque).filter(ItemEstoque.id == item_id).first()
        if not item:
            return JSONResponse({"error": "Item não encontrado"}, status_code=404)

        # Marcar como confirmado (resolvido)
        item.status = StatusEstoque.CONFIRMADO
        item.divergencia = None
        db.commit()

        return JSONResponse({
            "sucesso": True,
            "mensagem": "Divergência marcada como resolvida"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()

async def deletar_divergencia(request: Request):
    """Deleta uma divergência"""
    db = SessionLocal()
    try:
        data = await request.json()
        item_id = data.get("item_id")

        item = db.query(ItemEstoque).filter(ItemEstoque.id == item_id).first()
        if not item:
            return JSONResponse({"error": "Item não encontrado"}, status_code=404)

        # Voltar para quarentena (como se não tivesse sido conferido)
        item.status = StatusEstoque.QUARENTENA
        item.divergencia = None
        item.quantidade_confirmada = None
        db.commit()

        return JSONResponse({
            "sucesso": True,
            "mensagem": "Divergência deletada com sucesso"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()

async def adicionar_produto_manual(request: Request):
    """Registra um produto adicionado manualmente (fornecedor mandou errado)"""
    db = SessionLocal()
    try:
        data = await request.json()
        nf_id = data.get("nf_id")
        codigo_recebido = data.get("codigo_recebido")
        descricao_recebida = data.get("descricao_recebida")
        quantidade = data.get("quantidade", 1)
        preco = data.get("preco", 0)

        item_manual = ItemEstoque(
            nf_id=nf_id,
            codigo_produto=codigo_recebido,
            descricao=descricao_recebida,
            quantidade_nf=quantidade,
            quantidade_confirmada=quantidade,
            preco_unitario=preco,
            status=StatusEstoque.CONFIRMADO,
            divergencia="produto_substituido",
            data_criacao=datetime.utcnow()
        )

        db.add(item_manual)
        db.commit()

        return JSONResponse({
            "sucesso": True,
            "item_id": item_manual.id,
            "mensagem": "Produto manual adicionado"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()

async def buscar_produtos_olist(request: Request):
    """Busca produtos na Olist via API v3 (OAuth2)"""
    try:
        query = request.query_params.get("q", "")

        if not query or len(query) < 1:
            return JSONResponse({
                "produtos": [],
                "total": 0,
                "mensagem": "Digite ao menos 1 caractere para buscar"
            })

        # Verificar se está autorizado
        if not olist.get_access_token():
            print("[BUSCA] Olist nao autorizado")
            return JSONResponse({
                "produtos": [],
                "total": 0,
                "termo_busca": query,
                "nao_autorizado": True,
                "url_autorizacao": "http://localhost:8000/api/olist/conectar",
                "mensagem": "Conecte-se à Olist primeiro (acesse /api/olist/conectar)"
            })

        # Buscar via API v3
        print(f"[BUSCA] Buscando na Olist: {query}")
        produtos = olist.buscar_produtos(query)

        if produtos:
            return JSONResponse({
                "produtos": produtos,
                "total": len(produtos),
                "termo_busca": query,
                "metodo": "oauth2_v3"
            })

        # Nenhum produto encontrado (mas API funcionou)
        return JSONResponse({
            "produtos": [],
            "total": 0,
            "termo_busca": query,
            "formulario_manual": True,
            "mensagem": f"Nenhum produto encontrado com '{query}'."
        })

    except Exception as e:
        print(f"[ERRO] Busca: {str(e)}")
        return JSONResponse({
            "produtos": [],
            "total": 0,
            "formulario_manual": True,
            "erro": str(e)
        })


async def listar_produtos_olist(request: Request):
    """Lista todos os produtos na Olist"""
    try:
        print("[LISTA] Listando todos os produtos da Olist")
        produtos = olist.listar_todos_produtos(limite=100)

        return JSONResponse({
            "produtos": produtos,
            "total": len(produtos),
            "metodo": "list_all"
        })
    except Exception as e:
        print(f"[ERRO] Listagem: {str(e)}")
        return JSONResponse({
            "produtos": [],
            "total": 0,
            "erro": str(e)
        })


# ===== NOVOS ENDPOINTS - INTEGRAÇÃO OLIST =====

async def olist_status(request: Request):
    """Retorna status da integração Olist"""
    status = olist.status()
    return JSONResponse(status)


async def olist_listar_anuncios(request: Request):
    """Lista anúncios (produtos publicados) da Olist"""
    anuncios = olist.listar_anuncios(limite=100)

    return JSONResponse({
        "total": len(anuncios),
        "anuncios": anuncios
    })


async def vincular_produto_olist(request: Request):
    """Vincula um produto da NF com um anúncio da Olist"""
    db = SessionLocal()
    try:
        data = await request.json()
        item_id = data.get("item_id")
        olist_produto_id = data.get("olist_produto_id")
        olist_sku = data.get("olist_sku", "")
        olist_nome = data.get("olist_nome", "")

        item = db.query(ItemEstoque).filter(ItemEstoque.id == item_id).first()
        if not item:
            return JSONResponse({"error": "Item não encontrado"}, status_code=404)

        # Salvar vinculação no item
        item.olist_produto_id = olist_produto_id
        item.olist_sku = olist_sku
        item.olist_nome = olist_nome
        item.vinculado_em = datetime.utcnow()

        # MEMÓRIA DE VÍNCULOS: salva o de-para (descricao/codigo do fornecedor -> anúncio Olist)
        # para sugerir automaticamente em notas futuras com a mesma descrição/código.
        olist_preco = float(data.get("olist_preco", 0) or 0)
        vinculo = db.query(VinculoOlist).filter(
            VinculoOlist.nf_descricao == item.descricao,
            VinculoOlist.olist_produto_id == str(olist_produto_id)
        ).first()

        if vinculo:
            # Já existe esse de-para: atualiza e conta uso
            vinculo.nf_codigo = item.codigo_produto
            vinculo.olist_sku = olist_sku
            vinculo.olist_nome = olist_nome
            vinculo.olist_preco = olist_preco
            vinculo.vezes_usado = (vinculo.vezes_usado or 1) + 1
            vinculo.atualizado_em = datetime.utcnow()
        else:
            vinculo = VinculoOlist(
                nf_codigo=item.codigo_produto,
                nf_descricao=item.descricao,
                olist_produto_id=str(olist_produto_id),
                olist_sku=olist_sku,
                olist_nome=olist_nome,
                olist_preco=olist_preco,
                vezes_usado=1,
            )
            db.add(vinculo)

        db.commit()

        return JSONResponse({
            "sucesso": True,
            "mensagem": f"Produto vinculado: {olist_nome}",
            "item_id": item_id,
            "olist_produto_id": olist_produto_id
        })

    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


async def aceitar_sugestao_vinculo(request: Request):
    """Aceita uma sugestão de vinculação automática (fuzzy match)"""
    db = SessionLocal()
    try:
        data = await request.json()
        item_id = data.get("item_id")
        olist_produto_id = data.get("olist_produto_id")
        olist_sku = data.get("olist_sku", "")
        olist_nome = data.get("olist_nome", "")
        olist_preco = float(data.get("olist_preco", 0) or 0)

        item = db.query(ItemEstoque).filter(ItemEstoque.id == item_id).first()
        if not item:
            return JSONResponse({"error": "Item não encontrado"}, status_code=404)

        # Vincular item
        item.olist_produto_id = olist_produto_id
        item.olist_sku = olist_sku
        item.olist_nome = olist_nome
        item.vinculado_em = datetime.utcnow()

        # Atualizar memória de vínculos
        vinculo = db.query(VinculoOlist).filter(
            VinculoOlist.nf_descricao == item.descricao,
            VinculoOlist.olist_produto_id == str(olist_produto_id)
        ).first()

        if vinculo:
            vinculo.nf_codigo = item.codigo_produto
            vinculo.vezes_usado = (vinculo.vezes_usado or 1) + 1
            vinculo.atualizado_em = datetime.utcnow()
        else:
            vinculo = VinculoOlist(
                nf_codigo=item.codigo_produto,
                nf_descricao=item.descricao,
                olist_produto_id=str(olist_produto_id),
                olist_sku=olist_sku,
                olist_nome=olist_nome,
                olist_preco=olist_preco,
                vezes_usado=1,
            )
            db.add(vinculo)

        db.commit()

        return JSONResponse({
            "sucesso": True,
            "mensagem": f"Sugestão aceita: {olist_nome}",
            "item_id": item_id
        })

    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


async def atualizar_estoque_olist(request: Request):
    """Atualiza estoque do produto na Olist (entrada de mercadoria da NF)"""
    db = SessionLocal()
    try:
        data = await request.json()
        item_id = data.get("item_id")
        quantidade = data.get("quantidade", 0)  # quantidade a ADICIONAR (entrada)
        tipo = data.get("tipo", "E")  # E=Entrada (padrao), B=Balanco, S=Saida

        item = db.query(ItemEstoque).filter(ItemEstoque.id == item_id).first()
        if not item:
            return JSONResponse({"error": "Item não encontrado"}, status_code=404)

        if not item.olist_produto_id:
            return JSONResponse({
                "error": "Produto não está vinculado à Olist"
            }, status_code=400)

        # Chamar API para atualizar estoque (entrada da NF)
        sucesso = olist.atualizar_estoque(
            item.olist_produto_id,
            quantidade=float(quantidade),
            tipo=tipo,
            preco_unitario=float(item.preco_unitario or 0)
        )

        if sucesso:
            item.estoque_olist_atualizado_em = datetime.utcnow()
            db.commit()

            return JSONResponse({
                "sucesso": True,
                "mensagem": f"Entrada de {quantidade} unidades registrada na Olist",
                "olist_produto_id": item.olist_produto_id
            })
        else:
            return JSONResponse({
                "error": "Falha ao atualizar estoque na Olist"
            }, status_code=500)

    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()

async def olist_sugestao_vinculo(request: Request):
    """
    Dado o código/descrição de um produto da NF, retorna o anúncio Olist
    que já foi vinculado antes a esse mesmo produto (se existir).
    Casa por código exato OU descrição exata.
    """
    codigo = request.query_params.get("codigo", "").strip()
    descricao = request.query_params.get("descricao", "").strip()

    db = SessionLocal()
    try:
        vinculo = None
        # 1) Tenta por código do fornecedor (mais confiável)
        if codigo:
            vinculo = db.query(VinculoOlist).filter(
                VinculoOlist.nf_codigo == codigo
            ).order_by(VinculoOlist.vezes_usado.desc()).first()
        # 2) Se não achou, tenta por descrição exata
        if not vinculo and descricao:
            vinculo = db.query(VinculoOlist).filter(
                VinculoOlist.nf_descricao == descricao
            ).order_by(VinculoOlist.vezes_usado.desc()).first()

        if not vinculo:
            return JSONResponse({"encontrado": False})

        return JSONResponse({
            "encontrado": True,
            "vinculo": {
                "id": vinculo.id,
                "nf_codigo": vinculo.nf_codigo,
                "nf_descricao": vinculo.nf_descricao,
                "olist_produto_id": vinculo.olist_produto_id,
                "olist_sku": vinculo.olist_sku,
                "olist_nome": vinculo.olist_nome,
                "olist_preco": vinculo.olist_preco,
                "vezes_usado": vinculo.vezes_usado,
            }
        })
    finally:
        db.close()


async def olist_listar_vinculos(request: Request):
    """Lista todos os vínculos salvos (de-para fornecedor -> Olist)"""
    db = SessionLocal()
    try:
        vinculos = db.query(VinculoOlist).order_by(VinculoOlist.atualizado_em.desc()).all()
        return JSONResponse({
            "total": len(vinculos),
            "vinculos": [{
                "id": v.id,
                "nf_codigo": v.nf_codigo,
                "nf_descricao": v.nf_descricao,
                "olist_produto_id": v.olist_produto_id,
                "olist_sku": v.olist_sku,
                "olist_nome": v.olist_nome,
                "olist_preco": v.olist_preco,
                "vezes_usado": v.vezes_usado,
                "criado_em": v.criado_em.isoformat() if v.criado_em else None,
            } for v in vinculos]
        })
    finally:
        db.close()


async def olist_deletar_vinculo(request: Request):
    """Remove um vínculo salvo da memória"""
    db = SessionLocal()
    try:
        data = await request.json()
        vinculo_id = data.get("id")
        v = db.query(VinculoOlist).filter(VinculoOlist.id == vinculo_id).first()
        if not v:
            return JSONResponse({"error": "Vínculo não encontrado"}, status_code=404)
        db.delete(v)
        db.commit()
        return JSONResponse({"sucesso": True, "mensagem": "Vínculo removido"})
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


async def excluir_nota_fiscal(request: Request):
    """Exclui uma nota fiscal e todos os seus itens"""
    db = SessionLocal()
    try:
        data = await request.json()
        nf_id = data.get("nf_id")

        nf = db.query(NotaFiscal).filter(NotaFiscal.id == nf_id).first()
        if not nf:
            return JSONResponse({"error": "Nota fiscal não encontrada"}, status_code=404)

        # Excluir arquivo se existir
        try:
            arquivo_path = os.path.join(UPLOAD_DIR, nf.arquivo_original)
            if os.path.exists(arquivo_path):
                os.remove(arquivo_path)
        except:
            pass

        # Excluir nota (cascata deleta itens)
        db.delete(nf)
        db.commit()

        return JSONResponse({
            "sucesso": True,
            "mensagem": f"Nota fiscal #{nf.numero_nf} excluída com sucesso"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


async def excluir_multiplas_notas(request: Request):
    """Exclui múltiplas notas fiscais"""
    db = SessionLocal()
    try:
        data = await request.json()
        nf_ids = data.get("nf_ids", [])

        if not nf_ids:
            return JSONResponse({"error": "Nenhuma nota selecionada"}, status_code=400)

        deletadas = 0
        for nf_id in nf_ids:
            nf = db.query(NotaFiscal).filter(NotaFiscal.id == nf_id).first()
            if nf:
                try:
                    arquivo_path = os.path.join(UPLOAD_DIR, nf.arquivo_original)
                    if os.path.exists(arquivo_path):
                        os.remove(arquivo_path)
                except:
                    pass
                db.delete(nf)
                deletadas += 1

        db.commit()

        return JSONResponse({
            "sucesso": True,
            "mensagem": f"{deletadas} nota(s) excluída(s) com sucesso"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


async def baixar_nota_fiscal(request: Request):
    """Baixa o arquivo original da nota fiscal"""
    nf_id = int(request.path_params['nf_id'])

    db = SessionLocal()
    try:
        nf = db.query(NotaFiscal).filter(NotaFiscal.id == nf_id).first()
        if not nf:
            return JSONResponse({"error": "Nota fiscal não encontrada"}, status_code=404)

        arquivo_path = os.path.join(UPLOAD_DIR, nf.arquivo_original)
        if not os.path.exists(arquivo_path):
            return JSONResponse({"error": "Arquivo não encontrado"}, status_code=404)

        return FileResponse(
            arquivo_path,
            filename=nf.arquivo_original,
            media_type='application/octet-stream'
        )
    finally:
        db.close()


async def gerar_pdf_nota_fiscal(request: Request):
    """Gera e baixa um PDF formatado da nota fiscal"""
    nf_id = int(request.path_params['nf_id'])

    db = SessionLocal()
    try:
        nf = db.query(NotaFiscal).filter(NotaFiscal.id == nf_id).first()
        if not nf:
            return JSONResponse({"error": "Nota fiscal não encontrada"}, status_code=404)

        # Se o arquivo é XML, gerar PDF a partir dele
        if nf.tipo_documento == "nfe" and nf.xml_processado:
            pdf_bytes = NFePDFGenerator.gerar_pdf(nf.xml_processado if isinstance(nf.xml_processado, bytes) else nf.xml_processado.encode('utf-8', errors='ignore'))
            if pdf_bytes:
                return Response(
                    content=bytes(pdf_bytes) if isinstance(pdf_bytes, bytearray) else pdf_bytes,
                    media_type='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="NF-{nf.numero_nf}.pdf"'}
                )

        # Se não conseguiu gerar PDF, retorna o arquivo original
        arquivo_path = os.path.join(UPLOAD_DIR, nf.arquivo_original)
        if not os.path.exists(arquivo_path):
            return JSONResponse({"error": "Arquivo não encontrado"}, status_code=404)

        return FileResponse(
            arquivo_path,
            filename=f"NF-{nf.numero_nf}.pdf" if nf.arquivo_original.endswith('.pdf') else nf.arquivo_original,
            media_type='application/pdf' if nf.arquivo_original.endswith('.pdf') else 'application/octet-stream'
        )

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


async def olist_conectar(request: Request):
    """Redireciona o usuário para autorizar o app no Olist"""
    if not olist.enabled:
        return HTMLResponse(
            "<h2>Erro: Credenciais OLIST_CLIENT_ID/SECRET não configuradas no .env</h2>",
            status_code=400
        )
    url = olist.get_authorization_url()
    return RedirectResponse(url)


async def olist_callback(request: Request):
    """Recebe o código de autorização do Olist e troca por token"""
    code = request.query_params.get("code")
    erro = request.query_params.get("error")

    if erro:
        return HTMLResponse(f"""
            <html><body style="font-family:sans-serif;text-align:center;padding:50px">
            <h2 style="color:#d32f2f">Autorizacao negada</h2>
            <p>Erro: {erro}</p>
            <a href="http://localhost:5173">Voltar ao sistema</a>
            </body></html>
        """, status_code=400)

    if not code:
        return HTMLResponse("<h2>Código de autorização não recebido</h2>", status_code=400)

    sucesso = olist.trocar_code_por_token(code)

    if sucesso:
        return HTMLResponse("""
            <html><body style="font-family:sans-serif;text-align:center;padding:50px">
            <h1 style="color:#2e7d32">✓ Olist conectado com sucesso!</h1>
            <p>A integração está ativa. Você já pode buscar produtos e atualizar estoque.</p>
            <a href="http://localhost:5173" style="display:inline-block;margin-top:20px;
               padding:12px 30px;background:#1976d2;color:white;text-decoration:none;
               border-radius:6px;font-weight:bold">Voltar ao Estoque Virtual</a>
            </body></html>
        """)
    else:
        return HTMLResponse("""
            <html><body style="font-family:sans-serif;text-align:center;padding:50px">
            <h2 style="color:#d32f2f">Falha ao obter token</h2>
            <p>Verifique se as credenciais e a URL de redirecionamento estão corretas.</p>
            <a href="http://localhost:5173">Voltar ao sistema</a>
            </body></html>
        """, status_code=500)


# ===== ENDPOINTS: GESTÃO DE FORNECEDORES =====

async def criar_fornecedor(request: Request):
    """Cria um novo fornecedor"""
    db = SessionLocal()
    try:
        data = await request.json()

        # Validações básicas
        nome = data.get("nome", "").strip()
        if not nome:
            return JSONResponse({"error": "Nome é obrigatório"}, status_code=400)

        # Verificar se já existe fornecedor com esse nome
        existente = db.query(Fornecedor).filter(Fornecedor.nome == nome).first()
        if existente:
            return JSONResponse({"error": f"Fornecedor '{nome}' já existe"}, status_code=400)

        fornecedor = Fornecedor(
            nome=nome,
            cnpj=data.get("cnpj", "").strip() or None,
            contato_whatsapp=data.get("contato_whatsapp", "").strip() or None,
            email=data.get("email", "").strip() or None,
            endereco=data.get("endereco", "").strip() or None,
            ativo=int(data.get("ativo", 1))
        )

        db.add(fornecedor)
        db.commit()

        return JSONResponse({
            "sucesso": True,
            "fornecedor": {
                "id": fornecedor.id,
                "nome": fornecedor.nome,
                "cnpj": fornecedor.cnpj,
                "contato_whatsapp": fornecedor.contato_whatsapp,
                "email": fornecedor.email,
                "endereco": fornecedor.endereco,
                "ativo": fornecedor.ativo,
                "criado_em": fornecedor.criado_em.isoformat()
            }
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


async def listar_fornecedores(request: Request):
    """Lista todos os fornecedores"""
    db = SessionLocal()
    try:
        skip = int(request.query_params.get("skip", 0))
        limit = int(request.query_params.get("limit", 100))
        ativo_only = request.query_params.get("ativo", "1") == "1"

        query = db.query(Fornecedor)
        if ativo_only:
            query = query.filter(Fornecedor.ativo == 1)

        fornecedores = query.order_by(Fornecedor.nome).offset(skip).limit(limit).all()
        total = db.query(Fornecedor).count()

        return JSONResponse({
            "total": total,
            "skip": skip,
            "limit": limit,
            "fornecedores": [{
                "id": f.id,
                "nome": f.nome,
                "cnpj": f.cnpj,
                "contato_whatsapp": f.contato_whatsapp,
                "email": f.email,
                "endereco": f.endereco,
                "ativo": f.ativo,
                "criado_em": f.criado_em.isoformat()
            } for f in fornecedores]
        })
    finally:
        db.close()


async def editar_fornecedor(request: Request):
    """Edita um fornecedor existente"""
    db = SessionLocal()
    try:
        fornecedor_id = int(request.path_params['id'])
        fornecedor = db.query(Fornecedor).filter(Fornecedor.id == fornecedor_id).first()

        if not fornecedor:
            return JSONResponse({"error": "Fornecedor não encontrado"}, status_code=404)

        data = await request.json()

        if "nome" in data:
            nome = data["nome"].strip()
            if nome and nome != fornecedor.nome:
                # Verificar se já existe outro com esse nome
                existente = db.query(Fornecedor).filter(
                    Fornecedor.nome == nome,
                    Fornecedor.id != fornecedor_id
                ).first()
                if existente:
                    return JSONResponse({"error": f"Fornecedor '{nome}' já existe"}, status_code=400)
            fornecedor.nome = nome

        if "cnpj" in data:
            fornecedor.cnpj = data["cnpj"].strip() or None
        if "contato_whatsapp" in data:
            fornecedor.contato_whatsapp = data["contato_whatsapp"].strip() or None
        if "email" in data:
            fornecedor.email = data["email"].strip() or None
        if "endereco" in data:
            fornecedor.endereco = data["endereco"].strip() or None
        if "ativo" in data:
            fornecedor.ativo = int(data["ativo"])

        db.commit()

        return JSONResponse({
            "sucesso": True,
            "fornecedor": {
                "id": fornecedor.id,
                "nome": fornecedor.nome,
                "cnpj": fornecedor.cnpj,
                "contato_whatsapp": fornecedor.contato_whatsapp,
                "email": fornecedor.email,
                "endereco": fornecedor.endereco,
                "ativo": fornecedor.ativo,
                "criado_em": fornecedor.criado_em.isoformat()
            }
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


async def deletar_fornecedor(request: Request):
    """Deleta um fornecedor"""
    db = SessionLocal()
    try:
        fornecedor_id = int(request.path_params['id'])
        fornecedor = db.query(Fornecedor).filter(Fornecedor.id == fornecedor_id).first()

        if not fornecedor:
            return JSONResponse({"error": "Fornecedor não encontrado"}, status_code=404)

        nome = fornecedor.nome
        db.delete(fornecedor)
        db.commit()

        return JSONResponse({
            "sucesso": True,
            "mensagem": f"Fornecedor '{nome}' deletado com sucesso"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


# ===== ENDPOINTS: CONFIGURAÇÃO DE ESTOQUE MÍNIMO =====

async def criar_estoque_minimo(request: Request):
    """Cria/atualiza configuração de estoque mínimo para um produto"""
    db = SessionLocal()
    try:
        data = await request.json()

        produto_codigo = data.get("produto_codigo", "").strip()
        if not produto_codigo:
            return JSONResponse({"error": "produto_codigo é obrigatório"}, status_code=400)

        estoque_minimo = float(data.get("estoque_minimo", 10))
        notificar = int(data.get("notificar_fornecedores", 1))

        config = db.query(ConfiguracaoEstoqueMinimo).filter(
            ConfiguracaoEstoqueMinimo.produto_codigo == produto_codigo
        ).first()

        if config:
            config.estoque_minimo = estoque_minimo
            config.notificar_fornecedores = notificar
            config.atualizado_em = datetime.utcnow()
        else:
            config = ConfiguracaoEstoqueMinimo(
                produto_codigo=produto_codigo,
                estoque_minimo=estoque_minimo,
                notificar_fornecedores=notificar
            )
            db.add(config)

        db.commit()

        return JSONResponse({
            "sucesso": True,
            "config": {
                "id": config.id,
                "produto_codigo": config.produto_codigo,
                "estoque_minimo": config.estoque_minimo,
                "notificar_fornecedores": config.notificar_fornecedores,
                "atualizado_em": config.atualizado_em.isoformat()
            }
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


async def listar_estoque_minimo(request: Request):
    """Lista configurações de estoque mínimo"""
    db = SessionLocal()
    try:
        skip = int(request.query_params.get("skip", 0))
        limit = int(request.query_params.get("limit", 100))

        configs = db.query(ConfiguracaoEstoqueMinimo).order_by(
            ConfiguracaoEstoqueMinimo.produto_codigo
        ).offset(skip).limit(limit).all()

        total = db.query(ConfiguracaoEstoqueMinimo).count()

        return JSONResponse({
            "total": total,
            "skip": skip,
            "limit": limit,
            "configuracoes": [{
                "id": c.id,
                "produto_codigo": c.produto_codigo,
                "estoque_minimo": c.estoque_minimo,
                "notificar_fornecedores": c.notificar_fornecedores,
                "criado_em": c.criado_em.isoformat(),
                "atualizado_em": c.atualizado_em.isoformat()
            } for c in configs]
        })
    finally:
        db.close()


async def editar_estoque_minimo(request: Request):
    """Edita configuração de estoque mínimo"""
    db = SessionLocal()
    try:
        produto_codigo = request.path_params['produto_codigo']

        config = db.query(ConfiguracaoEstoqueMinimo).filter(
            ConfiguracaoEstoqueMinimo.produto_codigo == produto_codigo
        ).first()

        if not config:
            return JSONResponse({"error": "Configuração não encontrada"}, status_code=404)

        data = await request.json()

        if "estoque_minimo" in data:
            config.estoque_minimo = float(data["estoque_minimo"])
        if "notificar_fornecedores" in data:
            config.notificar_fornecedores = int(data["notificar_fornecedores"])

        config.atualizado_em = datetime.utcnow()
        db.commit()

        return JSONResponse({
            "sucesso": True,
            "config": {
                "id": config.id,
                "produto_codigo": config.produto_codigo,
                "estoque_minimo": config.estoque_minimo,
                "notificar_fornecedores": config.notificar_fornecedores,
                "atualizado_em": config.atualizado_em.isoformat()
            }
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


# ===== ENDPOINTS: HISTÓRICO E NOTIFICAÇÕES =====

async def historico_compras_produto(request: Request):
    """Retorna lista de fornecedores que já forneceram um produto"""
    db = SessionLocal()
    try:
        produto_codigo = request.path_params['produto_codigo']

        historico = db.query(HistoricoCompra).filter(
            HistoricoCompra.produto_codigo == produto_codigo
        ).order_by(HistoricoCompra.data_compra.desc()).all()

        # Agrupar por fornecedor
        fornecedores = {}
        for h in historico:
            if h.fornecedor_id not in fornecedores:
                fornecedor = db.query(Fornecedor).filter(Fornecedor.id == h.fornecedor_id).first()
                if fornecedor:
                    fornecedores[h.fornecedor_id] = {
                        "id": fornecedor.id,
                        "nome": fornecedor.nome,
                        "contato_whatsapp": fornecedor.contato_whatsapp,
                        "email": fornecedor.email,
                        "compras": []
                    }

            if h.fornecedor_id in fornecedores:
                fornecedores[h.fornecedor_id]["compras"].append({
                    "quantidade": h.quantidade,
                    "data_compra": h.data_compra.isoformat(),
                    "nf_numero": h.nf_numero
                })

        return JSONResponse({
            "produto_codigo": produto_codigo,
            "total_fornecedores": len(fornecedores),
            "fornecedores": list(fornecedores.values())
        })
    finally:
        db.close()


async def notificar_fornecedores(request: Request):
    """
    Notifica fornecedores de produtos com estoque baixo via WhatsApp.
    Pode ser acionado manualmente ou pela rotina diária.
    """
    db = SessionLocal()
    try:
        # Encontrar todos os produtos com estoque abaixo do mínimo
        produtos_baixos = []

        configs = db.query(ConfiguracaoEstoqueMinimo).filter(
            ConfiguracaoEstoqueMinimo.notificar_fornecedores == 1
        ).all()

        for config in configs:
            # Somar todas as quantidades confirmadas deste produto
            total_estoque = db.query(ItemEstoque).filter(
                ItemEstoque.codigo_produto == config.produto_codigo,
                ItemEstoque.status == StatusEstoque.CONFIRMADO
            ).all()

            quantidade_total = sum(item.quantidade_confirmada or 0 for item in total_estoque)

            if quantidade_total <= config.estoque_minimo:
                produtos_baixos.append({
                    "produto_codigo": config.produto_codigo,
                    "estoque_minimo": config.estoque_minimo,
                    "quantidade_atual": quantidade_total,
                    "itens": total_estoque
                })

        if not produtos_baixos:
            return JSONResponse({
                "sucesso": True,
                "notificacoes_enviadas": 0,
                "mensagem": "Nenhum produto com estoque baixo"
            })

        notificacoes_enviadas = []

        # Para cada produto com estoque baixo, notificar os fornecedores
        for produto in produtos_baixos:
            codigo = produto["produto_codigo"]

            # Obter descrição do produto
            item = produto["itens"][0] if produto["itens"] else None
            descricao = item.descricao if item else codigo

            # Buscar fornecedores que já forneceram este produto
            historico = db.query(HistoricoCompra).filter(
                HistoricoCompra.produto_codigo == codigo
            ).distinct(HistoricoCompra.fornecedor_id).all()

            fornecedor_ids = [h.fornecedor_id for h in historico]

            if not fornecedor_ids:
                continue

            fornecedores = db.query(Fornecedor).filter(
                Fornecedor.id.in_(fornecedor_ids),
                Fornecedor.ativo == 1,
                Fornecedor.contato_whatsapp != None
            ).all()

            for fornecedor in fornecedores:
                # Verificar se já foi notificado hoje
                hoje = datetime.utcnow().date()
                ja_notificado = db.query(NotificacaoFornecedor).filter(
                    NotificacaoFornecedor.fornecedor_id == fornecedor.id,
                    NotificacaoFornecedor.produto_codigo == codigo,
                    NotificacaoFornecedor.status == "enviado"
                ).first()

                # Se já foi notificado hoje, pula
                if ja_notificado and ja_notificado.enviado_em.date() == hoje:
                    continue

                # Construir mensagem
                mensagem = f"""📦 ALERTA DE ESTOQUE BAIXO - Estoque Virtual

Produto: {descricao}
Código: {codigo}
Estoque Atual: {produto['quantidade_atual']} un
Estoque Mínimo: {produto['estoque_minimo']} un

Você já forneceu este produto anteriormente.
Favor entrar em contato para recompra.

Obrigado!"""

                # Gerar WhatsApp link
                telefone = fornecedor.contato_whatsapp
                mensagem_encoded = urllib.parse.quote(mensagem)
                whatsapp_link = f"https://wa.me/{telefone}?text={mensagem_encoded}"

                # Registrar notificação no banco
                notif = NotificacaoFornecedor(
                    fornecedor_id=fornecedor.id,
                    produto_codigo=codigo,
                    produto_descricao=descricao,
                    quantidade_atual=produto['quantidade_atual'],
                    estoque_minimo=produto['estoque_minimo'],
                    mensagem=mensagem,
                    telefone_usado=telefone,
                    status="enviado"
                )

                db.add(notif)
                notificacoes_enviadas.append({
                    "fornecedor_id": fornecedor.id,
                    "fornecedor_nome": fornecedor.nome,
                    "produto_codigo": codigo,
                    "telefone": telefone,
                    "whatsapp_link": whatsapp_link
                })

        db.commit()

        return JSONResponse({
            "sucesso": True,
            "notificacoes_enviadas": len(notificacoes_enviadas),
            "notificacoes": notificacoes_enviadas
        })

    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


async def historico_notificacoes(request: Request):
    """Lista histórico de notificações enviadas"""
    db = SessionLocal()
    try:
        skip = int(request.query_params.get("skip", 0))
        limit = int(request.query_params.get("limit", 100))

        notificacoes = db.query(NotificacaoFornecedor).order_by(
            NotificacaoFornecedor.enviado_em.desc()
        ).offset(skip).limit(limit).all()

        total = db.query(NotificacaoFornecedor).count()

        return JSONResponse({
            "total": total,
            "skip": skip,
            "limit": limit,
            "notificacoes": [{
                "id": n.id,
                "fornecedor_id": n.fornecedor_id,
                "fornecedor_nome": n.fornecedor.nome if n.fornecedor else "Desconhecido",
                "produto_codigo": n.produto_codigo,
                "produto_descricao": n.produto_descricao,
                "quantidade_atual": n.quantidade_atual,
                "estoque_minimo": n.estoque_minimo,
                "telefone_usado": n.telefone_usado,
                "enviado_em": n.enviado_em.isoformat(),
                "status": n.status,
                "erro_mensagem": n.erro_mensagem
            } for n in notificacoes]
        })
    finally:
        db.close()


routes = [
    Route("/", root, methods=["GET"]),
    Route("/api/upload-nfe", upload_nfe, methods=["POST"]),
    Route("/api/notas-fiscais", get_nfs, methods=["GET"]),
    Route("/api/notas-fiscais/{nf_id}", get_nf, methods=["GET"]),
    Route("/api/notas-fiscais/{nf_id}/baixar", baixar_nota_fiscal, methods=["GET"]),
    Route("/api/notas-fiscais/{nf_id}/pdf", gerar_pdf_nota_fiscal, methods=["GET"]),
    Route("/api/notas-fiscais/deletar", excluir_nota_fiscal, methods=["POST"]),
    Route("/api/notas-fiscais/deletar-multiplas", excluir_multiplas_notas, methods=["POST"]),
    Route("/api/estoque-virtual", get_estoque_virtual, methods=["GET"]),
    Route("/api/confirmar-estoque", confirmar_estoque, methods=["POST"]),
    Route("/api/registrar-divergencia", registrar_divergencia, methods=["POST"]),
    Route("/api/historico-confirmacao/{item_id}", get_historico_confirmacao, methods=["GET"]),
    Route("/api/notas-fiscais/{nf_id}/tem-divergencias", nf_tem_divergencias, methods=["GET"]),
    Route("/api/divergencias", listar_divergencias, methods=["GET"]),
    Route("/api/produtos-manuais", adicionar_produto_manual, methods=["POST"]),
    Route("/api/resolver-divergencia", resolver_divergencia, methods=["POST"]),
    Route("/api/deletar-divergencia", deletar_divergencia, methods=["POST"]),
    # Integração Olist (OAuth2)
    Route("/api/olist/conectar", olist_conectar, methods=["GET"]),
    Route("/api/olist/callback", olist_callback, methods=["GET"]),
    Route("/api/olist/status", olist_status, methods=["GET"]),
    Route("/api/olist/produtos", buscar_produtos_olist, methods=["GET"]),
    Route("/api/olist/produtos-todos", listar_produtos_olist, methods=["GET"]),
    Route("/api/olist/vincular-produto", vincular_produto_olist, methods=["POST"]),
    Route("/api/olist/aceitar-sugestao", aceitar_sugestao_vinculo, methods=["POST"]),
    Route("/api/olist/atualizar-estoque", atualizar_estoque_olist, methods=["POST"]),
    # Memória de vínculos (de-para fornecedor -> Olist)
    Route("/api/olist/sugestao-vinculo", olist_sugestao_vinculo, methods=["GET"]),
    Route("/api/olist/vinculos", olist_listar_vinculos, methods=["GET"]),
    Route("/api/olist/vinculos/deletar", olist_deletar_vinculo, methods=["POST"]),
    # Gestão de Fornecedores
    Route("/api/fornecedores", criar_fornecedor, methods=["POST"]),
    Route("/api/fornecedores", listar_fornecedores, methods=["GET"]),
    Route("/api/fornecedores/{id}", editar_fornecedor, methods=["PUT"]),
    Route("/api/fornecedores/{id}", deletar_fornecedor, methods=["DELETE"]),
    # Configuração de Estoque Mínimo
    Route("/api/estoque-minimo", criar_estoque_minimo, methods=["POST"]),
    Route("/api/estoque-minimo", listar_estoque_minimo, methods=["GET"]),
    Route("/api/estoque-minimo/{produto_codigo}", editar_estoque_minimo, methods=["PUT"]),
    # Histórico e Notificações
    Route("/api/historico-compras/{produto_codigo}", historico_compras_produto, methods=["GET"]),
    Route("/api/notificar-fornecedores", notificar_fornecedores, methods=["POST"]),
    Route("/api/historico-notificacoes", historico_notificacoes, methods=["GET"]),
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

# Iniciar scheduler de jobs (notificação diária de fornecedores)
iniciar_scheduler()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
