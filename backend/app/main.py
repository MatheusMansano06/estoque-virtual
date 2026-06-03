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
    KitOlist, HistoricoVendas, FornecedorConfiguracao,
    HistoricoPrecos, Recomendacao
)
from app.utils.nfe_parser import NFeParsing
from app.utils.nfe_pdf_generator import NFePDFGenerator
from app.integracoes_olist import olist

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
        db.commit()

        return JSONResponse({
            "success": True,
            "id": confirmacao.id,
            "quantidade_confirmada": quantidade_confirmada,
            "divergencia": divergencia
        })
    except Exception as e:
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


# ===== ENDPOINTS DE KITS =====

async def verificar_kit(request: Request):
    """Verifica se um SKU é um kit e retorna seus componentes"""
    db = SessionLocal()
    try:
        sku = request.query_params.get("sku", "").strip().upper()
        if not sku:
            return JSONResponse({"erro": "SKU não informado"}, status_code=400)

        kit = db.query(KitOlist).filter(
            KitOlist.sku_kit == sku,
            KitOlist.ativo == 1
        ).first()

        if not kit:
            return JSONResponse({
                "eh_kit": False,
                "sku": sku
            })

        # Parsear os SKUs dos componentes
        skus_componentes = [s.strip() for s in kit.skus_componentes.split("|")]

        return JSONResponse({
            "eh_kit": True,
            "sku_kit": kit.sku_kit,
            "nome_kit": kit.nome_kit,
            "skus_componentes": skus_componentes,
            "quantidade_componentes": kit.quantidade_componentes,
            "id_kit": kit.id
        })
    finally:
        db.close()


async def listar_kits(request: Request):
    """Lista todos os kits cadastrados"""
    db = SessionLocal()
    try:
        kits = db.query(KitOlist).filter(KitOlist.ativo == 1).all()
        return JSONResponse({
            "total": len(kits),
            "kits": [{
                "id": k.id,
                "sku_kit": k.sku_kit,
                "nome_kit": k.nome_kit,
                "skus_componentes": k.skus_componentes.split("|"),
                "quantidade_componentes": k.quantidade_componentes,
                "criado_em": k.criado_em.isoformat()
            } for k in kits]
        })
    finally:
        db.close()


async def criar_kit(request: Request):
    """Cria um novo kit"""
    db = SessionLocal()
    try:
        data = await request.json()
        sku_kit = data.get("sku_kit", "").strip().upper()
        nome_kit = data.get("nome_kit", "")
        skus_componentes = data.get("skus_componentes", [])  # Lista de SKUs

        if not sku_kit or not skus_componentes:
            return JSONResponse(
                {"erro": "sku_kit e skus_componentes são obrigatórios"},
                status_code=400
            )

        # Verificar se já existe
        existe = db.query(KitOlist).filter(KitOlist.sku_kit == sku_kit).first()
        if existe:
            return JSONResponse(
                {"erro": f"Kit {sku_kit} já existe"},
                status_code=400
            )

        # Criar kit
        skus_str = "|".join([s.strip().upper() for s in skus_componentes])
        novo_kit = KitOlist(
            sku_kit=sku_kit,
            nome_kit=nome_kit,
            skus_componentes=skus_str,
            quantidade_componentes=len(skus_componentes),
            ativo=1
        )
        db.add(novo_kit)
        db.commit()

        return JSONResponse({
            "sucesso": True,
            "mensagem": f"Kit {sku_kit} criado com sucesso",
            "kit_id": novo_kit.id
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"erro": str(e)}, status_code=500)
    finally:
        db.close()


async def atualizar_kit(request: Request):
    """Atualiza um kit existente"""
    db = SessionLocal()
    try:
        data = await request.json()
        kit_id = data.get("id")
        nome_kit = data.get("nome_kit")
        skus_componentes = data.get("skus_componentes")

        kit = db.query(KitOlist).filter(KitOlist.id == kit_id).first()
        if not kit:
            return JSONResponse({"erro": "Kit não encontrado"}, status_code=404)

        if nome_kit:
            kit.nome_kit = nome_kit
        if skus_componentes:
            skus_str = "|".join([s.strip().upper() for s in skus_componentes])
            kit.skus_componentes = skus_str
            kit.quantidade_componentes = len(skus_componentes)

        kit.atualizado_em = datetime.utcnow()
        db.commit()

        return JSONResponse({
            "sucesso": True,
            "mensagem": f"Kit atualizado com sucesso"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"erro": str(e)}, status_code=500)
    finally:
        db.close()


