import axios, { AxiosInstance } from 'axios'

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api'

const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

export interface UploadResponse {
  id: number
  numero_nf: string
  status: string
  itens_encontrados: number
  erros?: string
}

export interface NotaFiscalItem {
  id: number
  codigo_produto: string
  descricao: string
  quantidade_nf: number
  quantidade_confirmada?: number
  preco_unitario: number
  status: string
  divergencia?: string
  data_criacao: string
}

export interface NotaFiscal {
  id: number
  numero_nf: string
  serie: string
  fornecedor: string
  data_emissao: string
  data_upload: string
  arquivo_original: string
  status: string
  erros?: string
  itens: NotaFiscalItem[]
}

export interface NotaFiscalList {
  total: number
  skip: number
  limit: number
  items: NotaFiscal[]
}

export const uploadNFe = (file: File): Promise<UploadResponse> => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/upload-nfe', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  }).then(res => res.data)
}

export const getNotaFiscal = (id: number): Promise<NotaFiscal> => {
  return api.get(`/notas-fiscais/${id}`).then(res => res.data)
}

export const listNotasFiscais = (skip: number = 0, limit: number = 10): Promise<NotaFiscalList> => {
  return api.get('/notas-fiscais', {
    params: { skip, limit }
  }).then(res => res.data)
}

export default api
