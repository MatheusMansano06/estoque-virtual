from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse, FileResponse, RedirectResponse, HTMLResponse, Response
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from sqlalchemy.orm import Session
from database import engine, Base, SessionLocal
import os
import json
from datetime import datetime, timedelta
import uuid
import urllib.request
import urllib.parse
from dotenv import load_dotenv
from difflib import SequenceMatcher
import io

from app.models import (
    NotaFiscal, ItemEstoque, ConfirmacaoEstoque, StatusEstoque, VinculoOlist,
    Fornecedor, HistoricoCompra, ConfiguracaoEstoqueMinimo, NotificacaoFornecedor,
    EmbaleFU, ItemEmbaleFU
)
from app.utils.nfe_parser import NFeParsing
from app.utils.nfe_pdf_generator import NFePDFGenerator
from app.utils.fornecedores import garantir_fornecedor, linkar_fornecedor_nf
from app.utils.embale_parser import extrair_items_embale_pdf
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

# 📋 Constantes de configuração
MIN_AUTO_CONFIDENCE = 0.95  # Vincular automaticamente apenas com 95%+ de confiança
MIN_FUZZY_CONFIDENCE = 0.80  # Sugerir vinculação com 80%+ de confiança
MAX_PAGINATION_LIMIT = 1000  # Limite máximo de itens por página

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

    # 3) Tenta fuzzy match por descrição (acima de MIN_FUZZY_CONFIDENCE)
    if item.descricao:
        # ⚡ PERFORMANCE: Usar SQL LIKE para pré-filtrar antes do loop
        termo = item.descricao[:30]  # Primeiros 30 caracteres
        vinculos_candidatos = db.query(VinculoOlist).filter(
            VinculoOlist.nf_descricao.like(f"%{termo}%")
        ).all()

        best_match = None
        best_score = 0
        for v in vinculos_candidatos:
            # 🔒 SEGURANÇA: Verificar se nf_descricao não é None
            if v.nf_descricao is None:
                continue
            score = similaridade(item.descricao, v.nf_descricao)
            if score > best_score:
                best_score = score
                best_match = v
        if best_match and best_score >= MIN_FUZZY_CONFIDENCE:
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
        # 🔒 SEGURANÇA: Sanitizar nome do arquivo para evitar path traversal
        safe_filename = uuid.uuid4().hex + os.path.splitext(file.filename)[1]

        if file_ext == "xml":
            result = NFeParsing.parse_xml(content)
        else:
            # Save temp file for OCR processing
            temp_path = os.path.join(UPLOAD_DIR, safe_filename)
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
                arquivo_original=safe_filename,
                tipo_documento="nfe" if file_ext == "xml" else "pdf",
                status="processado",
                xml_processado=content.decode('utf-8', errors='ignore') if file_ext == "xml" else None
            )

            db.add(nf)
            db.flush()

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
                    # Auto-vincular se confiança >= MIN_AUTO_CONFIDENCE (match exato)
                    if confianca >= MIN_AUTO_CONFIDENCE:
                        estoque_item.olist_produto_id = vinculo.olist_produto_id
                        estoque_item.olist_sku = vinculo.olist_sku
                        estoque_item.olist_nome = vinculo.olist_nome
                        estoque_item.vinculado_em = datetime.utcnow()
                        db.commit()
                    else:
                        # Sugerir se confiança entre MIN_FUZZY_CONFIDENCE e MIN_AUTO_CONFIDENCE (fuzzy match)
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
    try:
        skip = int(request.query_params.get("skip", 0))
        # 🔒 SEGURANÇA: Limitar paginação para evitar DoS
        limit = min(int(request.query_params.get("limit", 100)), MAX_PAGINATION_LIMIT)
    except ValueError:
        return JSONResponse({"error": "Parâmetros skip/limit devem ser números inteiros"}, status_code=400)

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
    except Exception as e:
        print(f"[ERROR get_nfs] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({"erro": str(e)}, status_code=500)
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
    from sqlalchemy.orm import joinedload
    db = SessionLocal()
    try:
        # ⚡ PERFORMANCE: Usar joinedload para evitar N+1 queries
        # Get all items grouped by product description
        items = db.query(ItemEstoque).options(
            joinedload(ItemEstoque.nota_fiscal)
        ).all()

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
        db.commit()

        return JSONResponse({
            "success": True,
            "id": confirmacao.id,
            "quantidade_confirmada": quantidade_confirmada,
            "divergencia": divergencia
        })
    except Exception as e:
        # 🔒 ROLLBACK: Desfazer alterações em caso de erro
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
    """Busca produtos na Olist via API v3 (OAuth2) ou token simples (fallback)"""
    try:
        query = request.query_params.get("q", "")

        if not query or len(query) < 1:
            return JSONResponse({
                "produtos": [],
                "total": 0,
                "mensagem": "Digite ao menos 1 caractere para buscar"
            })

        # Buscar via API (com fallback automático para token simples)
        print(f"[BUSCA] Buscando na Olist: {query}")
        produtos = olist.buscar_produtos(query)

        # Se não encontrou produtos e não tem nenhum token configurado
        if not produtos and not olist.get_access_token() and not olist.token_v2:
            print("[BUSCA] Nenhum token Olist configurado")
            return JSONResponse({
                "produtos": [],
                "total": 0,
                "termo_busca": query,
                "nao_autorizado": True,
                "url_autorizacao": "http://localhost:8000/api/olist/conectar",
                "mensagem": "Configure a chave OLIST_API_TOKEN_SIMPLE no .env ou conecte-se via OAuth2"
            })

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
    """Lista todos os produtos na Olist (usa cache)"""
    try:
        print("[LISTA] Listando todos os produtos da Olist")
        produtos = olist.listar_todos_produtos(limite=2000)

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


async def obter_estoque_produto_olist(request: Request):
    """Busca o estoque de UM produto sob demanda (rapido - 1 requisicao)"""
    try:
        produto_id = request.query_params.get("id", "").strip()
        if not produto_id:
            return JSONResponse({"error": "id obrigatorio"}, status_code=400)

        estoque = olist.obter_estoque(produto_id)
        if estoque:
            return JSONResponse({
                "estoque_atual": estoque.get("disponivel", 0),
                "estoque_saldo": estoque.get("saldo", 0),
                "estoque_reservado": estoque.get("reservado", 0),
            })
        return JSONResponse({
            "estoque_atual": 0,
            "estoque_saldo": 0,
            "estoque_reservado": 0,
        })
    except Exception as e:
        print(f"[ERRO] Estoque produto: {str(e)}")
        return JSONResponse({"estoque_atual": 0, "estoque_saldo": 0, "estoque_reservado": 0})


async def refresh_cache_produtos_olist(request: Request):
    """Forca recarregar o cache de produtos da Olist (atualizar lista)"""
    try:
        print("[CACHE] Refresh forcado do cache de produtos")
        produtos = olist.listar_todos_produtos(limite=2000, forcar_refresh=True)
        return JSONResponse({
            "status": "sucesso",
            "total": len(produtos),
            "mensagem": f"Cache atualizado: {len(produtos)} produtos"
        })
    except Exception as e:
        print(f"[ERRO] Refresh cache: {str(e)}")
        return JSONResponse({"status": "erro", "mensagem": str(e)}, status_code=500)


async def detectar_kit_automatico(request: Request):
    """
    Detecta automaticamente se um SKU é um KIT na Olist
    e retorna os componentes unitários para atualizar estoque
    GET /api/olist/detectar-kit?sku=V+RL3
    """
    try:
        sku = request.query_params.get("sku", "").strip()

        if not sku:
            return JSONResponse({
                "eh_kit": False,
                "erro": "SKU não informado"
            }, status_code=400)

        print(f"[KIT-AUTO] Detectando kit para SKU: {sku}")

        # Tenta detectar kit
        resultado = olist.detectar_e_buscar_kit(sku)

        if resultado.get("eh_kit"):
            # É um kit!
            componentes = resultado.get("componentes", [])
            print(f"[KIT-AUTO] KIT DETECTADO: {sku} com {len(componentes)} componente(s)")

            return JSONResponse({
                "eh_kit": True,
                "sku_principal": resultado.get("sku_principal"),
                "nome_kit": resultado.get("nome_kit"),
                "preco_kit": resultado.get("preco_kit"),
                "componentes": componentes,
                "mensagem": f"✅ KIT detectado! {len(componentes)} componentes encontrados"
            })
        else:
            # Não é kit, retorna o produto normal
            produto = resultado.get("produto")
            print(f"[KIT-AUTO] Não é kit. Tipo: {resultado.get('tipo')}")

            return JSONResponse({
                "eh_kit": False,
                "tipo": resultado.get("tipo"),
                "produto": produto,
                "mensagem": "Este SKU não é um kit, use a busca normal"
            })

    except Exception as e:
        print(f"[ERRO KIT-AUTO] {str(e)}")
        return JSONResponse({
            "eh_kit": False,
            "erro": str(e)
        }, status_code=500)


# ===== NOVOS ENDPOINTS - INTEGRAÇÃO OLIST =====

async def olist_status(request: Request):
    """Retorna status da integração Olist"""
    status = olist.status()
    return JSONResponse(status)


async def olist_diagnostico(request: Request):
    """Diagnóstico da integração Olist - para debug"""
    try:
        diagnostico = {
            "oauth2_configurado": bool(olist.client_id and olist.client_secret),
            "token_simples_configurado": bool(olist.token_v2),
            "token_oauth2_valido": bool(olist.get_access_token()),
            "tentar_lista_produtos": False,
            "erro": None
        }

        # Tentar listar alguns produtos com mais detalhes
        print("[DIAG] Testando conexão com Olist...")
        token = olist.get_access_token() or olist.token_v2

        if token:
            try:
                url = "https://api.tiny.com.br/public-api/v3/produtos?limit=1"
                headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=5) as response:
                    resposta = json.loads(response.read().decode("utf-8"))
                    diagnostico["conexao_ok"] = True
                    diagnostico["resposta_tipo"] = type(resposta).__name__
                    diagnostico["primeiro_campo"] = list(resposta.keys())[0] if isinstance(resposta, dict) else "lista"
            except urllib.error.HTTPError as e:
                diagnostico["conexao_ok"] = False
                diagnostico["erro"] = f"HTTP {e.code}: {e.read().decode('utf-8')[:100]}"
            except Exception as e:
                diagnostico["conexao_ok"] = False
                diagnostico["erro"] = str(e)
        else:
            diagnostico["erro"] = "Nenhum token disponível"

        return JSONResponse(diagnostico)
    except Exception as e:
        return JSONResponse({"erro": str(e)}, status_code=500)