async def deletar_kit(request: Request):
    """Deleta (inativa) um kit"""
    db = SessionLocal()
    try:
        data = await request.json()
        kit_id = data.get("id")

        kit = db.query(KitOlist).filter(KitOlist.id == kit_id).first()
        if not kit:
            return JSONResponse({"erro": "Kit não encontrado"}, status_code=404)

        kit.ativo = 0
        kit.atualizado_em = datetime.utcnow()
        db.commit()

        return JSONResponse({
            "sucesso": True,
            "mensagem": f"Kit deletado"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({"erro": str(e)}, status_code=500)
    finally:
        db.close()


async def vincular_kit_com_componentes(request: Request):
    """
    Vincula um item com um kit e seus componentes.
    Atualiza estoque para CADA componente do kit na Olist.
    """
    db = SessionLocal()
    try:
        data = await request.json()
        item_id = data.get("item_id")
        sku_kit = data.get("sku_kit", "").strip().upper()

        # Componentes: [{"sku": "V+RL3REPARO", "olist_produto_id": "123", "olist_nome": "...", "olist_preco": 50}, ...]
        componentes = data.get("componentes", [])

        if not item_id or not sku_kit or not componentes:
            return JSONResponse(
                {"erro": "item_id, sku_kit e componentes são obrigatórios"},
                status_code=400
            )

        item = db.query(ItemEstoque).filter(ItemEstoque.id == item_id).first()
        if not item:
            return JSONResponse({"erro": "Item não encontrado"}, status_code=404)

        # Vincular o item ao kit (armazenar como referência)
        item.olist_sku = sku_kit  # SKU do kit
        item.olist_nome = f"KIT: {sku_kit}"  # Marcar como kit
        item.vinculado_em = datetime.utcnow()
        item.estoque_olist_atualizado_em = datetime.utcnow()  # Marcar como subido
        print(f"[VINCULAR-KIT] Item {item_id}: vinculado_em={item.vinculado_em}, atualizado_em={item.estoque_olist_atualizado_em}")

        # Para cada componente, atualizar estoque na Olist
        resultados = []
        for comp in componentes:
            sku_comp = comp.get("sku", "").strip().upper()
            olist_produto_id = comp.get("olist_produto_id")
            olist_nome = comp.get("olist_nome", "")
            olist_preco = float(comp.get("olist_preco", 0) or 0)
            quantidade = float(item.quantidade_nf or 1)
            estoque_atual = comp.get("estoque_atual", 0)

            try:
                # Atualizar estoque do componente na Olist
                resultado_estoque = olist.atualizar_estoque(
                    produto_id=str(olist_produto_id),
                    quantidade=int(quantidade)
                )

                novo_estoque = int(estoque_atual) + int(quantidade) if resultado_estoque else estoque_atual

                resultados.append({
                    "sku": sku_comp,
                    "nome": olist_nome,
                    "sucesso": resultado_estoque,
                    "estoque_anterior": int(estoque_atual),
                    "quantidade_adicionada": int(quantidade) if resultado_estoque else 0,
                    "novo_estoque": novo_estoque
                })

            except Exception as e:
                resultados.append({
                    "sku": sku_comp,
                    "nome": olist_nome,
                    "sucesso": False,
                    "erro": str(e),
                    "estoque_anterior": int(estoque_atual)
                })

        db.commit()
        print(f"[VINCULAR-KIT] Dados salvos no banco! Item {item_id} agora tem estoque_olist_atualizado_em")

        return JSONResponse({
            "sucesso": True,
            "mensagem": f"Kit {sku_kit} vinculado com sucesso",
            "item_id": item_id,
            "resultados_componentes": resultados
        })

    except Exception as e:
        db.rollback()
        return JSONResponse({"erro": str(e)}, status_code=500)
    finally:
        db.close()

# ============== ENDPOINTS DE RECOMENDACOES =============

async def get_recomendacoes(request):
    """
    Retorna lista de recomendações de recompra.
    Query params:
    - filtro: critico|moderado|ok|todos (default: todos)
    - limite: 20 (default)
    - offset: 0 (default)
    """
    try:
        from app.utils.recomendacao_engine import calcular_recomendacoes

        filtro = request.query_params.get("filtro", "todos")
        limite = int(request.query_params.get("limite", 20))
        offset = int(request.query_params.get("offset", 0))

        db = SessionLocal()
        recomendacoes = calcular_recomendacoes(db)
        db.close()

        # Filtrar se necessário
        if filtro != "todos":
            recomendacoes = [r for r in recomendacoes if r.urgencia == filtro]

        # Paginação
        total = len(recomendacoes)
        recomendacoes = recomendacoes[offset : offset + limite]

        return JSONResponse({
            "total": total,
            "offset": offset,
            "limite": limite,
            "recomendacoes": [r.dict() for r in recomendacoes]
        })

    except Exception as e:
        print(f"Erro ao buscar recomendações: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_recomendacao_detalhada(request):
    """
    Retorna análise detalhada de uma recomendação.
    """
    try:
        from app.utils.recomendacao_engine import (
            obter_frequencia_venda, obter_fornecedores_produto,
            calcular_lead_time, obter_historico_precos, calcular_tendencia_preco
        )

        sku = request.path_params.get("sku")
        db = SessionLocal()

        # Análise de demanda
        demanda = obter_frequencia_venda(db, sku)

        # Estoque atual
        from sqlalchemy import func
        estoque_query = db.query(
            func.sum(ItemEstoque.quantidade_confirmada),
            func.sum(ItemEstoque.quantidade_confirmada * ItemEstoque.preco_unitario),
            func.sum(ItemEstoque.quantidade_confirmada * 2 * ItemEstoque.preco_unitario)  # Aproximação de preço venda
        ).filter(ItemEstoque.olist_sku == sku).first()

        estoque_atual = estoque_query[0] or 0
        valor_total_custo = estoque_query[1] or 0
        valor_total_venda = estoque_query[2] or 0

        frequencia_diaria = demanda["media_diaria"]
        cobertura_dias = estoque_atual / frequencia_diaria if frequencia_diaria > 0 else 999

        estoque_info = {
            "quantidade": int(estoque_atual),
            "valor_total_custo": round(float(valor_total_custo), 2),
            "valor_total_venda": round(float(valor_total_venda), 2),
            "cobertura_dias": round(cobertura_dias, 1),
            "status": "critico" if cobertura_dias < 3 else "ok" if cobertura_dias > 7 else "moderado"
        }

        # Fornecedores
        fornecedores_data = obter_fornecedores_produto(db, sku)
        fornecedores_list = []

        for f in fornecedores_data:
            lead_time_info = calcular_lead_time(db, f["nome"])
            historico_precos = obter_historico_precos(db, f["nome"], f["codigo_produto"])
            tendencia_preco = calcular_tendencia_preco(db, f["nome"], f["codigo_produto"])

            fornecedores_list.append({
                "nome": f["nome"],
                "preco_unitario": f["preco_unitario"],
                "lead_time_dias": lead_time_info["lead_time_dias"],
                "frequencia_compra": f["frequencia_compra"],
                "ultima_compra": None,  # Seria preciso rastrear data
                "historico_precos": historico_precos,
                "tendencia_preco": tendencia_preco,
                "motivo_recomendacao": None
            })

        # Recomendação final
        from app.utils.recomendacao_engine import (
            selecionar_melhor_fornecedor, calcular_quantidade_compra
        )

        melhor_fornecedor, _ = selecionar_melhor_fornecedor(db, sku, fornecedores_data)
        melhor_info = next((f for f in fornecedores_data if f["nome"] == melhor_fornecedor), None)

        if melhor_info:
            lead_time = melhor_info["lead_time_dias"]
            quantidade_recomendada = calcular_quantidade_compra(frequencia_diaria, lead_time)
            preco_unitario = melhor_info["preco_unitario"]
            custo_total = quantidade_recomendada * preco_unitario
            data_chegada = datetime.utcnow() + timedelta(days=lead_time)
            data_falta = datetime.utcnow() + timedelta(days=cobertura_dias)

            recomendacao_final = {
                "comprar_quantidade": quantidade_recomendada,
                "fornecedor": melhor_fornecedor,
                "preco_unitario": round(preco_unitario, 2),
                "custo_total": round(custo_total, 2),
                "prazo_entrega_dias": lead_time,
                "data_chegada_estimada": data_chegada.isoformat(),
                "estoque_sera_zero_em": data_falta.isoformat(),
                "cobertura_apos_compra": round(cobertura_dias + (quantidade_recomendada / frequencia_diaria), 1),
                "margem_estimada_30_dias": round(quantidade_recomendada * preco_unitario * 0.5, 2),  # Aproximação
                "roi_30_dias": round(1.5, 2)  # Aproximação
            }
        else:
            recomendacao_final = {}

        db.close()

        return JSONResponse({
            "sku": sku,
            "nome": "Produto",
            "analise_demanda": demanda,
            "estoque_atual": estoque_info,
            "fornecedores": fornecedores_list,
            "recomendacao_final": recomendacao_final
        })

    except Exception as e:
        print(f"Erro ao buscar recomendação detalhada: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def gerar_recomendacoes(request):
    """
    Força recálculo de todas as recomendações.
    Sincroniza com Olist e recalcula tudo.
    """
    try:
        from app.utils.recomendacao_engine import calcular_recomendacoes, salvar_recomendacoes
        from datetime import datetime

        db = SessionLocal()

        # Sincronizar histórico de vendas
        try:
            from app.integracoes_olist import olist
            vendas_sincronizadas = olist.sincronizar_historico_vendas(db, dias=30)
            print(f"Vendas sincronizadas: {vendas_sincronizadas}")
        except Exception as e:
            print(f"Aviso: não foi possível sincronizar vendas: {e}")

        # Calcular recomendações
        inicio = datetime.utcnow()
        recomendacoes = calcular_recomendacoes(db)

        # Salvar no BD
        salvar_recomendacoes(db, recomendacoes)

        tempo_calculo = (datetime.utcnow() - inicio).total_seconds()
        db.close()

        return JSONResponse({
            "status": "sucesso",
            "recomendacoes_geradas": len(recomendacoes),
            "tempo_calculo_segundos": round(tempo_calculo, 2),
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        print(f"Erro ao gerar recomendações: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def confirmar_compra_recomendacao(request):
    """
    Usuário confirmou que quer comprar a recomendação.
    Salva a ação e envia email ao fornecedor (future).
    """
    try:
        sku = request.path_params.get("sku")
        body = await request.json()

        quantidade = body.get("quantidade", 0)
        fornecedor = body.get("fornecedor", "")
        observacoes = body.get("observacoes", "")

        db = SessionLocal()

        # Marcar recomendação como comprada
        recomendacao = db.query(Recomendacao).filter(
            Recomendacao.olist_sku == sku
        ).first()

        if recomendacao:
            recomendacao.status_acao = "comprado"
            db.commit()

        db.close()

        # TODO: Enviar email ao fornecedor com os detalhes da compra

        return JSONResponse({
            "status": "sucesso",
            "id_pedido": None,  # Será preenchido quando email for enviado
            "mensagem": f"Pedido de {quantidade} unidades registrado para {fornecedor}. Email será enviado em breve."
        })

    except Exception as e:
        print(f"Erro ao confirmar compra: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


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
    Route("/api/olist/detectar-kit", detectar_kit_automatico, methods=["GET"]),
    Route("/api/olist/produtos-todos", listar_produtos_olist, methods=["GET"]),
    Route("/api/olist/vincular-produto", vincular_produto_olist, methods=["POST"]),
    Route("/api/olist/aceitar-sugestao", aceitar_sugestao_vinculo, methods=["POST"]),
    Route("/api/olist/atualizar-estoque", atualizar_estoque_olist, methods=["POST"]),
    # Memória de vínculos (de-para fornecedor -> Olist)
    Route("/api/olist/sugestao-vinculo", olist_sugestao_vinculo, methods=["GET"]),
    Route("/api/olist/vinculos", olist_listar_vinculos, methods=["GET"]),
    Route("/api/olist/vinculos/deletar", olist_deletar_vinculo, methods=["POST"]),
    # Kits (produtos compostos)
    Route("/api/olist/kits/verificar", verificar_kit, methods=["GET"]),
    Route("/api/olist/kits", listar_kits, methods=["GET"]),
    Route("/api/olist/kits/criar", criar_kit, methods=["POST"]),
    Route("/api/olist/kits/atualizar", atualizar_kit, methods=["POST"]),
    Route("/api/olist/kits/deletar", deletar_kit, methods=["POST"]),
    Route("/api/olist/kits/vincular-com-componentes", vincular_kit_com_componentes, methods=["POST"]),
    # Recomendações de Recompra
    Route("/api/recomendacoes", get_recomendacoes, methods=["GET"]),
    Route("/api/recomendacoes/{sku}", get_recomendacao_detalhada, methods=["GET"]),
    Route("/api/recomendacoes/gerar", gerar_recomendacoes, methods=["POST"]),
    Route("/api/recomendacoes/{sku}/confirmar-compra", confirmar_compra_recomendacao, methods=["POST"]),
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
