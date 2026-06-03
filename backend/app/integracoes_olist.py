"""
Integracao Profissional com Olist/Tiny ERP - API v3 (OAuth2 Authorization Code)
Endpoints de PRODUCAO corretos.

Fluxo:
1. Usuario acessa /api/olist/conectar -> redireciona para login Olist
2. Usuario autoriza no navegador
3. Olist redireciona de volta para /api/olist/callback com 'code'
4. Trocamos 'code' por access_token + refresh_token
5. Token e salvo em arquivo e renovado automaticamente
"""

import os
import json
import base64
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dotenv import load_dotenv

load_dotenv()

# Caminho para armazenar o token de forma persistente
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "..", "olist_token.json")


class OlistIntegration:
    """Integracao com Olist/Tiny ERP - API v3 OAuth2 Authorization Code"""

    # Endpoints de PRODUCAO (Tiny ERP)
    AUTH_URL = "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth"
    TOKEN_URL = "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/token"
    API_BASE = "https://api.tiny.com.br/public-api/v3"

    def __init__(self):
        self.client_id = os.getenv("OLIST_CLIENT_ID", "")
        self.client_secret = os.getenv("OLIST_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv(
            "OLIST_REDIRECT_URI",
            "http://localhost:8000/api/olist/callback"
        )
        self.enabled = bool(self.client_id and self.client_secret)

        # Token simples v2 (fallback legado)
        self.token_v2 = os.getenv("OLIST_API_TOKEN_SIMPLE", "")

    # ========== PERSISTENCIA DE TOKEN ==========

    def _salvar_token(self, dados: Dict):
        """Salva token em arquivo JSON"""
        try:
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                json.dump(dados, f, indent=2)
            print("[OLIST] Token salvo com sucesso")
        except Exception as e:
            print(f"[OLIST] Erro ao salvar token: {e}")

    def _carregar_token(self) -> Optional[Dict]:
        """Carrega token do arquivo JSON"""
        try:
            if os.path.exists(TOKEN_FILE):
                with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"[OLIST] Erro ao carregar token: {e}")
        return None

    # ========== FLUXO OAUTH2 ==========

    def get_authorization_url(self) -> str:
        """Gera a URL para o usuario autorizar o app no Olist"""
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "openid"
        }
        query = urllib.parse.urlencode(params)
        return f"{self.AUTH_URL}?{query}"

    def _basic_auth_header(self) -> str:
        """Gera header Basic Auth: base64(client_id:client_secret)"""
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"

    def trocar_code_por_token(self, code: str) -> bool:
        """
        Troca o authorization code por access_token + refresh_token
        Chamado pelo callback apos usuario autorizar
        """
        try:
            print("[OLIST] Trocando code por token...")

            data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri
            }

            post_data = urllib.parse.urlencode(data).encode("utf-8")
            headers = {
                "Authorization": self._basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded"
            }

            req = urllib.request.Request(
                self.TOKEN_URL, data=post_data, headers=headers, method="POST"
            )

            with urllib.request.urlopen(req, timeout=15) as response:
                resposta = json.loads(response.read().decode("utf-8"))

                if "access_token" in resposta:
                    expires_in = resposta.get("expires_in", 3600)
                    expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()

                    dados = {
                        "access_token": resposta["access_token"],
                        "refresh_token": resposta.get("refresh_token", ""),
                        "expires_at": expires_at,
                        "obtido_em": datetime.utcnow().isoformat()
                    }
                    self._salvar_token(dados)
                    print("[OLIST] Autorizacao concluida com sucesso!")
                    return True

                print(f"[OLIST] Resposta sem token: {resposta}")
                return False

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            print(f"[OLIST] Erro HTTP {e.code} ao trocar code: {error_body}")
            return False
        except Exception as e:
            print(f"[OLIST] Erro ao trocar code: {e}")
            return False

    def _renovar_token(self, refresh_token: str) -> Optional[str]:
        """Renova o access_token usando o refresh_token"""
        try:
            print("[OLIST] Renovando token...")

            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }

            post_data = urllib.parse.urlencode(data).encode("utf-8")
            headers = {
                "Authorization": self._basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded"
            }

            req = urllib.request.Request(
                self.TOKEN_URL, data=post_data, headers=headers, method="POST"
            )

            with urllib.request.urlopen(req, timeout=15) as response:
                resposta = json.loads(response.read().decode("utf-8"))

                if "access_token" in resposta:
                    expires_in = resposta.get("expires_in", 3600)
                    expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()

                    dados = {
                        "access_token": resposta["access_token"],
                        "refresh_token": resposta.get("refresh_token", refresh_token),
                        "expires_at": expires_at,
                        "obtido_em": datetime.utcnow().isoformat()
                    }
                    self._salvar_token(dados)
                    print("[OLIST] Token renovado com sucesso")
                    return dados["access_token"]

        except Exception as e:
            print(f"[OLIST] Erro ao renovar token: {e}")

        return None

    def get_access_token(self) -> Optional[str]:
        """
        Obtem um access_token valido.
        - Carrega do arquivo
        - Renova se expirado
        - Retorna None se nunca foi autorizado
        """
        dados = self._carregar_token()
        if not dados:
            return None

        # Verificar validade
        expires_at = dados.get("expires_at")
        if expires_at:
            # Renovar 60s antes de expirar
            if datetime.utcnow() < (datetime.fromisoformat(expires_at) - timedelta(seconds=60)):
                return dados["access_token"]

        # Token expirado: tentar renovar
        refresh_token = dados.get("refresh_token")
        if refresh_token:
            return self._renovar_token(refresh_token)

        return None

    # ========== OPERACOES NA API ==========

    def listar_todos_produtos(self, limite: int = 100) -> List[Dict]:
        """Lista todos os produtos da Olist (com limite)"""
        token = self.get_access_token()
        if not token:
            token = self.token_v2
            if not token:
                return []

        try:
            # Tentar com diferentes parâmetros de paginação
            url = f"{self.API_BASE}/produtos?pageSize={limite}"
            print(f"[OLIST] Listando produtos: {url}")
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            req = urllib.request.Request(url, headers=headers, method="GET")

            with urllib.request.urlopen(req, timeout=15) as response:
                resposta = json.loads(response.read().decode("utf-8"))
                produtos = resposta.get("itens") or resposta.get("data") or resposta.get("results") or (resposta if isinstance(resposta, list) else [])

                resultado = []
                for prod in produtos:
                    resultado.append({
                        "id": prod.get("id", ""),
                        "sku": prod.get("sku") or prod.get("codigo", ""),
                        "nome": prod.get("descricao") or prod.get("nome", ""),
                        "preco": float(prod.get("precos", {}).get("preco", 0) if isinstance(prod.get("precos"), dict) else prod.get("preco", 0) or 0),
                    })

                print(f"[OLIST] {len(resultado)} produto(s) listados")
                return resultado
        except Exception as e:
            print(f"[OLIST] Erro ao listar produtos: {e}")
            return []

    def buscar_produtos(self, termo: str) -> List[Dict]:
        """Busca produtos na API v3 por codigo (SKU) ou nome"""
        if not termo or len(termo) < 1:
            return []

        token = self.get_access_token()
        if not token:
            # Fallback para token simples (legado v2)
            token = self.token_v2
            if not token:
                print("[OLIST] Nao autorizado - acesse /api/olist/conectar ou configure OLIST_API_TOKEN_SIMPLE")
                return []

        # Tenta buscar por codigo (SKU) primeiro, depois por nome
        resultado = []
        for campo in ["codigo", "nome"]:
            resultado = self._buscar_por_campo(token, campo, termo)
            if resultado:
                break

        # Se nenhum resultado encontrado via filtro, fazer busca local
        if not resultado:
            print(f"[OLIST] Nenhum resultado via API, tentando busca local...")
            todos = self.listar_todos_produtos(limite=500)
            termo_lower = termo.lower()
            resultado = [p for p in todos if termo_lower in p.get('nome', '').lower() or termo_lower in p.get('sku', '').lower()]
            if resultado:
                print(f"[OLIST] {len(resultado)} produto(s) encontrado(s) via busca local")

        # Enriquecer com estoque real (saldo/disponivel)
        for prod in resultado:
            if prod.get("id"):
                estoque = self.obter_estoque(str(prod["id"]))
                if estoque:
                    prod["estoque_atual"] = estoque["disponivel"]
                    prod["estoque_saldo"] = estoque["saldo"]
                    prod["estoque_reservado"] = estoque["reservado"]

        return resultado

    def obter_estoque(self, produto_id: str) -> Optional[Dict]:
        """Obtem o estoque atual de um produto (saldo, reservado, disponivel)"""
        token = self.get_access_token()
        if not token:
            # Fallback para token simples (legado v2)
            token = self.token_v2
            if not token:
                return None

        try:
            url = f"{self.API_BASE}/estoque/{produto_id}"
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            req = urllib.request.Request(url, headers=headers, method="GET")

            with urllib.request.urlopen(req, timeout=15) as response:
                dados = json.loads(response.read().decode("utf-8"))
                return {
                    "saldo": int(dados.get("saldo", 0) or 0),
                    "reservado": int(dados.get("reservado", 0) or 0),
                    "disponivel": int(dados.get("disponivel", 0) or 0),
                }
        except Exception as e:
            print(f"[OLIST] Erro ao obter estoque de {produto_id}: {e}")
            return None

    def _buscar_por_campo(self, token: str, campo: str, termo: str) -> List[Dict]:
        """Busca produtos por um campo especifico"""
        try:
            # Tentar busca com filtro exato primeiro
            params = {campo: termo, "limit": 50}
            query = urllib.parse.urlencode(params)
            url = f"{self.API_BASE}/produtos?{query}"

            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }

            print(f"[OLIST] Buscando por {campo}='{termo}' em {url}")
            req = urllib.request.Request(url, headers=headers, method="GET")

            with urllib.request.urlopen(req, timeout=15) as response:
                resposta = json.loads(response.read().decode("utf-8"))

                # API v3 retorna {"itens": [...]} ou {"data": [...]} ou lista direta
                produtos = []
                if isinstance(resposta, dict):
                    produtos = (resposta.get("itens") or resposta.get("data")
                                or resposta.get("results") or [])
                elif isinstance(resposta, list):
                    produtos = resposta

                resultado = []
                for prod in produtos:
                    resultado.append({
                        "id": prod.get("id", ""),
                        "sku": prod.get("sku") or prod.get("codigo", ""),
                        "codigo_produto": prod.get("sku") or prod.get("codigo", ""),
                        "nome": prod.get("descricao") or prod.get("nome", ""),
                        "descricao": prod.get("descricao") or prod.get("nome", ""),
                        "preco": float(prod.get("precos", {}).get("preco", 0) if isinstance(prod.get("precos"), dict) else prod.get("preco", 0) or 0),
                        "estoque_atual": int(prod.get("estoque", {}).get("quantidade", 0) if isinstance(prod.get("estoque"), dict) else prod.get("estoque", 0) or 0),
                    })

                if resultado:
                    print(f"[OLIST] {len(resultado)} produto(s) por '{campo}'='{termo}'")
                return resultado

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            print(f"[OLIST] Erro HTTP {e.code} buscando por {campo}: {error_body[:200]}")
            return []
        except Exception as e:
            print(f"[OLIST] Erro buscando por {campo}: {e}")
            return []

    def atualizar_estoque(self, produto_id: str, quantidade: float,
                          tipo: str = "E", preco_unitario: float = 0,
                          observacao: str = "Entrada via Estoque Virtual (NF-e)") -> bool:
        """
        Atualiza o estoque de um produto na Olist
        tipo: 'E' = Entrada (soma), 'S' = Saida (subtrai), 'B' = Balanco (absoluto)
        """
        token = self.get_access_token()
        if not token:
            # Fallback para token simples (legado v2)
            token = self.token_v2
            if not token:
                return False

        try:
            url = f"{self.API_BASE}/estoque/{produto_id}"
            data = {
                "tipo": tipo,
                "quantidade": float(quantidade),
                "precoUnitario": float(preco_unitario),
                "observacoes": observacao
            }
            post_data = json.dumps(data).encode("utf-8")
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            req = urllib.request.Request(url, data=post_data, headers=headers, method="POST")

            with urllib.request.urlopen(req, timeout=15) as response:
                print(f"[OLIST] Estoque ({tipo}) atualizado: produto {produto_id} qtd {quantidade}")
                return True

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            print(f"[OLIST] Erro HTTP {e.code} ao atualizar estoque: {error_body[:300]}")
            return False
        except Exception as e:
            print(f"[OLIST] Erro ao atualizar estoque: {e}")
            return False

    def status(self) -> Dict:
        """Retorna status da integracao"""
        token = self.get_access_token()
        autorizado = token is not None

        return {
            "integrado": autorizado,
            "credenciais_configuradas": self.enabled,
            "autorizado": autorizado,
            "status": "OK Pronto" if autorizado else "PRECISA AUTORIZAR",
            "url_autorizacao": self.get_authorization_url() if (self.enabled and not autorizado) else None,
            "mensagem": (
                "Integracao ativa e funcionando!" if autorizado
                else "Acesse /api/olist/conectar para autorizar o aplicativo"
            )
        }


# Instancia global
olist = OlistIntegration()
