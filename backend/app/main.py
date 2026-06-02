from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse, FileResponse, RedirectResponse, HTMLResponse
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

from app.models import NotaFiscal, ItemEstoque, ConfirmacaoEstoque, StatusEstoque
from app.utils.nfe_parser import NFeParsing
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
                "itens": [serialize_item(item) for item in nf.itens]
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
            "itens": [serialize_item(item) for item in nf.itens]
        })
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


routes = [
    Route("/", root, methods=["GET"]),
    Route("/api/upload-nfe", upload_nfe, methods=["POST"]),
    Route("/api/notas-fiscais", get_nfs, methods=["GET"]),
    Route("/api/notas-fiscais/{nf_id}", get_nf, methods=["GET"]),
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
    Route("/api/olist/vincular-produto", vincular_produto_olist, methods=["POST"]),
    Route("/api/olist/atualizar-estoque", atualizar_estoque_olist, methods=["POST"]),
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
