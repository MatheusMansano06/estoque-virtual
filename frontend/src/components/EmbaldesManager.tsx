import { useState, useEffect } from 'react'
import api from '../services/api'

interface ItemEmbale {
  id: number
  titulo_anuncio: string
  quantidade_separada: number
  olist_produto_id?: string
  olist_sku?: string
  olist_nome?: string
  validado: number
  validacao_mensagem?: string
}

interface Embale {
  id: number
  nome_embalde: string
  arquivo_original: string
  data_upload: string
  status: string
  qtd_items: number
  qtd_validados: number
  itens?: ItemEmbale[]
}

export function EmbaldesManager() {
  const [embaldes, setEmbaldes] = useState<Embale[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [nomeEmbale, setNomeEmbale] = useState('')
  const [arquivo, setArquivo] = useState<File | null>(null)
  const [embaleSelecionado, setEmbaleSelecionado] = useState<Embale | null>(null)
  const [expandidoDetalhes, setExpandidoDetalhes] = useState(false)

  // Carregar embaldes ao montar
  useEffect(() => {
    carregarEmbaldes()
  }, [])

  const carregarEmbaldes = async () => {
    try {
      setLoading(true)
      const resposta = await api.get('/embaldes?limit=100')
      setEmbaldes(resposta.data.items)
    } catch (erro) {
      setMessage('Erro ao carregar embaldes: ' + String(erro))
    } finally {
      setLoading(false)
    }
  }

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!arquivo) {
      setMessage('Selecione um arquivo PDF')
      return
    }

    if (!nomeEmbale.trim()) {
      setMessage('Digite um nome para o embale')
      return
    }

    try {
      setLoading(true)
      setMessage('')

      const formData = new FormData()
      formData.append('arquivo', arquivo)
      formData.append('nome_embale', nomeEmbale)

      const resposta = await api.post('/embaldes/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      })

      setMessage(`✓ ${resposta.data.itens_validados}/${resposta.data.itens_processados} items vinculados à Olist`)
      setNomeEmbale('')
      setArquivo(null)

      // Recarregar lista
      await carregarEmbaldes()
    } catch (erro: any) {
      const msgErro = erro.response?.data?.erro || String(erro)
      setMessage('Erro: ' + msgErro)
    } finally {
      setLoading(false)
    }
  }

  const carregarDetalhesEmbale = async (emb: Embale) => {
    try {
      const resposta = await api.get(`/embaldes/${emb.id}`)
      setEmbaleSelecionado(resposta.data)
      setExpandidoDetalhes(true)
    } catch (erro) {
      setMessage('Erro ao carregar detalhes: ' + String(erro))
    }
  }

  return (
    <div style={{ padding: '2rem' }}>
      <h2>📦 Lista de Separação (Embaldes para FU)</h2>

      {/* Formulário de Upload */}
      <div style={{
        backgroundColor: '#f5f5f5',
        padding: '1.5rem',
        borderRadius: '8px',
        marginBottom: '2rem',
        border: '2px dashed #ccc'
      }}>
        <h3>Fazer Upload de Embale</h3>

        <form onSubmit={handleUpload}>
          <div style={{ marginBottom: '1rem' }}>
            <label style={{ fontWeight: 'bold' }}>Nome do Embale:</label>
            <input
              type="text"
              placeholder="Ex: Embale Semana 1"
              value={nomeEmbale}
              onChange={(e) => setNomeEmbale(e.target.value)}
              disabled={loading}
              style={{
                width: '100%',
                padding: '0.75rem',
                marginTop: '0.5rem',
                border: '1px solid #ddd',
                borderRadius: '4px',
                fontSize: '1rem'
              }}
            />
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ fontWeight: 'bold' }}>Arquivo PDF:</label>
            <div style={{
              border: '2px solid #ddd',
              borderRadius: '4px',
              padding: '1.5rem',
              textAlign: 'center',
              backgroundColor: '#fafafa',
              cursor: 'pointer'
            }}>
              <input
                type="file"
                accept=".pdf"
                onChange={(e) => setArquivo(e.target.files?.[0] || null)}
                disabled={loading}
                style={{
                  display: 'none'
                }}
                id="pdf-input"
              />
              <label htmlFor="pdf-input" style={{ cursor: 'pointer', display: 'block' }}>
                {arquivo ? (
                  <div style={{ color: '#4CAF50', fontWeight: 'bold' }}>
                    ✓ {arquivo.name}
                  </div>
                ) : (
                  <div>
                    <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>📄</div>
                    <div style={{ color: '#666' }}>Clique ou arraste um PDF aqui</div>
                  </div>
                )}
              </label>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || !arquivo || !nomeEmbale}
            style={{
              padding: '0.9rem 2rem',
              backgroundColor: loading ? '#ccc' : '#4CAF50',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontWeight: 'bold',
              fontSize: '1rem'
            }}
          >
            {loading ? 'Processando...' : '📤 Fazer Upload'}
          </button>
        </form>

        {message && (
          <div style={{
            marginTop: '1rem',
            padding: '1rem',
            backgroundColor: message.includes('Erro') ? '#ffebee' : '#e8f5e9',
            color: message.includes('Erro') ? '#c62828' : '#2e7d32',
            borderRadius: '4px',
            fontWeight: 'bold'
          }}>
            {message}
          </div>
        )}
      </div>

      {/* Lista de Embaldes */}
      <h3>Embaldes Criados</h3>

      {embaldes.length === 0 ? (
        <p style={{ color: '#999', textAlign: 'center', padding: '2rem' }}>
          Nenhum embale criado ainda.
        </p>
      ) : (
        <div style={{ display: 'grid', gap: '1rem' }}>
          {embaldes.map((emb) => (
            <div
              key={emb.id}
              style={{
                border: '1px solid #ddd',
                borderRadius: '8px',
                padding: '1.5rem',
                cursor: 'pointer',
                backgroundColor: '#fafafa',
                transition: 'all 0.3s'
              }}
              onClick={() => carregarDetalhesEmbale(emb)}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = '#f0f0f0'
                e.currentTarget.style.boxShadow = '0 2px 4px rgba(0,0,0,0.1)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = '#fafafa'
                e.currentTarget.style.boxShadow = 'none'
              }}
            >
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '2rem', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>{emb.nome_embalde}</div>
                  <div style={{ color: '#666', fontSize: '0.9rem', marginTop: '0.5rem' }}>
                    {new Date(emb.data_upload).toLocaleDateString('pt-BR')}
                  </div>
                </div>
                <div style={{ color: '#666', fontSize: '0.9rem' }}>
                  {emb.arquivo_original}
                </div>
                <div style={{ textAlign: 'right', fontWeight: 'bold' }}>
                  <div style={{
                    fontSize: '1.2rem',
                    color: emb.qtd_validados === emb.qtd_items ? '#4CAF50' : '#ff9800'
                  }}>
                    ✓ {emb.qtd_validados}/{emb.qtd_items}
                  </div>
                  <div style={{ fontSize: '0.85rem', color: '#666', marginTop: '0.25rem' }}>
                    items vinculados
                  </div>
                </div>
              </div>

              {/* Detalhes expandidos */}
              {expandidoDetalhes && embaleSelecionado?.id === emb.id && (
                <div style={{
                  marginTop: '1.5rem',
                  paddingTop: '1.5rem',
                  borderTop: '1px solid #eee'
                }}>
                  <h4 style={{ marginTop: 0 }}>Items:</h4>
                  <div style={{ display: 'grid', gap: '0.75rem', maxHeight: '400px', overflowY: 'auto' }}>
                    {embaleSelecionado.itens?.map((item) => (
                      <div
                        key={item.id}
                        style={{
                          padding: '1rem',
                          backgroundColor: item.validado ? '#e8f5e9' : '#fff3e0',
                          borderRadius: '4px',
                          borderLeft: `4px solid ${item.validado ? '#4CAF50' : '#ff9800'}`
                        }}
                      >
                        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr auto', gap: '1rem', alignItems: 'center' }}>
                          <div>
                            <div style={{ fontWeight: 'bold' }}>{item.titulo_anuncio}</div>
                            {item.olist_nome && (
                              <div style={{ fontSize: '0.85rem', color: '#666', marginTop: '0.25rem' }}>
                                → {item.olist_nome}
                              </div>
                            )}
                          </div>
                          <div style={{ textAlign: 'center' }}>
                            <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>{Math.round(item.quantidade_separada)}</div>
                            <div style={{ fontSize: '0.8rem', color: '#666' }}>un</div>
                          </div>
                          <div style={{
                            padding: '0.4rem 0.8rem',
                            backgroundColor: item.validado ? '#4CAF50' : '#ff9800',
                            color: 'white',
                            borderRadius: '4px',
                            fontSize: '0.85rem',
                            fontWeight: 'bold'
                          }}>
                            {item.validado ? '✓' : '⚠'}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