async def vincular_produto_olist(request: Request):
    """Vincula um produto da NF com um anúncio da Olist"""
    db = SessionLocal()
    try:
        data = await request.json()
        item_id = data.get("item_id")
        olist_produto_id = data.get("olist_produto_id")
        olist_sku = data.get("olist_sku", "")
        olist_nome = data.get("olist_nome", "")

        # 🔒 VALIDAÇÃO: Verificar se campos obrigatórios estão presentes
        if not item_id or not olist_produto_id:
            return JSONResponse({"error": "item_id e olist_produto_id são obrigatórios"}, status_code=400)

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
        item_ids = data.get("item_ids")  # lista opcional: subida EM MASSA de varios registros
        quantidade = data.get("quantidade", 0)  # quantidade a ADICIONAR (entrada)
        tipo = data.get("tipo", "E")  # E=Entrada (padrao), B=Balanco, S=Saida

        item = db.query(ItemEstoque).filter(ItemEstoque.id == item_id).first()
        if not item:
            return JSONResponse({"error": "Item não encontrado"}, status_code=404)

        if not item.olist_produto_id:
            return JSONResponse({
                "error": "Produto não está vinculado à Olist"
            }, status_code=400)

        # Chamar API para atualizar estoque (entrada da NF) - UMA unica vez com a qtd total
        sucesso = olist.atualizar_estoque(
            item.olist_produto_id,
            quantidade=float(quantidade),
            tipo=tipo,
            preco_unitario=float(item.preco_unitario or 0)
        )

        if sucesso:
            agora = datetime.utcnow()

            # Determina TODOS os itens que participaram desta entrada.
            # Em massa, o frontend manda item_ids (todos os registros do grupo).
            if isinstance(item_ids, list) and item_ids:
                ids_marcar = item_ids
            else:
                ids_marcar = [item_id]

            # Vincula todos ao mesmo anuncio Olist e marca todos como subidos.
            # (sem isso, so o 1o registro ficava "Subido na Olist" numa subida em massa)
            itens_grupo = db.query(ItemEstoque).filter(ItemEstoque.id.in_(ids_marcar)).all()
            for it in itens_grupo:
                it.olist_produto_id = item.olist_produto_id
                it.olist_sku = item.olist_sku
                it.olist_nome = item.olist_nome
                it.estoque_olist_atualizado_em = agora

            db.commit()

            return JSONResponse({
                "sucesso": True,
                "mensagem": f"Entrada de {quantidade} unidades registrada na Olist",
                "olist_produto_id": item.olist_produto_id,
                "itens_marcados": len(itens_grupo)
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


async def adicionar_produto_olist_manual(request: Request):
    """Adiciona um produto Olist manualmente para opções de vinculação"""
    db = SessionLocal()
    try:
        data = await request.json()
        sku = data.get("sku", "").strip()
        nome = data.get("nome", "").strip()
        preco = float(data.get("preco", 0) or 0)
        estoque = int(data.get("estoque", 0) or 0)

        if not sku or not nome:
            return JSONResponse(
                {"error": "SKU e Nome são obrigatórios"},
                status_code=400
            )

        # Criar como sugestão retornável
        resultado = {
            "id": f"manual_{sku}",
            "sku": sku,
            "nome": nome,
            "preco": preco,
            "estoque_atual": estoque,
            "estoque_saldo": estoque,
            "estoque_reservado": 0,
            "fonte": "manual"
        }

        return JSONResponse(resultado)

    except Exception as e:
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

        # 🔒 VALIDAÇÃO: Verificar se é uma lista
        if not isinstance(nf_ids, list):
            return JSONResponse({"error": "nf_ids deve ser uma lista"}, status_code=400)

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

        # 🔒 SEGURANÇA: Validar que o arquivo está dentro de UPLOAD_DIR
        arquivo_path = os.path.join(UPLOAD_DIR, nf.arquivo_original)
        real_path = os.path.realpath(arquivo_path)
        upload_dir_real = os.path.realpath(UPLOAD_DIR)

        if not real_path.startswith(upload_dir_real):
            return JSONResponse({"error": "Acesso negado"}, status_code=403)

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


# ==================== ENDPOINTS INBOUND / LISTA DE SEPARAÇÃO ====================

async def upload_embale(request: Request):
    """
    POST /api/embaldes/upload
    Faz upload de um PDF de Inbound do Mercado Livre (lista de separação).
    Extrai os items (SKU, código ML, título, unidades) e vincula
    automaticamente com anúncios Olist via SKU.
    """
    db = SessionLocal()
    try:
        # Receber arquivo
        form = await request.form()
        arquivo = form.get("arquivo")
        nome_embale = form.get("nome_embale") or "Inbound sem nome"

        if not arquivo:
            return JSONResponse({"erro": "Arquivo não fornecido"}, status_code=400)

        # Validar tipo de arquivo
        if not arquivo.filename.lower().endswith('.pdf'):
            return JSONResponse({"erro": "Apenas arquivos PDF são aceitos"}, status_code=400)

        # Salvar arquivo com UUID
        arquivo_uuid = f"{uuid.uuid4()}_{arquivo.filename}"
        caminho_arquivo = os.path.join(UPLOAD_DIR, arquivo_uuid)

        conteudo = await arquivo.read()
        with open(caminho_arquivo, 'wb') as f:
            f.write(conteudo)

        # Extrair items do PDF ANTES de criar o registro
        resultado = extrair_items_embale_pdf(caminho_arquivo)

        if isinstance(resultado, dict) and resultado.get("erro"):
            return JSONResponse(
                {"erro": resultado.get("mensagem", "Erro ao processar PDF")},
                status_code=400
            )

        items_extraidos = resultado.get("items", [])
        numero_inbound = resultado.get("numero_inbound")
        total_unidades = resultado.get("total_unidades", 0)

        # Criar inbound no BD
        embale = EmbaleFU(
            nome_embalde=nome_embale,
            numero_inbound=numero_inbound,
            total_unidades=total_unidades,
            arquivo_original=arquivo.filename,
            arquivo_uuid=arquivo_uuid
        )
        db.add(embale)
        db.commit()
        db.refresh(embale)

        # Processar cada item
        items_processados = 0
        items_validados = 0
        items_com_erro = []

        for item_data in items_extraidos:
            sku = (item_data.get("sku") or "").strip()
            codigo_ml = (item_data.get("codigo_ml") or "").strip()
            titulo = (item_data.get("titulo_anuncio") or "").strip()
            qtd = item_data.get("quantidade_separada", 0)

            item_embale = ItemEmbaleFU(
                embalde_id=embale.id,
                titulo_anuncio=titulo,
                quantidade_separada=qtd,
                sku_inbound=sku or None,
                codigo_ml=codigo_ml or None,
                validado=0
            )

            # 1) Match primário por SKU (exato, case-insensitive)
            vinculo = None
            if sku:
                vinculo = db.query(VinculoOlist).filter(
                    VinculoOlist.olist_sku.ilike(sku)
                ).first()

            # 2) Fallback: match por título do anúncio
            if not vinculo and titulo:
                vinculo = db.query(VinculoOlist).filter(
                    VinculoOlist.olist_nome.ilike(f"%{titulo}%")
                ).first()

            if vinculo:
                item_embale.olist_produto_id = vinculo.olist_produto_id
                item_embale.olist_sku = vinculo.olist_sku
                item_embale.olist_nome = vinculo.olist_nome
                item_embale.validado = 1
                item_embale.validacao_mensagem = f"Vinculado via SKU {vinculo.olist_sku}"
                item_embale.data_validacao = datetime.utcnow()
                items_validados += 1
            else:
                item_embale.validado = 0
                item_embale.validacao_mensagem = (
                    f"SKU '{sku}' não encontrado nos vínculos Olist" if sku
                    else "Item sem SKU identificável"
                )
                items_com_erro.append({"sku": sku, "titulo": titulo})

            db.add(item_embale)
            items_processados += 1

        db.commit()

        return JSONResponse({
            "id": embale.id,
            "nome_embale": embale.nome_embalde,
            "numero_inbound": numero_inbound,
            "total_unidades": total_unidades,
            "status": "processado",
            "itens_processados": items_processados,
            "itens_validados": items_validados,
            "itens_com_erro": len(items_com_erro),
            "erros": items_com_erro if items_com_erro else None,
            "mensagem": f"Inbound {numero_inbound or ''} processado: {items_validados}/{items_processados} items vinculados"
        })

    except Exception as e:
        db.rollback()
        return JSONResponse({"erro": str(e)}, status_code=500)
    finally:
        db.close()


async def listar_embaldes(request: Request):
    """
    GET /api/embaldes
    Lista todos os embaldes/listas de separação
    """
    try:
        db = SessionLocal()

        skip = int(request.query_params.get("skip", 0))
        limit = min(int(request.query_params.get("limit", 10)), MAX_PAGINATION_LIMIT)
        status = request.query_params.get("status", None)

        query = db.query(EmbaleFU)

        if status:
            query = query.filter(EmbaleFU.status == status)

        total = query.count()
        embaldes = query.offset(skip).limit(limit).all()

        return JSONResponse({
            "total": total,
            "skip": skip,
            "limit": limit,
            "items": [
                {
                    "id": e.id,
                    "nome_embalde": e.nome_embalde,
                    "numero_inbound": e.numero_inbound,
                    "total_unidades": e.total_unidades,
                    "arquivo_original": e.arquivo_original,
                    "data_upload": e.data_upload.isoformat(),
                    "status": e.status,
                    "qtd_items": len(e.itens),
                    "qtd_validados": sum(1 for i in e.itens if i.validado == 1)
                }
                for e in embaldes
            ]
        })

    except Exception as e:
        return JSONResponse({"erro": str(e)}, status_code=500)
    finally:
        db.close()


async def obter_embale(request: Request):
    """
    GET /api/embaldes/{id}
    Obtém detalhes de um embale específico
    """
    try:
        db = SessionLocal()
        embale_id = int(request.path_params.get("embale_id"))

        embale = db.query(EmbaleFU).filter(EmbaleFU.id == embale_id).first()

        if not embale:
            return JSONResponse({"erro": "Embale não encontrado"}, status_code=404)

        return JSONResponse({
            "id": embale.id,
            "nome_embalde": embale.nome_embalde,
            "numero_inbound": embale.numero_inbound,
            "total_unidades": embale.total_unidades,
            "arquivo_original": embale.arquivo_original,
            "data_upload": embale.data_upload.isoformat(),
            "status": embale.status,
            "itens": [
                {
                    "id": i.id,
                    "titulo_anuncio": i.titulo_anuncio,
                    "quantidade_separada": i.quantidade_separada,
                    "sku_inbound": i.sku_inbound,
                    "codigo_ml": i.codigo_ml,
                    "olist_produto_id": i.olist_produto_id,
                    "olist_sku": i.olist_sku,
                    "olist_nome": i.olist_nome,
                    "validado": i.validado,
                    "validacao_mensagem": i.validacao_mensagem
                }
                for i in embale.itens
            ]
        })

    except Exception as e:
        return JSONResponse({"erro": str(e)}, status_code=500)
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
    Route("/api/olist/diagnostico", olist_diagnostico, methods=["GET"]),
    Route("/api/olist/produtos", buscar_produtos_olist, methods=["GET"]),
    Route("/api/olist/detectar-kit", detectar_kit_automatico, methods=["GET"]),
    Route("/api/olist/produtos-todos", listar_produtos_olist, methods=["GET"]),
    Route("/api/olist/estoque-produto", obter_estoque_produto_olist, methods=["GET"]),
    Route("/api/olist/refresh-cache", refresh_cache_produtos_olist, methods=["POST"]),
    Route("/api/olist/vincular-produto", vincular_produto_olist, methods=["POST"]),
    Route("/api/olist/aceitar-sugestao", aceitar_sugestao_vinculo, methods=["POST"]),
    Route("/api/olist/atualizar-estoque", atualizar_estoque_olist, methods=["POST"]),
    Route("/api/olist/adicionar-manual", adicionar_produto_olist_manual, methods=["POST"]),
    # Memória de vínculos (de-para fornecedor -> Olist)
    Route("/api/olist/sugestao-vinculo", olist_sugestao_vinculo, methods=["GET"]),
    Route("/api/olist/vinculos", olist_listar_vinculos, methods=["GET"]),
    Route("/api/olist/vinculos/deletar", olist_deletar_vinculo, methods=["POST"]),
    # Embaldes / Lista de Separação para FU
    Route("/api/embaldes/upload", upload_embale, methods=["POST"]),
    Route("/api/embaldes", listar_embaldes, methods=["GET"]),
    Route("/api/embaldes/{embale_id}", obter_embale, methods=["GET"]),
]

app = Starlette(routes=routes)

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://localhost:5177",
        "http://localhost:5178",
        "http://localhost:5179",
        "http://localhost:5180",
        "http://localhost:5181",
        "http://localhost:5182",
        "http://localhost:5183",
        "http://localhost:5184",
        "http://localhost:5185",
        "http://localhost:5186",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
