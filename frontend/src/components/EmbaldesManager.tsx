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
  nome_embale: string
  arquivo_original: string
  data_upload: string
  status: string
  observacoes?: string
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
  const [observacoes, setObservacoes] = useState('')
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
      formData.append('observacoes', observacoes)

      const resposta = await api.post('/embaldes/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      })

      setMessage(`✓ Embale "${nomeEmbale}" criado com sucesso! ${resposta.data.itens_validados}/${resposta.data.itens_processados} items vinculados à Olist`)
      setNomeEmbale('')
      setArquivo(null)
      setObservacoes('')

      // Recarregar lista
      await carregarEmbaldes()
    } catch (erro: any) {
      const msgErro = erro.response?.data?.erro || String(erro)
      setMessage('Erro ao fazer upload: ' + msgErro)
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
        <p style={{ color: '#666', fontSize: '0.9rem' }}>
          📋 Envie um arquivo PDF com a lista de separação dos produtos já separados para envio ao Marketplace.
          O sistema identificará automaticamente quais produtos já estão vinculados à Olist.
        </p>

        <form onSubmit={handleUpload}>
          <div style={{ marginBottom: '1rem' }}>
            <label>Nome do Embale:</label>
            <input
              type="text"
              placeholder="Ex: Embale 2024-01-15 (Semana 1)"
              value={nomeEmbale}
              onChange={(e) => setNomeEmbale(e.target.value)}
              style={{
                width: '100%',
                padding: '0.5rem',
                marginTop: '0.5rem',
                border: '1px solid #ddd',
                borderRadius: '4px'
              }}
            />
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <label>Arquivo PDF:</label>
            <input
              type="file"
              accept=".pdf"
              onChange={(e) => setArquivo(e.target.files?.[0] || null)}
              style={{
                width: '100%',
                padding: '0.5rem',
                marginTop: '0.5rem',
                border: '1px solid #ddd',
                borderRadius: '4px'
              }}
            />
            {arquivo && (
              <p style={{ color: '#4CAF50', fontSize: '0.9rem', marginTop: '0.5rem' }}>
                ✓ {arquivo.name}
              </p>
            )}
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <label>Observações (opcional):</label>
            <textarea
              placeholder="Ex: Preparado para envio segunda-feira..."
              value={observacoes}
              onChange={(e) => setObservacoes(e.target.value)}
              style={{
                width: '100%',
                padding: '0.5rem',
                marginTop: '0.5rem',
                border: '1px solid #ddd',
                borderRadius: '4px',
                minHeight: '80px'
              }}
            />
          </div>

          <button
            type="submit"
            disabled={loading || !arquivo || !nomeEmbale}
            style={{
              padding: '0.8rem 1.5rem',
              backgroundColor: loading ? '#ccc' : '#4CAF50',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontWeight: 'bold'
            }}
          >
            {loading ? 'Enviando...' : '📤 Fazer Upload'}
          </button>
        </form>

        {message && (
          <div style={{
            marginTop: '1rem',
            padding: '1rem',
            backgroundColor: message.includes('Erro') ? '#ffebee' : '#e8f5e9',
            color: message.includes('Erro') ? '#c62828' : '#2e7d32',
            borderRadius: '4px'
          }}>
            {message}
          </div>
        )}
      </div>

      {/* Lista de Embaldes */}
      <h3>Embaldes Criados</h3>

      {embaldes.length === 0 ? (
        <p style={{ color: '#999' }}>Nenhum embale criado ainda.</p>
      ) : (
        <div style={{ display: 'grid', gap: '1rem' }}>
          {embaldes.map((emb) => (
            <div
              key={emb.id}
              style={{
                border: '1px solid #ddd',
                borderRadius: '8px',
                padding: '1rem',
                cursor: 'pointer',
                backgroundColor: '#fafafa',
                transition: 'all 0.3s'
              }}
              onClick={() => carregarDetalhesEmbale(emb)}
            >
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
                <div>
                  <strong>{emb.nome_embale}</strong>
                  <p style={{ color: '#666', fontSize: '0.9rem', margin: '0.5rem 0 0 0' }}>
                    {new Date(emb.data_upload).toLocaleDateString('pt-BR')}
                  </p>
                </div>
                <div>
                  <p style={{ margin: '0', fontSize: '0.9rem' }}>
                    📄 {emb.arquivo_original}
                  </p>
                  <p style={{ margin: '0.5rem 0 0 0', color: '#666', fontSize: '0.85rem' }}>
                    Status: <strong>{emb.status}</strong>
                  </p>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <p style={{ margin: '0', fontSize: '0.9rem' }}>
                    ✓ {emb.qtd_validados}/{emb.qtd_items} items vinculados
                  </p>
                  <p style={{
                    margin: '0.5rem 0 0 0',
                    color: emb.qtd_validados === emb.qtd_items ? '#4CAF50' : '#ff9800',
                    fontWeight: 'bold',
                    fontSize: '0.85rem'
                  }}>
                    {emb.qtd_validados === emb.qtd_items
                      ? '✓ Pronto para processar'
                      : '⚠ Items não vinculados'}
                  </p>
                </div>
              </div>

              {/* Detalhes expandidos */}
              {expandidoDetalhes && embaleSelecionado?.id === emb.id && (
                <div style={{
                  marginTop: '1rem',
                  paddingTop: '1rem',
                  borderTop: '1px solid #eee'
                }}>
                  <h4>Items deste Embale:</h4>
                  <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                    {embaleSelecionado.itens?.map((item) => (
                      <div
                        key={item.id}
                        style={{
                          padding: '0.8rem',
                          marginBottom: '0.5rem',
                          backgroundColor: item.validado ? '#e8f5e9' : '#fff3e0',
                          borderRadius: '4px',
                          borderLeft: `4px solid ${item.validado ? '#4CAF50' : '#ff9800'}`
                        }}
                      >
                        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '1rem' }}>
                          <div>
                            <p style={{ margin: '0', fontWeight: 'bold', fontSize: '0.95rem' }}>
                              {item.titulo_anuncio}
                            </p>
                            {item.olist_nome && (
                              <p style={{ margin: '0.3rem 0 0 0', color: '#666', fontSize: '0.85rem' }}>
                                Vinculado: {item.olist_nome}
                              </p>
                            )}
                          </div>
                          <div>
                            <p style={{ margin: '0', fontSize: '0.9rem' }}>
                              <strong>{item.quantidade_separada}</strong> unidades
                            </p>
                          </div>
                          <div style={{ textAlign: 'right' }}>
                            <p style={{
                              margin: '0',
                              fontSize: '0.85rem',
                              color: item.validado ? '#4CAF50' : '#ff9800'
                            }}>
                              {item.validado ? '✓ Validado' : '⚠ Não validado'}
                            </p>
                            {item.validacao_mensagem && (
                              <p style={{ margin: '0.3rem 0 0 0', color: '#666', fontSize: '0.8rem' }}>
                                {item.validacao_mensagem}
                              </p>
                            )}
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
