import xml.etree.ElementTree as ET
from typing import Dict, Optional
import logging
import json

logger = logging.getLogger(__name__)

class NFeParsing:
    """Parse NF-e XML files to extract products and quantities"""

    @staticmethod
    def parse_xml(file_content: bytes) -> Dict:
        """
        Parse NF-e XML and extract relevant information

        Returns:
            {
                "numero_nf": str,
                "serie": str,
                "data_emissao": str,
                "fornecedor": str,
                "itens": [
                    {"codigo": str, "descricao": str, "quantidade": float, "preco": float}
                ]
            }
        """
        try:
            root = ET.fromstring(file_content)

            # Namespaces for NF-e
            ns = {
                'nfe': 'http://www.portalfiscal.inf.br/nfe',
            }

            # Extract header info
            ide = root.find('.//nfe:ide', ns)
            emit = root.find('.//nfe:emit', ns)

            numero_nf = ide.find('nfe:cUF', ns).text if ide is not None else "N/A"
            serie = ide.find('nfe:serie', ns).text if ide is not None else "1"
            data_emissao = ide.find('nfe:dhEmi', ns).text if ide is not None else None
            fornecedor = emit.find('nfe:xNome', ns).text if emit is not None else "Desconhecido"

            # Extract items
            itens = []
            for det in root.findall('.//nfe:det', ns):
                prod = det.find('nfe:prod', ns)
                if prod is not None:
                    item = {
                        "codigo": prod.find('nfe:cProd', ns).text if prod.find('nfe:cProd', ns) is not None else "",
                        "descricao": prod.find('nfe:xProd', ns).text if prod.find('nfe:xProd', ns) is not None else "",
                        "quantidade": float(prod.find('nfe:qCom', ns).text) if prod.find('nfe:qCom', ns) is not None else 0.0,
                        "preco": float(prod.find('nfe:vUnCom', ns).text) if prod.find('nfe:vUnCom', ns) is not None else 0.0,
                    }
                    itens.append(item)

            return {
                "numero_nf": numero_nf,
                "serie": serie,
                "data_emissao": data_emissao,
                "fornecedor": fornecedor,
                "itens": itens,
                "sucesso": True
            }

        except Exception as e:
            logger.error(f"Erro ao fazer parse do XML: {str(e)}")
            return {
                "sucesso": False,
                "erro": str(e),
                "itens": []
            }

    @staticmethod
    def parse_pdf_ocr(file_path: str) -> Dict:
        """
        Parse PDF using OCR (optional, phase 2)
        Requires pytesseract and poppler
        """
        try:
            from pdf2image import convert_from_path
            import pytesseract

            images = convert_from_path(file_path)
            texto_completo = ""

            for image in images:
                texto = pytesseract.image_to_string(image, lang='por')
                texto_completo += texto

            return {
                "sucesso": True,
                "texto": texto_completo,
                "requer_validacao_manual": True
            }

        except Exception as e:
            logger.error(f"Erro ao processar PDF com OCR: {str(e)}")
            return {
                "sucesso": False,
                "erro": str(e)
            }
