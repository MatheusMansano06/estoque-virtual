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
  data_limite?: string | null
  data_encerramento?: string | null
  status: string
  qtd_items: number
  qtd_validados: number
  itens?: ItemInbound[]
}

type Aba = 'processando' | 'encerrado'

interface ItemRevisao {
  item_id: number
  titulo_anuncio: string
  sku_inbound?: string
  quantidade_full: number
  olist_encontrado: boolean
  olist_produto_id?: string | null
  olist_nome?: string | null
  estoque_atual?: number | null
  baixa_proposta?: number | null
  resultado?: number | null
  falta?: number | null
  tem_falta: boolean
  estoque_indisponivel?: boolean
  baixa_aplicada: number
}

interface Revisao {
  embale_id: number
  nome_embalde: string
  numero_inbound?: string
  status: string
  resumo: { total: number; encontrados: number; nao_encontrados: number; com_falta: number }
  itens: ItemRevisao[]
}

export function EmbaldesManager() {
  const [inbounds, setInbounds] = useState<Inbound[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [nomeInbound, setNomeInbound] = useState('')
  const [dataLimite, setDataLimite] = useState('')
  const [semData, setSemData] = useState(true)
  const [arquivo, setArquivo] = useState<File | null>(null)
  const [inboundSelecionado, setInboundSelecionado] = useState<Inbound | null>(null)
  const [aba, setAba] = useState<Aba>('processando')
  const [editandoData, setEditandoData] = useState<number | null>(null)
  const [novaData, setNovaData] = useState('')
  const [revisao, setRevisao] = useState<Revisao | null>(null)
  const [revisandoId, setRevisandoId] = useState<number | null>(null)
  const [carregandoRevisao, setCarregandoRevisao] = useState(false)
  const [declaracoes, setDeclaracoes] = useState<Record<number, number>>({})
  const [confirmandoBaixa, setConfirmandoBaixa] = useState(false)

  useEffect(() => {
    carregarInbounds()
  }, [])

  const carregarInbounds = async () => {
    try {
      setLoading(true)
      const resposta = await api.get('/embaldes?limit=200')
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
      if (dataLimite) formData.append('data_limite', dataLimite)

      const resposta = await api.post('/embaldes/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })

      const d = resposta.data
      setMessage(`Inbound ${d.numero_inbound || ''} processado: ${d.itens_validados}/${d.itens_processados} items vinculados`)
      setNomeInbound('')
      setDataLimite('')
      setSemData(true)
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

  const encerrarInbound = async (id: number) => {
    if (!confirm('Encerrar este inbound? Ele vai parar de descontar do estoque nas próximas notas.')) return
    try {
      await api.post(`/embaldes/${id}/encerrar`)
      await carregarInbounds()
      setMessage('Inbound encerrado')
    } catch (erro: any) {
      setMessage('Erro: ' + (erro.response?.data?.erro || String(erro)))
    }
  }

  const salvarData = async (id: number) => {
    try {
      await api.post(`/embaldes/${id}/data-limite`, { data_limite: novaData || null })
      setEditandoData(null)
      setNovaData('')
      await carregarInbounds()
      setMessage('Data limite atualizada')
    } catch (erro: any) {
      setMessage('Erro: ' + (erro.response?.data?.erro || String(erro)))
    }
  }

  const carregarRevisao = async (id: number) => {
    if (revisandoId === id) {
      // Toggle: fecha
      setRevisandoId(null)
      setRevisao(null)
      setDeclaracoes({})
      return
    }
    try {
      setCarregandoRevisao(true)
      setRevisandoId(id)
      setRevisao(null)
      setDeclaracoes({})
      const resposta = await api.get(`/embaldes/${id}/revisao`)
      setRevisao(resposta.data)
    } catch (erro: any) {
      setMessage('Erro ao revisar: ' + (erro.response?.data?.erro || String(erro)))
      setRevisandoId(null)
    } finally {
      setCarregandoRevisao(false)
    }
  }

  const confirmarBaixa = async () => {
    if (!revisao) return
    try {
      setConfirmandoBaixa(true)
      const resposta = await api.post(`/embaldes/${revisao.embale_id}/confirmar-baixa`, {
        itens: declaracoes
      })
      setMessage(`Sucesso! ${resposta.data.mensagem}`)
      // Recarrega a revisão
      await carregarRevisao(revisao.embale_id)
    } catch (erro: any) {
      setMessage('Erro ao confirmar: ' + (erro.response?.data?.erro || String(erro)))
    } finally {
      setConfirmandoBaixa(false)
    }
  }

  const formatarData = (iso?: string | null) => {
    if (!iso) return null
    return new Date(iso).toLocaleDateString('pt-BR')
  }

  // "valendo" e "processando" são ambos ativos (não encerrados)
  const ehAtivo = (status: string) => status !== 'encerrado'
  const inboundsFiltrados = inbounds.filter((i) =>
    aba === 'encerrado' ? i.status === 'encerrado' : ehAtivo(i.status)
  )
  const countProcessando = inbounds.filter((i) => ehAtivo(i.status)).length
  const countEncerrado = inbounds.filter((i) => i.status === 'encerrado').length

  return (
    <div style={{ padding: '2rem' }}>
      <h2>Inbound (Lista de Separação ML FULL)</h2>

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
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
            <div>
              <label style={{ fontWeight: 'bold', display: 'block', marginBottom: '0.5rem' }}>
                Nome do Inbound:
              </label>
              <input
                type="text"
                placeholder="Ex: Inbound Semana 1"
                value={nomeInbound}
                onChange={(e) => setNomeInbound(e.target.value)}
                disabled={loading}
                style={{ width: '100%', padding: '0.75rem', border: '1px solid #ddd', borderRadius: '4px', fontSize: '1rem' }}
              />
            </div>
            <div>
              <label style={{ fontWeight: 'bold', display: 'block', marginBottom: '0.5rem' }}>
                Data de envio do FULL:
              </label>
              <input
                type="date"
                value={dataLimite}
                onChange={(e) => setDataLimite(e.target.value)}
                disabled={loading || semData}
                style={{ width: '100%', padding: '0.75rem', border: '1px solid #ddd', borderRadius: '4px', fontSize: '1rem', backgroundColor: semData ? '#f0f0f0' : '#fff', color: semData ? '#999' : '#000' }}
              />
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '0.5rem', cursor: 'pointer', fontSize: '0.88rem', color: '#555' }}>
                <input
                  type="checkbox"
                  checked={semData}
                  onChange={(e) => { setSemData(e.target.checked); if (e.target.checked) setDataLimite('') }}
                  disabled={loading}
                />
                Sem data ainda (fica como <strong style={{ color: '#1565c0' }}>&nbsp;valendo</strong>)
              </label>
            </div>
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ fontWeight: 'bold', display: 'block', marginBottom: '0.5rem' }}>
              Arquivo PDF:
            </label>
            <div style={{ border: '2px dashed #ccc', borderRadius: '4px', padding: '1.5rem', textAlign: 'center', backgroundColor: '#fff' }}>
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
                  <div style={{ color: '#2e7d32', fontWeight: 'bold' }}>{arquivo.name}</div>
                ) : (
                  <div style={{ color: '#666' }}>Clique para selecionar um PDF</div>
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

      {/* Abas */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', borderBottom: '2px solid #eee' }}>
        <button
          onClick={() => setAba('processando')}
          style={{
            padding: '0.75rem 1.5rem',
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            fontWeight: 'bold',
            fontSize: '1rem',
            color: aba === 'processando' ? '#1976D2' : '#999',
            borderBottom: aba === 'processando' ? '3px solid #1976D2' : '3px solid transparent',
            marginBottom: '-2px'
          }}
        >
          Ativos ({countProcessando})
        </button>
        <button
          onClick={() => setAba('encerrado')}
          style={{
            padding: '0.75rem 1.5rem',
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            fontWeight: 'bold',
            fontSize: '1rem',
            color: aba === 'encerrado' ? '#1976D2' : '#999',
            borderBottom: aba === 'encerrado' ? '3px solid #1976D2' : '3px solid transparent',
            marginBottom: '-2px'
          }}
        >
          Encerrados ({countEncerrado})
        </button>
      </div>

      {/* Lista de Inbounds */}
      {inboundsFiltrados.length === 0 ? (
        <p style={{ color: '#999', textAlign: 'center', padding: '2rem' }}>
          {aba === 'processando' ? 'Nenhum inbound processando.' : 'Nenhum inbound encerrado.'}
        </p>
      ) : (
        <div style={{ display: 'grid', gap: '1rem' }}>
          {inboundsFiltrados.map((inb) => (
            <div
              key={inb.id}
              style={{
                border: '1px solid #ddd',
                borderRadius: '8px',
                padding: '1.5rem',
                backgroundColor: inb.status === 'encerrado' ? '#fafafa' : '#fff'
              }}
            >
              <div
                style={{ display: 'grid', gridTemplateColumns: '2fr 1.5fr 1fr auto', gap: '1.5rem', alignItems: 'center', cursor: 'pointer' }}
                onClick={() => carregarDetalhes(inb)}
              >
                <div>
                  <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>{inb.nome_embalde}</div>
                  <div style={{ color: '#666', fontSize: '0.85rem', marginTop: '0.4rem' }}>
                    {inb.numero_inbound ? `Frete #${inb.numero_inbound}` : 'Sem número'}
                    {inb.total_unidades ? ` · ${Math.round(inb.total_unidades)} un` : ''}
                  </div>
                </div>

                {/* Data limite */}
                <div style={{ fontSize: '0.85rem' }} onClick={(e) => e.stopPropagation()}>
                  {editandoData === inb.id ? (
                    <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', flexWrap: 'wrap' }}>
                      <input
                        type="date"
                        value={novaData}
                        onChange={(e) => setNovaData(e.target.value)}
                        style={{ padding: '0.4rem', border: '1px solid #ddd', borderRadius: '4px' }}
                      />
                      <button onClick={() => salvarData(inb.id)} style={{ padding: '0.4rem 0.7rem', background: '#1976D2', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>OK</button>
                      <button onClick={() => { setNovaData(''); salvarData(inb.id) }} title="Volta para VALENDO (sem data)" style={{ padding: '0.4rem 0.7rem', background: '#fff', color: '#1565c0', border: '1px solid #1565c0', borderRadius: '4px', cursor: 'pointer', fontSize: '0.78rem' }}>Sem data</button>
                      <button onClick={() => { setEditandoData(null); setNovaData('') }} style={{ padding: '0.4rem 0.7rem', background: '#eee', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>x</button>
                    </div>
                  ) : (
                    <div>
                      <span style={{ color: '#666' }}>Envio FULL: </span>
                      {inb.status === 'valendo' ? (
                        <span style={{ padding: '0.15rem 0.5rem', background: '#e3f2fd', color: '#1565c0', borderRadius: '4px', fontWeight: 'bold', fontSize: '0.8rem' }}>
                          VALENDO (sem data)
                        </span>
                      ) : (
                        <strong>{formatarData(inb.data_limite) || 'sem data'}</strong>
                      )}
                      {ehAtivo(inb.status) && (
                        <button
                          onClick={() => { setEditandoData(inb.id); setNovaData(inb.data_limite?.slice(0, 10) || '') }}
                          style={{ marginLeft: '0.5rem', padding: '0.2rem 0.5rem', background: 'none', border: '1px solid #ddd', borderRadius: '4px', cursor: 'pointer', fontSize: '0.78rem' }}
                        >
                          editar
                        </button>
                      )}
                      {inb.status === 'encerrado' && inb.data_encerramento && (
                        <div style={{ color: '#999', marginTop: '0.2rem' }}>
                          Encerrado em {formatarData(inb.data_encerramento)}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Vinculados */}
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: inb.qtd_validados === inb.qtd_items ? '#2e7d32' : '#ef6c00' }}>
                    {inb.qtd_validados}/{inb.qtd_items}
                  </div>
                  <div style={{ fontSize: '0.78rem', color: '#666' }}>vinculados</div>
                </div>

                {/* Ação */}
                <div onClick={(e) => e.stopPropagation()} style={{ display: 'flex', gap: '0.5rem', flexDirection: 'column' }}>
                  <button
                    onClick={() => carregarRevisao(inb.id)}
                    style={{ padding: '0.5rem 1rem', background: revisandoId === inb.id ? '#1976D2' : '#fff', color: revisandoId === inb.id ? '#fff' : '#1976D2', border: '1px solid #1976D2', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold', fontSize: '0.85rem', whiteSpace: 'nowrap' }}
                  >
                    {revisandoId === inb.id ? 'Fechar revisão' : 'Revisar Olist'}
                  </button>
                  {ehAtivo(inb.status) ? (
                    <button
                      onClick={() => encerrarInbound(inb.id)}
                      style={{ padding: '0.5rem 1rem', background: '#fff', color: '#c62828', border: '1px solid #c62828', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold', fontSize: '0.85rem', whiteSpace: 'nowrap' }}
                    >
                      Encerrar
                    </button>
                  ) : (
                    <span style={{ padding: '0.4rem 0.9rem', background: '#9e9e9e', color: '#fff', borderRadius: '4px', fontSize: '0.82rem', fontWeight: 'bold', textAlign: 'center' }}>
                      Encerrado
                    </span>
                  )}
                </div>
              </div>

              {/* Revisão de baixa na Olist */}
              {revisandoId === inb.id && (
                <div style={{ marginTop: '1.5rem', paddingTop: '1.5rem', borderTop: '2px solid #1976D2' }}>
                  {carregandoRevisao ? (
                    <div style={{ textAlign: 'center', padding: '2rem', color: '#1976D2', fontWeight: 'bold' }}>
                      Consultando estoque na Olist, produto por produto... aguarde.
                    </div>
                  ) : revisao ? (
                    <div>
                      {/* Resumo */}
                      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                        <div style={{ padding: '0.6rem 1rem', background: '#e3f2fd', borderRadius: '4px', fontSize: '0.85rem' }}>
                          Total: <strong>{revisao.resumo.total}</strong>
                        </div>
                        <div style={{ padding: '0.6rem 1rem', background: '#e8f5e9', borderRadius: '4px', fontSize: '0.85rem' }}>
                          Achados na Olist: <strong>{revisao.resumo.encontrados}</strong>
                        </div>
                        <div style={{ padding: '0.6rem 1rem', background: '#fff3e0', borderRadius: '4px', fontSize: '0.85rem' }}>
                          Não achados: <strong>{revisao.resumo.nao_encontrados}</strong>
                        </div>
                        <div style={{ padding: '0.6rem 1rem', background: '#ffebee', borderRadius: '4px', fontSize: '0.85rem' }}>
                          Com falta: <strong>{revisao.resumo.com_falta}</strong>
                        </div>
                      </div>

                      <div style={{ fontSize: '0.8rem', color: '#666', marginBottom: '0.75rem', fontStyle: 'italic' }}>
                        Revisão (somente leitura) — selecione quantas unidades baixar em cada item.
                      </div>

                      {/* Tabela */}
                      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1.2fr 1fr', gap: '0.5rem', padding: '0.6rem 0.8rem', background: '#f5f5f5', borderRadius: '4px 4px 0 0', fontSize: '0.75rem', fontWeight: 'bold', color: '#666', textTransform: 'uppercase' }}>
                        <div>Produto / SKU</div>
                        <div style={{ textAlign: 'center' }}>Estoque Olist</div>
                        <div style={{ textAlign: 'center' }}>Vai pro FULL</div>
                        <div style={{ textAlign: 'center' }}>Resultado</div>
                        <div style={{ textAlign: 'center' }}>Situação</div>
                        <div style={{ textAlign: 'center' }}>Declarar</div>
                      </div>
                      <div style={{ maxHeight: '500px', overflowY: 'auto', border: '1px solid #eee', borderTop: 'none' }}>
                        {revisao.itens.map((it) => {
                          const naoAchado = !it.olist_encontrado
                          const semEstoque = it.olist_encontrado && it.estoque_indisponivel
                          const bg = naoAchado ? '#fff8f0' : it.tem_falta ? '#ffebee' : '#fff'
                          return (
                            <div
                              key={it.item_id}
                              style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1.2fr 1fr', gap: '0.5rem', padding: '0.7rem 0.8rem', background: bg, borderBottom: '1px solid #f0f0f0', fontSize: '0.85rem', alignItems: 'center' }}
                            >
                              <div>
                                <div style={{ fontWeight: 600 }}>{it.titulo_anuncio}</div>
                                <div style={{ fontSize: '0.78rem', color: '#666' }}>SKU: {it.sku_inbound || '—'}</div>
                              </div>
                              <div style={{ textAlign: 'center', fontWeight: 'bold' }}>
                                {naoAchado ? '—' : semEstoque ? '?' : it.estoque_atual}
                              </div>
                              <div style={{ textAlign: 'center' }}>{Math.round(it.quantidade_full)}</div>
                              <div style={{ textAlign: 'center', fontWeight: 'bold', color: '#2e7d32' }}>
                                {naoAchado || semEstoque ? '—' : it.tem_falta ? '—' : it.resultado}
                              </div>
                              <div style={{ textAlign: 'center' }}>
                                {naoAchado ? (
                                  <span style={{ color: '#ef6c00', fontWeight: 'bold', fontSize: '0.8rem' }}>Não achado na Olist</span>
                                ) : semEstoque ? (
                                  <span style={{ color: '#999', fontSize: '0.8rem' }}>Estoque indisponível</span>
                                ) : it.tem_falta ? (
                                  <span style={{ color: '#c62828', fontWeight: 'bold', fontSize: '0.8rem' }}>Falta {Math.round(it.falta || 0)}</span>
                                ) : (
                                  <span style={{ color: '#2e7d32', fontWeight: 'bold', fontSize: '0.8rem' }}>OK</span>
                                )}
                              </div>
                              <div style={{ textAlign: 'center' }}>
                                {it.tem_falta ? (
                                  <input
                                    type="number"
                                    min="0"
                                    max={it.estoque_atual || 0}
                                    value={declaracoes[it.item_id] ?? Math.round(it.estoque_atual || 0)}
                                    onChange={(e) => setDeclaracoes({ ...declaracoes, [it.item_id]: parseFloat(e.target.value) || 0 })}
                                    style={{ width: '60px', padding: '0.3rem', borderRadius: '3px', border: '1px solid #ddd', textAlign: 'center', fontSize: '0.85rem' }}
                                  />
                                ) : (
                                  <span style={{ color: '#999', fontSize: '0.8rem' }}>—</span>
                                )}
                              </div>
                            </div>
                          )
                        })}
                      </div>

                      {/* Botão Confirmar Baixa */}
                      <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
                        <button
                          onClick={confirmarBaixa}
                          disabled={confirmandoBaixa}
                          style={{ padding: '0.6rem 1.2rem', background: '#1976D2', color: '#fff', border: 'none', borderRadius: '4px', cursor: confirmandoBaixa ? 'not-allowed' : 'pointer', fontWeight: 'bold', opacity: confirmandoBaixa ? 0.7 : 1 }}
                        >
                          {confirmandoBaixa ? 'Processando...' : 'Confirmar Baixa na Olist'}
                        </button>
                        <span style={{ fontSize: '0.75rem', color: '#666', alignSelf: 'center', fontStyle: 'italic' }}>
                          Isso escreverá na Olist — não há volta!
                        </span>
                      </div>
                    </div>
                  ) : null}
                </div>
              )}

              {/* Detalhes expandidos */}
              {inboundSelecionado?.id === inb.id && (
                <div style={{ marginTop: '1.5rem', paddingTop: '1.5rem', borderTop: '1px solid #eee' }}>
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
                            <div style={{ fontWeight: 'bold', fontSize: '0.95rem' }}>{item.titulo_anuncio}</div>
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
                            <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>{Math.round(item.quantidade_separada)}</div>
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
