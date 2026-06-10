"""
Parser para arquivos PDF de embaldes/listas de separação
Extrai título do anúncio e quantidade separada
"""

import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import re
from typing import List, Tuple

def extrair_items_embale_pdf(caminho_pdf: str) -> List[dict]:
    """
    Extrai items de um PDF de lista de separação
    Tenta identificar padrões de: "Título do Produto | Quantidade"

    Retorna: [{"titulo_anuncio": str, "quantidade_separada": float}, ...]
    """
    try:
        # Converter PDF para imagens
        imagens = convert_from_path(caminho_pdf)
        texto_completo = ""

        # OCR cada página
        for imagem in imagens:
            texto = pytesseract.image_to_string(imagem, lang='por')
            texto_completo += texto + "\n"

        # Extrair items
        items = _parsear_texto_embale(texto_completo)
        return items

    except Exception as e:
        return {
            "erro": True,
            "mensagem": f"Erro ao processar PDF: {str(e)}"
        }


def _parsear_texto_embale(texto: str) -> List[dict]:
    """
    Parseia texto OCR para extrair items da lista de separação
    Padrões esperados:
    - "Produto XYZ | 100"
    - "Produto XYZ 100"
    - "SKU: PRODUTO | QTD: 100"
    """
    items = []
    linhas = texto.split('\n')

    for linha in linhas:
        linha = linha.strip()
        if not linha or len(linha) < 5:
            continue

        # Padrão 1: "algo | número"
        if '|' in linha:
            partes = linha.split('|')
            if len(partes) >= 2:
                titulo = partes[0].strip()
                qtd_str = partes[-1].strip()
                qtd = _extrair_quantidade(qtd_str)

                if qtd and titulo and len(titulo) > 3:
                    items.append({
                        "titulo_anuncio": titulo,
                        "quantidade_separada": qtd,
                        "validado": 0,
                        "validacao_mensagem": None
                    })

        # Padrão 2: última palavra é número
        else:
            partes = linha.rsplit(' ', 1)
            if len(partes) == 2:
                titulo = partes[0].strip()
                qtd_str = partes[1].strip()
                qtd = _extrair_quantidade(qtd_str)

                if qtd and titulo and len(titulo) > 3:
                    items.append({
                        "titulo_anuncio": titulo,
                        "quantidade_separada": qtd,
                        "validado": 0,
                        "validacao_mensagem": None
                    })

    # Remover duplicatas
    items_unicos = []
    titles_vistos = set()
    for item in items:
        if item["titulo_anuncio"] not in titles_vistos:
            items_unicos.append(item)
            titles_vistos.add(item["titulo_anuncio"])

    return items_unicos


def _extrair_quantidade(texto: str) -> float:
    """Extrai número float do texto"""
    try:
        # Remover tudo que não é número ou ponto
        numeros = re.findall(r'\d+[.,]?\d*', texto)
        if numeros:
            quantidade = numeros[0].replace(',', '.')
            return float(quantidade)
    except:
        pass
    return None
