import { useState, useEffect } from 'react'
import { listNotasFiscais, NotaFiscal } from '../services/api'
import './NotaFiscalList.css'

interface NotaFiscalListProps {
  refresh: number
}

export default function NotaFiscalList({ refresh }: NotaFiscalListProps) {
  const [notas, setNotas] = useState<NotaFiscal[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadNotas = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await listNotasFiscais()
      setNotas(response.items)
    } catch (err: any) {
      setError('Erro ao carregar notas fiscais')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadNotas()
  }, [refresh])

  if (loading) {
    return <div className="loading">Carregando...</div>
  }

  if (error) {
    return <div className="error">{error}</div>
  }

  if (notas.length === 0) {
    return <div className="empty">Nenhuma nota fiscal processada ainda</div>
  }

  return (
    <div className="list-container">
      <div className="list">
        {notas.map(nota => (
          <div key={nota.id} className="nota-item">
            <div className="nota-header">
              <h3>NF #{nota.numero_nf}</h3>
              <span className={`status-badge status-${nota.status}`}>
                {nota.status}
              </span>
            </div>
            <div className="nota-details">
              <p><strong>Fornecedor:</strong> {nota.fornecedor}</p>
              <p><strong>Série:</strong> {nota.serie}</p>
              <p><strong>Itens:</strong> {nota.itens.length}</p>
              <p><strong>Data Upload:</strong> {new Date(nota.data_upload).toLocaleDateString('pt-BR')}</p>
            </div>
            <div className="items-preview">
              <h4>Produtos ({nota.itens.length})</h4>
              <div className="items-list">
                {nota.itens.slice(0, 3).map(item => (
                  <div key={item.id} className="item-row">
                    <span className="item-desc">{item.descricao}</span>
                    <span className="item-qty">{item.quantidade_nf} un</span>
                  </div>
                ))}
                {nota.itens.length > 3 && (
                  <div className="item-more">
                    + {nota.itens.length - 3} mais...
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
