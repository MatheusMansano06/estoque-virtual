import { useState, useEffect } from 'react'
import api from '../services/api'

interface ItemInbound {
  id: number
  titulo_anuncio: string
  quantidade_separada: number
  sku_inbound?: string
  codigo_ml?: string
  olist_produto_id?: string
  olist_sku?: string
  olist_nome?: string
  validado: number
  validacao_mensagem?: string
}

interface Inbound {
  id: number
  nome_embalde: string
  numero_inbound?: string
  total_unidades?: number
  arquivo_original: string
  data_upload: string
  status: string
  qtd_items: number
  qtd_validados: number
  itens?: ItemInbound[]
}

export function EmbaldesManager() {
  const [inbounds, setInbounds] = useState<Inbound[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [nomeInbound, setNomeInbound] = useState('')
  const [arquivo, setArquivo] = useState<File | null>(null)
  const [inboundSelecionado, setInboundSelecionado] = useState<Inbound | null>(null)

  useEffect(() => {
    carregarInbounds()
  }, [])

  const carregarInbounds = async () => {
    try {
      setLoading(true)
      const resposta = await api.get('/embaldes?limit=100')
      setInbounds(resposta.data.items)
    } catch (erro) {
      setMessage('Erro ao carregar inbounds: ' + String(erro))
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

    if (!nomeInbound.trim()) {
      setMessage('Digite um nome para o inbound')
      return
    }

    try {
      setLoading(true)
      setMessage('')

      const formData = new FormData()
      formData.append('arquivo', arquivo)
      formData.append('nome_embale', nomeInbound)

      const resposta = await api.post('/embaldes/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })

      const d = resposta.data
      setMessage(`Inbound ${d.numero_inbound || ''} processado: ${d.itens_validados}/${d.itens_processados} items vinculados`)
      setNomeInbound('')
      setArquivo(null)

      await carregarInbounds()
    } catch (erro: any) {
      const msgErro = erro.response?.data?.erro || String(erro)
      setMessage('Erro: ' + msgErro)
    } finally {
      setLoading(false)
    }
  }

  const carregarDetalhes = async (inb: Inbound) => {
    // Toggle: fecha se já estiver aberto
    if (inboundSelecionado?.id === inb.id) {
      setInboundSelecionado(null)
      return
    }
    try {
      const resposta = await api.get(`/embaldes/${inb.id}`)
      setInboundSelecionado(resposta.data)
    } catch (erro) {
      setMessage('Erro ao carregar detalhes: ' + String(erro))
    }
  }

  return (
    <div style={{ padding: '2rem' }}>
      <h2>Lista de Separação (Inbound ML FULL)</h2>

      {/* Formulário de Upload */}
      <div style={{
        backgroundColor: '#f5f5f5',
        padding: '1.5rem',
        borderRadius: '8px',
        marginBottom: '2rem',
        border: '1px solid #ddd'
      }}>
        <h3 style={{ marginTop: 0 }}>Subir Inbound</h3>
        <p style={{ color: '#666', fontSize: '0.9rem', marginBottom: '1.5rem' }}>
          Envie o PDF de instruções de preparação do Mercado Livre FULL. O sistema lê o
          SKU de cada produto e verifica se já existe um anúncio vinculado na Olist.
        </p>

        <form onSubmit={handleUpload}>
          <div style={{ marginBottom: '1rem' }}>
            <label style={{ fontWeight: 'bold', display: 'block', marginBottom: '0.5rem' }}>
              Nome do Inbound:
            </label>
            <input
              type="text"
              placeholder="Ex: Inbound Semana 1"
              value={nomeInbound}
              onChange={(e) => setNomeInbound(e.target.value)}
              disabled={loading}
              style={{
                width: '100%',
                padding: '0.75rem',
                border: '1px solid #ddd',
                borderRadius: '4px',
                fontSize: '1rem'
              }}
            />
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ fontWeight: 'bold', display: 'block', marginBottom: '0.5rem' }}>
              Arquivo PDF:
            </label>
            <div style={{
              border: '2px dashed #ccc',
              borderRadius: '4px',
              padding: '1.5rem',
              textAlign: 'center',
              backgroundColor: '#fff'
            }}>
              <input
                type="file"
                accept=".pdf"
                onChange={(e) => setArquivo(e.target.files?.[0] || null)}
                disabled={loading}
                style={{ display: 'none' }}
                id="pdf-input"
              />
              <label htmlFor="pdf-input" style={{ cursor: 'pointer', display: 'block' }}>
                {arquivo ? (
                  <div style={{ color: '#2e7d32', fontWeight: 'bold' }}>
                    {arquivo.name}
                  </div>
                ) : (
                  <div style={{ color: '#666' }}>
                    Clique para selecionar um PDF
                  </div>
                )}
              </label>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || !arquivo || !nomeInbound}
            style={{
              padding: '0.9rem 2rem',
              backgroundColor: (loading || !arquivo || !nomeInbound) ? '#ccc' : '#1976D2',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: (loading || !arquivo || !nomeInbound) ? 'not-allowed' : 'pointer',
              fontWeight: 'bold',
              fontSize: '1rem'
            }}
          >
            {loading ? 'Processando...' : 'Subir Inbound'}
          </button>
        </form>

        {message && (
          <div style={{
            marginTop: '1rem',
            padding: '1rem',
            backgroundColor: message.toLowerCase().includes('erro') ? '#ffebee' : '#e8f5e9',
            color: message.toLowerCase().includes('erro') ? '#c62828' : '#2e7d32',
            borderRadius: '4px',
            fontWeight: 'bold'
          }}>
            {message}
          </div>
        )}
      </div>

      {/* Lista de Inbounds */}
      <h3>Inbounds Subidos</h3>

      {inbounds.length === 0 ? (
        <p style={{ color: '#999', textAlign: 'center', padding: '2rem' }}>
          Nenhum inbound subido ainda.
        </p>
      ) : (
        <div style={{ display: 'grid', gap: '1rem' }}>
          {inbounds.map((inb) => (
            <div
              key={inb.id}
              style={{
                border: '1px solid #ddd',
                borderRadius: '8px',
                padding: '1.5rem',
                cursor: 'pointer',
                backgroundColor: '#fff'
              }}
              onClick={() => carregarDetalhes(inb)}
            >
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '1.5rem', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>{inb.nome_embalde}</div>
                  <div style={{ color: '#666', fontSize: '0.85rem', marginTop: '0.4rem' }}>
                    {inb.numero_inbound ? `Frete #${inb.numero_inbound}` : 'Sem número'}
                    {' · '}
                    {new Date(inb.data_upload).toLocaleDateString('pt-BR')}
                  </div>
                </div>
                <div style={{ color: '#666', fontSize: '0.85rem' }}>
                  {inb.total_unidades ? `${Math.round(inb.total_unidades)} unidades` : ''}
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{
                    fontSize: '1.2rem',
                    fontWeight: 'bold',
                    color: inb.qtd_validados === inb.qtd_items ? '#2e7d32' : '#ef6c00'
                  }}>
                    {inb.qtd_validados}/{inb.qtd_items}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: '#666' }}>
                    items vinculados
                  </div>
                </div>
              </div>

              {/* Detalhes expandidos */}
              {inboundSelecionado?.id === inb.id && (
                <div style={{
                  marginTop: '1.5rem',
                  paddingTop: '1.5rem',
                  borderTop: '1px solid #eee'
                }}>
                  <div style={{ display: 'grid', gap: '0.75rem' }}>
                    {inboundSelecionado.itens?.map((item) => (
                      <div
                        key={item.id}
                        style={{
                          padding: '1rem',
                          backgroundColor: item.validado ? '#f1f8f4' : '#fff8f0',
                          borderRadius: '4px',
                          borderLeft: `4px solid ${item.validado ? '#2e7d32' : '#ef6c00'}`
                        }}
                      >
                        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr auto', gap: '1rem', alignItems: 'center' }}>
                          <div>
                            <div style={{ fontWeight: 'bold', fontSize: '0.95rem' }}>
                              {item.titulo_anuncio}
                            </div>
                            <div style={{ fontSize: '0.82rem', color: '#666', marginTop: '0.3rem' }}>
                              SKU: <strong>{item.sku_inbound || '—'}</strong>
                              {item.codigo_ml ? ` · ML: ${item.codigo_ml}` : ''}
                            </div>
                            {!item.validado && item.validacao_mensagem && (
                              <div style={{ fontSize: '0.8rem', color: '#ef6c00', marginTop: '0.3rem' }}>
                                {item.validacao_mensagem}
                              </div>
                            )}
                          </div>
                          <div style={{ textAlign: 'center' }}>
                            <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>
                              {Math.round(item.quantidade_separada)}
                            </div>
                            <div style={{ fontSize: '0.78rem', color: '#666' }}>unidades</div>
                          </div>
                          <div style={{
                            padding: '0.4rem 0.9rem',
                            backgroundColor: item.validado ? '#2e7d32' : '#ef6c00',
                            color: 'white',
                            borderRadius: '4px',
                            fontSize: '0.82rem',
                            fontWeight: 'bold',
                            whiteSpace: 'nowrap'
                          }}>
                            {item.validado ? 'Vinculado' : 'Sem vínculo'}
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
