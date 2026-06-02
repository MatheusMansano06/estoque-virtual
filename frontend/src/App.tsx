import { useState, useEffect, useRef } from 'react'
import './App.css'
import { ModalDetalhes } from './ModalDetalhes'
import { ModalDetalhesNota } from './ModalDetalhesNota'
import { ModalDetalhesNotaFiscal } from './ModalDetalhesNotaFiscal'

interface NotaFiscal {
  id: number
  numero_nf: string
  serie: string
  fornecedor: string
  status: string
  data_emissao?: string
  data_upload?: string
  arquivo_original?: string
  itens?: ItemNota[]
}

interface ItemNota {
  id: number
  codigo_produto: string
  descricao: string
  quantidade_nf: number
  quantidade_confirmada?: number
  preco_unitario: number
  status: string
  divergencia?: string
  olist_produto_id?: string | null
  olist_sku?: string | null
  estoque_olist_atualizado_em?: string | null
}

interface ProdutoEstoque {
  id_item: number
  descricao: string
  codigo_produto: string
  quantidade_total: number
  quantidade_confirmada: number
  preco_unitario: number
  notas_fiscais: Array<{
    numero_nf: string
    serie: string
    fornecedor: string
    quantidade: number
  }>
}

type Pagina = 'inicial' | 'conferencia' | 'produtos_nota' | 'relacionamento_produto'

interface Divergencia {
  item_id: number
  numero_nf: string
  serie: string
  fornecedor: string
  produto: string
  codigo: string
  tipo_divergencia: string
  quantidade_nf: number
  quantidade_confirmada: number
  data_registro: string
}

function App() {
  // Estados de navegação
  const [pagina, setPagina] = useState<Pagina>('inicial')
  const [notaSelecionada, setNotaSelecionada] = useState<NotaFiscal | null>(null)
  const [produtosNota, setProdutosNota] = useState<ItemNota[]>([])

  // Estados da página inicial
  const [file, setFile] = useState<File | null>(null)
  const [notas, setNotas] = useState<NotaFiscal[]>([])
  const [estoque, setEstoque] = useState<ProdutoEstoque[]>([])
  const [divergencias, setDivergencias] = useState<Divergencia[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [produtoSelecionado, setProdutoSelecionado] = useState<ProdutoEstoque | null>(null)
  const [mostrarTodosEstoque, setMostrarTodosEstoque] = useState(false)
  const [modalDetalhesNFAberto, setModalDetalhesNFAberto] = useState(false)
  const [modalAdicionarProdutoAberto, setModalAdicionarProdutoAberto] = useState(false)
  const [novoProduto, setNovoProduto] = useState({
    codigo: '',
    descricao: '',
    quantidade: 1,
    preco: 0
  })
  const [produtoOlistSKU, setProdutoOlistSKU] = useState('')
  const [sugestoesSKU, setSugestoesSKU] = useState<Array<{sku: string, nome: string, preco: number}>>([])
  const [produtoOlistSelecionado, setProdutoOlistSelecionado] = useState({
    id: '',
    sku: '',
    nome: '',
    preco: 0,
    estoque: 0,
    estoque_saldo: 0,
    estoque_reservado: 0
  })
  const [produtoConferindoAtualmente, setProdutoConferindoAtualmente] = useState<ItemNota | null>(null)
  // Memória de vínculos (de-para fornecedor -> Olist)
  const [sugestaoVinculo, setSugestaoVinculo] = useState<any>(null)
  const [sugestaoDispensada, setSugestaoDispensada] = useState(false)
  const [modalVinculosAberto, setModalVinculosAberto] = useState(false)
  const [listaVinculos, setListaVinculos] = useState<any[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Carregar notas ao iniciar
  useEffect(() => {
    loadNotas()
    loadEstoque()
    loadDivergencias()
  }, [])

  // Ao entrar na tela de vínculo, busca se esse produto já foi vinculado antes
  useEffect(() => {
    if (pagina === 'relacionamento_produto' && produtoSelecionado) {
      setSugestaoVinculo(null)
      setSugestaoDispensada(false)
      const codigo = (produtoSelecionado as any).codigo_produto || ''
      const descricao = (produtoSelecionado as any).descricao || ''
      fetch(`http://localhost:8000/api/olist/sugestao-vinculo?codigo=${encodeURIComponent(codigo)}&descricao=${encodeURIComponent(descricao)}`)
        .then((r) => r.json())
        .then((d) => { if (d.encontrado) setSugestaoVinculo(d.vinculo) })
        .catch(() => {})
    }
  }, [pagina, produtoSelecionado])

  // Usa a sugestão: busca dados frescos (estoque) do anúncio e seleciona
  const usarSugestao = async () => {
    if (!sugestaoVinculo) return
    const termo = sugestaoVinculo.olist_sku || sugestaoVinculo.nf_codigo || ''
    try {
      const res = await fetch(`http://localhost:8000/api/olist/produtos?q=${encodeURIComponent(termo)}`)
      const data = await res.json()
      const lista = data.produtos || []
      const prod = lista.find((p: any) => String(p.id) === String(sugestaoVinculo.olist_produto_id)) || lista[0]
      if (prod) {
        handleSelecionarSKU(prod)
      } else {
        // fallback: usa os dados salvos (sem estoque ao vivo)
        handleSelecionarSKU({
          id: sugestaoVinculo.olist_produto_id,
          sku: sugestaoVinculo.olist_sku,
          nome: sugestaoVinculo.olist_nome,
          preco: sugestaoVinculo.olist_preco,
          estoque_atual: 0,
          estoque_saldo: 0,
        })
      }
    } catch {
      // fallback silencioso
    } finally {
      setSugestaoVinculo(null)
    }
  }

  const loadVinculos = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/olist/vinculos')
      const data = await res.json()
      setListaVinculos(data.vinculos || [])
    } catch (err) {
      console.error('Erro ao carregar vínculos:', err)
    }
  }

  const abrirModalVinculos = () => {
    loadVinculos()
    setModalVinculosAberto(true)
  }

  const deletarVinculo = async (id: number) => {
    if (!window.confirm('Remover este vínculo salvo? Ele não será mais sugerido automaticamente.')) return
    try {
      await fetch('http://localhost:8000/api/olist/vinculos/deletar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      })
      loadVinculos()
    } catch (err) {
      alert('Erro ao remover vínculo')
    }
  }

  const loadNotas = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/notas-fiscais')
      const data = await res.json()
      setNotas(data.items || [])
    } catch (err) {
      console.error('Erro ao carregar notas:', err)
    }
  }

  const loadEstoque = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/estoque-virtual')
      const data = await res.json()
      setEstoque(data.produtos || [])
    } catch (err) {
      console.error('Erro ao carregar estoque:', err)
    }
  }

  const loadDivergencias = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/divergencias')
      const data = await res.json()
      setDivergencias(data.divergencias || [])
    } catch (err) {
      console.error('Erro ao carregar divergências:', err)
    }
  }

  const irParaProximaEtapa = (novaPagina: Pagina) => {
    setPagina(novaPagina)
    setModalOpen(false)
    loadNotas()
    loadDivergencias()
  }

  // Vai para a página de vínculo Olist usando a quantidade que REALMENTE chegou
  const irParaOlistSubirEstoque = (qtdConfirmada: number) => {
    setProdutoSelecionado((prev) =>
      prev ? ({ ...prev, quantidade_nf: qtdConfirmada } as any) : prev
    )
    // Limpa seleção anterior da Olist
    setProdutoOlistSelecionado({
      id: '', sku: '', nome: '', preco: 0,
      estoque: 0, estoque_saldo: 0, estoque_reservado: 0
    })
    setProdutoOlistSKU('')
    setSugestoesSKU([])
    setModalOpen(false)
    setPagina('relacionamento_produto')
    loadNotas()
    loadDivergencias()
  }

  // Calcula progresso de estoque subido na Olist (0-100%)
  const calcularProgresso = (itens?: ItemNota[]) => {
    const lista = itens || []
    const total = lista.length
    if (total === 0) return { conferidos: 0, total: 0, percentual: 0 }
    const conferidos = lista.filter(
      (i) => !!i.estoque_olist_atualizado_em
    ).length
    return { conferidos, total, percentual: Math.round((conferidos / total) * 100) }
  }

  // Componente de barra de progresso reutilizável
  const BarraProgresso = ({ itens, compacto = false }: { itens?: ItemNota[], compacto?: boolean }) => {
    const { conferidos, total, percentual } = calcularProgresso(itens)
    const cor = percentual === 100 ? '#4caf50' : percentual > 0 ? '#007acc' : '#bdbdbd'
    return (
      <div style={{ marginTop: compacto ? '0.5rem' : '0' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
          <span style={{ fontSize: compacto ? '0.75rem' : '0.85rem', color: '#666', fontWeight: 600 }}>
            Subidos na Olist: {conferidos}/{total}
          </span>
          <span style={{ fontSize: compacto ? '0.75rem' : '0.85rem', color: cor, fontWeight: 700 }}>
            {percentual}%
          </span>
        </div>
        <div style={{ background: '#e0e0e0', borderRadius: '999px', height: compacto ? '6px' : '10px', overflow: 'hidden' }}>
          <div style={{
            width: `${percentual}%`,
            height: '100%',
            background: cor,
            borderRadius: '999px',
            transition: 'width 0.4s ease'
          }} />
        </div>
      </div>
    )
  }

  // Dados mock de produtos Olist (futuramente virá de uma API real)
  const produtosOlistMock = [
    { sku: '001', nome: 'Produto XYZ - Azul', preco: 49.90, estoque: 15 },
    { sku: '002', nome: 'Produto XYZ - Vermelho', preco: 49.90, estoque: 8 },
    { sku: '003', nome: 'Produto ABC - P', preco: 35.00, estoque: 12 },
    { sku: '004', nome: 'Produto ABC - M', preco: 35.00, estoque: 20 },
    { sku: '005', nome: 'Produto ABC - G', preco: 35.00, estoque: 5 },
    { sku: '006', nome: 'Camiseta Premium - Branco', preco: 79.90, estoque: 30 },
    { sku: '007', nome: 'Camiseta Premium - Preto', preco: 79.90, estoque: 25 },
    { sku: '008', nome: 'Bermuda Casual - Azul', preco: 89.90, estoque: 10 },
  ]

  const handleBuscarSKU = async (busca: string) => {
    setProdutoOlistSKU(busca)

    if (busca.length < 2) {
      setSugestoesSKU([])
      return
    }

    try {
      // Buscar produtos da API da Olist
      const response = await fetch(`http://localhost:8000/api/olist/produtos?q=${encodeURIComponent(busca)}`)

      if (!response.ok) {
        const errorData = await response.json()
        if (response.status === 503) {
          // Chave não configurada - mostrar aviso
          setSugestoesSKU([])
          setMessage({
            type: 'warning',
            text: '⚠️ Configure sua chave de API da Olist no arquivo .env para usar a busca em tempo real. Adicione: OLIST_API_KEY=sua_chave_aqui'
          })
          return
        }
      }

      const data = await response.json()

      if (data.produtos && Array.isArray(data.produtos)) {
        setSugestoesSKU(data.produtos)
      } else {
        setSugestoesSKU([])
      }
    } catch (err) {
      console.error('Erro ao buscar produtos Olist:', err)
      setSugestoesSKU([])
      setMessage({
        type: 'error',
        text: '❌ Erro ao buscar produtos da Olist. Verifique se a API está disponível.'
      })
    }
  }

  const handleSelecionarSKU = (produto: any) => {
    setProdutoOlistSelecionado({
      id: produto.id || '',
      sku: produto.sku || '',
      nome: produto.nome || '',
      preco: parseFloat(produto.preco) || 0,
      estoque: parseInt(produto.estoque_atual ?? produto.estoque) || 0,
      estoque_saldo: parseInt(produto.estoque_saldo ?? produto.estoque_atual) || 0,
      estoque_reservado: parseInt(produto.estoque_reservado) || 0
    })
    setProdutoOlistSKU('')
    setSugestoesSKU([])
  }

  const handleVincular = async () => {
    if (!produtoOlistSelecionado.sku || !produtoSelecionado) {
      alert('❌ Selecione um anúncio da Olist primeiro!')
      return
    }

    // O item pode vir com 'id' (divergência) ou 'id_item' (conferência)
    const itemId = (produtoSelecionado as any).id ?? (produtoSelecionado as any).id_item
    if (!itemId) {
      alert('❌ Erro: item sem identificador. Volte e selecione o produto novamente.')
      return
    }

    const qtdNF = Math.round(produtoSelecionado.quantidade_nf)
    const saldoAtual = produtoOlistSelecionado.estoque_saldo
    const novoSaldo = saldoAtual + qtdNF

    const confirmar = window.confirm(
      `Confirmar atualização de estoque na Olist?\n\n` +
      `Produto: ${produtoOlistSelecionado.nome}\n` +
      `SKU: ${produtoOlistSelecionado.sku}\n\n` +
      `Estoque atual na Olist: ${saldoAtual} un\n` +
      `+ Quantidade da NF: ${qtdNF} un\n` +
      `= Novo estoque total: ${novoSaldo} un\n\n` +
      `Deseja continuar?`
    )
    if (!confirmar) return

    try {
      // 1. Vincular produto NF -> anúncio Olist
      const resVinc = await fetch('http://localhost:8000/api/olist/vincular-produto', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          item_id: itemId,
          olist_produto_id: produtoOlistSelecionado.id,
          olist_sku: produtoOlistSelecionado.sku,
          olist_nome: produtoOlistSelecionado.nome,
          olist_preco: produtoOlistSelecionado.preco
        })
      })
      if (!resVinc.ok) {
        const err = await resVinc.json()
        alert('❌ Erro ao vincular: ' + (err.error || 'desconhecido'))
        return
      }

      // 2. Atualizar estoque na Olist (ENTRADA da quantidade da NF)
      const resEst = await fetch('http://localhost:8000/api/olist/atualizar-estoque', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          item_id: itemId,
          quantidade: qtdNF,
          tipo: 'E'
        })
      })

      const dataEst = await resEst.json()
      if (resEst.ok && dataEst.sucesso) {
        alert(
          `✅ Sucesso!\n\n` +
          `Produto vinculado e estoque atualizado na Olist.\n` +
          `Novo estoque: ${novoSaldo} unidades`
        )
        // Recarregar dados para a barra de progresso refletir a subida
        await loadNotas()
        await loadDivergencias()
        voltarParaInicial()
      } else {
        alert('⚠️ Produto vinculado, mas falha ao atualizar estoque: ' + (dataEst.error || 'desconhecido'))
      }
    } catch (err) {
      alert('❌ Erro: ' + err)
    }
  }

  const handleAdicionarProduto = async () => {
    if (!novoProduto.codigo || !novoProduto.descricao) {
      alert('❌ Preencha código e descrição!')
      return
    }

    try {
      const res = await fetch('http://localhost:8000/api/produtos-manuais', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nf_id: notaSelecionada?.id,
          codigo_recebido: novoProduto.codigo,
          descricao_recebida: novoProduto.descricao,
          quantidade: novoProduto.quantidade,
          preco: novoProduto.preco
        })
      })

      if (res.ok) {
        alert('✅ Produto adicionado ao estoque!')
        setModalAdicionarProdutoAberto(false)
        setNovoProduto({ codigo: '', descricao: '', quantidade: 1, preco: 0 })
        // Recarregar notas para atualizar a lista
        if (notaSelecionada) {
          const resNota = await fetch(`http://localhost:8000/api/notas-fiscais/${notaSelecionada.id}`)
          const dataNota = await resNota.json()
          setProdutosNota(dataNota.itens || [])
        }
      } else {
        alert('❌ Erro ao adicionar produto')
      }
    } catch (err) {
      alert('❌ Erro: ' + err)
    }
  }

  const abrirNotaSelecionada = async (notaId: number) => {
    try {
      const res = await fetch(`http://localhost:8000/api/notas-fiscais/${notaId}`)
      const data: NotaFiscal = await res.json()
      setNotaSelecionada(data)
      setPagina('inicial') // Mantém na inicial mas mostra a nota selecionada
    } catch (err) {
      console.error('Erro ao buscar nota:', err)
    }
  }

  const irParaConferenciaProdutos = async () => {
    if (!notaSelecionada) return
    try {
      // Buscar dados frescos da nota para refletir conferências já feitas
      const res = await fetch(`http://localhost:8000/api/notas-fiscais/${notaSelecionada.id}`)
      const data: NotaFiscal = await res.json()
      setNotaSelecionada(data)
      setProdutosNota(data.itens || [])
    } catch (err) {
      setProdutosNota(notaSelecionada.itens || [])
    }
    setPagina('produtos_nota')
  }

  const abrirConferencia = async (notaId: number) => {
    try {
      const res = await fetch(`http://localhost:8000/api/notas-fiscais/${notaId}`)
      const data: NotaFiscal = await res.json()
      setNotaSelecionada(data)
      setPagina('conferencia')
      setMostrarTodosEstoque(false)
    } catch (err) {
      console.error('Erro ao buscar nota:', err)
    }
  }

  const voltarParaInicial = () => {
    setPagina('inicial')
    setNotaSelecionada(null)
  }

  const enviarWhatsApp = (produto: string, quantidadeEsperada: number, quantidadeRecebida: number, tipo: 'a_mais' | 'a_menos' | 'nao_veio') => {
    let mensagem = ''
    const telefone = '5519978149245' // WhatsApp sem formatação

    if (tipo === 'a_mais') {
      mensagem = `Produto ${produto}: Chegou com quantidade MAIOR. Esperado: ${quantidadeEsperada} | Recebido: ${quantidadeRecebida}`
    } else if (tipo === 'a_menos') {
      mensagem = `Produto ${produto}: Chegou com quantidade MENOR. Esperado: ${quantidadeEsperada} | Recebido: ${quantidadeRecebida}`
    } else {
      mensagem = `Produto ${produto}: NÃO CHEGOU. Esperado: ${quantidadeEsperada} | Recebido: 0`
    }

    const urlWhatsApp = `https://wa.me/${telefone}?text=${encodeURIComponent(mensagem)}`
    window.open(urlWhatsApp, '_blank')
  }

  const abrirDetalhes = (produto: ProdutoEstoque) => {
    setProdutoSelecionado(produto)
    setModalOpen(true)
  }

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) {
      setMessage('Selecione um arquivo!')
      return
    }

    setLoading(true)
    setMessage('')

    try {
      const formData = new FormData()
      formData.append('file', file)

      const res = await fetch('http://localhost:8000/api/upload-nfe', {
        method: 'POST',
        body: formData,
      })

      const data = await res.json()

      if (res.ok) {
        setMessage(`NF #${data.numero_nf} - ${data.itens_encontrados} itens importados com sucesso`)
        setFile(null)
        loadNotas()
        loadEstoque()
      } else {
        setMessage(`Erro: ${data.error || 'Erro desconhecido'}`)
      }
    } catch (err) {
      setMessage(`Erro: ${err}`)
    } finally {
      setLoading(false)
    }
  }

  // ===== PÁGINA INICIAL =====
  if (pagina === 'inicial') {
    return (
      <div className="app">
        <header className="header">
          <div className="container">
            <h1>ESTOQUE VIRTUAL</h1>
            <p>Sistema de Inventário via Nota Fiscal Eletrônica</p>
          </div>
        </header>

        <main className="container main-content">
          {message && (
            <div className={`message ${message.includes('sucesso') ? 'success' : 'error'}`}>
              {message}
            </div>
          )}

          <div className="dashboard-grid">
            {/* UPLOAD CARD */}
            <div className="card">
              <h2>Upload de Nota Fiscal</h2>
              <div className="card-body">
              <form onSubmit={handleUpload}>
                <div
                  className="upload-section"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <div className="upload-icon">↑</div>
                  <h3>Selecione um arquivo</h3>
                  <p>XML ou PDF de NF-e</p>
                  <p style={{ fontSize: '0.85rem', color: '#6b7280' }}>
                    {file ? file.name : 'Clique ou arraste um arquivo'}
                  </p>
                </div>

                <div className="file-input-wrapper">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".xml,.pdf"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                    disabled={loading}
                    className="file-input"
                  />
                </div>

                <button
                  type="submit"
                  disabled={!file || loading}
                  className="upload-button"
                >
                  {loading ? 'Processando...' : 'Enviar NF-e'}
                </button>
              </form>
              </div>
            </div>

            {/* COLUNA 2: NOTAS FISCAIS PROCESSADAS */}
            <div className="card">
              <h2>Notas Fiscais Processadas</h2>
              <div className="card-body">
              {notas.length === 0 ? (
                <p style={{ color: '#666', textAlign: 'center', padding: '2rem' }}>
                  Nenhuma nota processada
                </p>
              ) : (
                <div className="notas-list">
                  {notas.map((nota) => (
                    <div
                      key={nota.id}
                      className="nota-item"
                      onClick={() => abrirNotaSelecionada(nota.id)}
                      style={{
                        cursor: 'pointer',
                        backgroundColor: notaSelecionada?.id === nota.id ? '#e3f2fd' : '#f9f9f9',
                        borderLeftColor: notaSelecionada?.id === nota.id ? '#0d47a1' : '#007acc',
                      }}
                    >
                      <div className="nota-number">NF #{nota.numero_nf}</div>
                      <div className="nota-info">
                        Fornecedor: <strong>{nota.fornecedor}</strong>
                      </div>
                      <div className="nota-info">
                        Série: <strong>{nota.serie}</strong>
                      </div>
                      <div className="nota-status">{nota.status.toUpperCase()}</div>
                      <BarraProgresso itens={nota.itens} compacto />
                    </div>
                  ))}
                </div>
              )}
              </div>
            </div>

            {/* COLUNA 3: ESTOQUE VIRTUAL - PRÉVIA */}
            <div className="card">
              <h2>Estoque Virtual - Prévia</h2>
              <div className="card-body">
              {!notaSelecionada ? (
                <p style={{ color: '#999', textAlign: 'center', padding: '2rem', fontSize: '0.95rem' }}>
                  Selecione uma nota fiscal para ver a prévia
                </p>
              ) : (
                <div>
                  {/* Informações da Nota */}
                  <div style={{ background: '#f9f9f9', padding: '1.5rem', borderRadius: '6px', marginBottom: '1.5rem' }}>
                    <h3 style={{ color: '#1a1a1a', marginBottom: '1rem', fontSize: '1.1rem', fontWeight: '600' }}>
                      {notaSelecionada.fornecedor}
                    </h3>

                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                      <span style={{ color: '#666', fontSize: '0.9rem' }}>NF:</span>
                      <span style={{ color: '#1a1a1a', fontWeight: '600' }}>{notaSelecionada.numero_nf}</span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                      <span style={{ color: '#666', fontSize: '0.9rem' }}>Série:</span>
                      <span style={{ color: '#1a1a1a', fontWeight: '600' }}>{notaSelecionada.serie}</span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                      <span style={{ color: '#666', fontSize: '0.9rem' }}>Itens:</span>
                      <span style={{ color: '#1a1a1a', fontWeight: '600' }}>{notaSelecionada.itens?.length || 0}</span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: '0.75rem', borderTop: '1px solid #e0e0e0' }}>
                      <span style={{ color: '#666', fontSize: '0.9rem', fontWeight: '600' }}>Valor Total:</span>
                      <span style={{ color: '#007acc', fontWeight: '700', fontSize: '1rem' }}>
                        R$ {(notaSelecionada.itens?.reduce((sum, item) => sum + (item.quantidade_nf * item.preco_unitario), 0) || 0).toFixed(2)}
                      </span>
                    </div>
                  </div>

                  {/* Lista de Produtos */}
                  <div style={{ background: '#f5f5f5', padding: '1rem', borderRadius: '6px', marginBottom: '1.5rem', maxHeight: '200px', overflowY: 'auto' }}>
                    <p style={{ color: '#999', fontSize: '0.8rem', fontWeight: '700', marginBottom: '0.75rem', textTransform: 'uppercase' }}>
                      Produtos ({notaSelecionada.itens?.length || 0})
                    </p>
                    {notaSelecionada.itens && notaSelecionada.itens.length > 0 ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        {notaSelecionada.itens.map((item, idx) => (
                          <div key={idx} style={{ background: '#ffffff', padding: '0.75rem', borderRadius: '4px', fontSize: '0.85rem' }}>
                            <div style={{ color: '#1a1a1a', fontWeight: '600', marginBottom: '0.25rem' }}>
                              {item.descricao}
                            </div>
                            <div style={{ color: '#666', fontSize: '0.8rem' }}>
                              {item.quantidade_nf.toFixed(0)} un × R$ {item.preco_unitario.toFixed(2)}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p style={{ color: '#999', fontSize: '0.85rem' }}>Nenhum produto</p>
                    )}
                  </div>

                  {/* Botões */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    <button
                      onClick={irParaConferenciaProdutos}
                      style={{
                        padding: '0.85rem',
                        background: '#007acc',
                        color: 'white',
                        border: 'none',
                        borderRadius: '4px',
                        fontWeight: '600',
                        cursor: 'pointer',
                        fontSize: '0.9rem',
                        transition: 'all 0.3s'
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = '#005a96')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = '#007acc')}
                    >
                      Ir para Conferência
                    </button>

                    <button
                      onClick={() => setModalDetalhesNFAberto(true)}
                      style={{
                        padding: '0.85rem',
                        background: '#f0f0f0',
                        color: '#1a1a1a',
                        border: '1px solid #e0e0e0',
                        borderRadius: '4px',
                        fontWeight: '600',
                        cursor: 'pointer',
                        fontSize: '0.9rem',
                        transition: 'all 0.3s'
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = '#e8e8e8')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = '#f0f0f0')}
                    >
                      Ver Detalhes
                    </button>
                  </div>
                </div>
              )}
              </div>
            </div>

            {/* COLUNA 4: DIVERGÊNCIAS REGISTRADAS */}
            <div className="card">
              <h2>Divergências Registradas</h2>
              <div className="card-body">
              {divergencias.length === 0 ? (
                <p style={{ color: '#999', textAlign: 'center', padding: '2rem', fontSize: '0.95rem' }}>
                  Nenhuma divergência registrada
                </p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {divergencias.map((div) => {
                    let bgColor = '#e3f2fd'
                    let borderColor = '#2196F3'
                    let textColor = '#1565c0'

                    if (div.tipo_divergencia === 'a_menos') {
                      bgColor = '#ffebee'
                      borderColor = '#f44336'
                      textColor = '#c62828'
                    } else if (div.tipo_divergencia === 'a_mais') {
                      bgColor = '#fff3e0'
                      borderColor = '#ff9800'
                      textColor = '#e65100'
                    } else if (div.tipo_divergencia === 'nao_veio') {
                      bgColor = '#f3e5f5'
                      borderColor = '#9c27b0'
                      textColor = '#6a1b9a'
                    } else if (div.tipo_divergencia === 'produto_substituido') {
                      bgColor = '#f0f4c3'
                      borderColor = '#cddc39'
                      textColor = '#827717'
                    }

                    const handleResolver = async () => {
                      const res = await fetch('http://localhost:8000/api/resolver-divergencia', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ item_id: div.item_id })
                      })
                      if (res.ok) {
                        alert('✅ Divergência marcada como resolvida')
                        loadDivergencias()
                      } else {
                        alert('❌ Erro ao resolver')
                      }
                    }

                    const handleDeletar = async () => {
                      if (!window.confirm('Tem certeza que deseja deletar esta divergência?')) return
                      const res = await fetch('http://localhost:8000/api/deletar-divergencia', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ item_id: div.item_id })
                      })
                      if (res.ok) {
                        alert('✅ Divergência deletada')
                        loadDivergencias()
                      } else {
                        alert('❌ Erro ao deletar')
                      }
                    }

                    return (
                      <div
                        key={div.item_id}
                        style={{
                          background: bgColor,
                          border: `2px solid ${borderColor}`,
                          padding: '1rem',
                          borderRadius: '4px',
                          fontSize: '0.85rem'
                        }}
                      >
                        <div style={{ color: textColor, fontWeight: '700', marginBottom: '0.5rem' }}>
                          NF #{div.numero_nf} - {div.tipo_divergencia.toUpperCase().replace('_', ' ')}
                        </div>
                        <div style={{ color: '#1a1a1a', fontWeight: '600', marginBottom: '0.25rem' }}>
                          {div.produto}
                        </div>
                        <div style={{ color: '#666', fontSize: '0.8rem', marginBottom: '0.5rem' }}>
                          Código: {div.codigo}
                        </div>
                        <div style={{ color: '#666', fontSize: '0.8rem', marginBottom: '0.75rem' }}>
                          NF: {Math.round(div.quantidade_nf)} | Recebido: {Math.round(div.quantidade_confirmada)}
                        </div>
                        <div style={{ color: '#999', fontSize: '0.75rem', marginBottom: '0.75rem' }}>
                          {new Date(div.data_registro).toLocaleDateString('pt-BR', {
                            day: '2-digit',
                            month: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit'
                          })}
                        </div>
                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                          <button
                            onClick={handleResolver}
                            style={{
                              flex: 1,
                              padding: '0.4rem 0.5rem',
                              background: '#4caf50',
                              color: 'white',
                              border: 'none',
                              borderRadius: '3px',
                              fontSize: '0.75rem',
                              fontWeight: '600',
                              cursor: 'pointer'
                            }}
                          >
                            ✓ Resolvida
                          </button>
                          <button
                            onClick={handleDeletar}
                            style={{
                              flex: 1,
                              padding: '0.4rem 0.5rem',
                              background: '#f44336',
                              color: 'white',
                              border: 'none',
                              borderRadius: '3px',
                              fontSize: '0.75rem',
                              fontWeight: '600',
                              cursor: 'pointer'
                            }}
                          >
                            ✗ Deletar
                          </button>
                        </div>
                        {/* Botão para subir estoque do que realmente chegou */}
                        {div.tipo_divergencia !== 'nao_veio' && Math.round(div.quantidade_confirmada) > 0 && (
                          <button
                            onClick={() => {
                              setProdutoSelecionado({
                                id: div.item_id,
                                descricao: div.produto,
                                codigo_produto: div.codigo,
                                quantidade_nf: div.quantidade_confirmada,
                                preco_unitario: 0
                              } as any)
                              setProdutoOlistSelecionado({
                                id: '', sku: '', nome: '', preco: 0,
                                estoque: 0, estoque_saldo: 0, estoque_reservado: 0
                              })
                              setProdutoOlistSKU('')
                              setSugestoesSKU([])
                              setPagina('relacionamento_produto')
                            }}
                            style={{
                              width: '100%',
                              marginTop: '0.5rem',
                              padding: '0.5rem',
                              background: '#007acc',
                              color: 'white',
                              border: 'none',
                              borderRadius: '3px',
                              fontSize: '0.78rem',
                              fontWeight: '700',
                              cursor: 'pointer'
                            }}
                          >
                            🔗 Vincular na Olist e Subir {Math.round(div.quantidade_confirmada)} un
                          </button>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
              </div>
            </div>
          </div>
          {/* SEÇÃO ESTOQUE COMPLETA */}
          {mostrarTodosEstoque && (
            <section className="estoque-hero">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
                <h2>Todos os Produtos ({estoque.length})</h2>
                <button
                  onClick={() => setMostrarTodosEstoque(false)}
                  style={{
                    padding: '0.5rem 1rem',
                    background: '#f0f0f0',
                    border: '1px solid #e0e0e0',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontWeight: '600'
                  }}
                >
                  Voltar
                </button>
              </div>

              <div className="estoque-grid">
                {estoque.map((produto) => (
                  <div key={produto.id_item} className="product-card">
                    <div className="product-header">
                      <div className="product-name">
                        <h3>{produto.descricao}</h3>
                        <span className="product-code">SKU: {produto.codigo_produto}</span>
                      </div>
                      <div className="product-code-badge">
                        {produto.notas_fiscais.length} NF
                      </div>
                    </div>

                    <div className="product-stats">
                      <div className="stat-box">
                        <div className="stat-value">{produto.quantidade_total.toFixed(0)}</div>
                        <div className="stat-label">Qtd Total</div>
                      </div>
                      <div className="stat-box">
                        <div className="stat-value">{produto.quantidade_confirmada.toFixed(0)}</div>
                        <div className="stat-label">Confirmada</div>
                      </div>
                    </div>

                    <div className="price-section">
                      <div className="price-label">Valor Total</div>
                      <div className="price-value">
                        R$ {(produto.quantidade_total * produto.preco_unitario).toFixed(2)}
                      </div>
                    </div>

                    <button
                      className="product-action"
                      onClick={() => abrirDetalhes(produto)}
                    >
                      Detalhes
                    </button>
                  </div>
                ))}
              </div>

              <div className="valor-total">
                Total: {estoque.length} produto{estoque.length !== 1 ? 's' : ''} | R$ {estoque.reduce((sum, p) => sum + (p.quantidade_total * p.preco_unitario), 0).toFixed(2)}
              </div>
            </section>
          )}

          {/* BOTÃO DISCRETO: memória de vínculos */}
          <div style={{ textAlign: 'center', marginTop: '2rem' }}>
            <button
              onClick={abrirModalVinculos}
              style={{
                background: 'transparent',
                border: 'none',
                color: '#9e9e9e',
                fontSize: '0.8rem',
                cursor: 'pointer',
                textDecoration: 'underline',
                padding: '0.5rem'
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = '#007acc')}
              onMouseLeave={(e) => (e.currentTarget.style.color = '#9e9e9e')}
            >
              ⚙ Vínculos salvos (de-para fornecedor → Olist)
            </button>
          </div>
        </main>

        {/* MODAL: VÍNCULOS SALVOS */}
        {modalVinculosAberto && (
          <div className="modal-overlay" onClick={() => setModalVinculosAberto(false)}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '900px', width: '90%' }}>
              <div className="modal-header">
                <h2>Vínculos Salvos (de-para fornecedor → Olist)</h2>
                <button className="modal-close" onClick={() => setModalVinculosAberto(false)}>×</button>
              </div>
              <div className="modal-body">
                <p style={{ color: '#666', marginBottom: '1.5rem', fontSize: '0.9rem' }}>
                  Cada linha é um "apelido" de fornecedor que aponta para um anúncio da Olist.
                  O mesmo anúncio pode ter vários apelidos (descrições/códigos diferentes).
                  Esses vínculos são sugeridos automaticamente em notas futuras.
                </p>
                {listaVinculos.length === 0 ? (
                  <p style={{ color: '#999', textAlign: 'center', padding: '2rem' }}>
                    Nenhum vínculo salvo ainda. Eles são criados quando você vincula um produto à Olist.
                  </p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', maxHeight: '55vh', overflowY: 'auto' }}>
                    {listaVinculos.map((v) => (
                      <div key={v.id} style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr auto',
                        gap: '1rem',
                        alignItems: 'center',
                        background: '#f9f9f9',
                        border: '1px solid #e0e0e0',
                        borderRadius: '6px',
                        padding: '1rem'
                      }}>
                        <div>
                          <p style={{ color: '#999', fontSize: '0.7rem', fontWeight: 700, margin: 0 }}>FORNECEDOR (NF)</p>
                          <p style={{ color: '#1a1a1a', fontSize: '0.9rem', fontWeight: 600, margin: '0.15rem 0 0 0' }}>{v.nf_descricao}</p>
                          <p style={{ color: '#666', fontSize: '0.75rem', margin: 0 }}>Cód: {v.nf_codigo || '-'}</p>
                        </div>
                        <div>
                          <p style={{ color: '#999', fontSize: '0.7rem', fontWeight: 700, margin: 0 }}>ANÚNCIO OLIST</p>
                          <p style={{ color: '#007acc', fontSize: '0.9rem', fontWeight: 600, margin: '0.15rem 0 0 0' }}>{v.olist_nome}</p>
                          <p style={{ color: '#666', fontSize: '0.75rem', margin: 0 }}>SKU: {v.olist_sku} · usado {v.vezes_usado}x</p>
                        </div>
                        <button
                          onClick={() => deletarVinculo(v.id)}
                          style={{
                            padding: '0.5rem 0.75rem', background: '#f44336', color: 'white',
                            border: 'none', borderRadius: '4px', fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer'
                          }}
                        >
                          Remover
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {produtoSelecionado && (
          <ModalDetalhes
            isOpen={modalOpen}
            onClose={() => setModalOpen(false)}
            produto={produtoSelecionado}
            onConfirm={() => {
              setModalOpen(false)
              loadEstoque()
            }}
          />
        )}

        {notaSelecionada && (
          <ModalDetalhesNotaFiscal
            isOpen={modalDetalhesNFAberto}
            onClose={() => setModalDetalhesNFAberto(false)}
            nota={notaSelecionada}
          />
        )}
      </div>
    )
  }

  // ===== PÁGINA DE PRODUTOS DA NOTA =====
  if (pagina === 'produtos_nota' && notaSelecionada && produtosNota.length > 0) {
    return (
      <div className="app">
        <header className="header">
          <div className="container">
            <h1>CONFERÊNCIA DE PRODUTOS</h1>
            <p>NF #{notaSelecionada.numero_nf} - {notaSelecionada.fornecedor}</p>
          </div>
        </header>

        <main className="container main-content">
          <div style={{ display: 'flex', gap: '1rem', marginBottom: '2rem' }}>
            <button
              onClick={() => setPagina('inicial')}
              style={{
                padding: '0.75rem 1.5rem',
                background: '#f0f0f0',
                border: '1px solid #e0e0e0',
                color: '#1a1a1a',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: '600',
                transition: 'all 0.3s'
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = '#e8e8e8')}
              onMouseLeave={(e) => (e.currentTarget.style.background = '#f0f0f0')}
            >
              ← Voltar para Nota
            </button>

            <button
              onClick={() => setModalAdicionarProdutoAberto(true)}
              style={{
                padding: '0.75rem 1.5rem',
                background: '#4caf50',
                border: 'none',
                color: 'white',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: '600',
                transition: 'all 0.3s'
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = '#45a049')}
              onMouseLeave={(e) => (e.currentTarget.style.background = '#4caf50')}
            >
              + Adicionar Produto Manual
            </button>
          </div>

          {/* BARRA DE PROGRESSO DA CONFERÊNCIA */}
          <div style={{
            background: 'white',
            border: '1px solid #e0e0e0',
            borderRadius: '8px',
            padding: '1.25rem 1.5rem',
            marginBottom: '1.5rem',
            boxShadow: '0 1px 3px rgba(0,0,0,0.06)'
          }}>
            <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1rem', color: '#1a1a1a' }}>
              Progresso - Estoque Subido na Olist
            </h3>
            <BarraProgresso itens={produtosNota} />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {produtosNota.map((item) => (
              <div
                key={item.id}
                style={{
                  background: '#ffffff',
                  border: '1px solid #e0e0e0',
                  borderRadius: '8px',
                  padding: '1.5rem',
                  display: 'grid',
                  gridTemplateColumns: '1fr 180px',
                  gap: '2rem',
                  alignItems: 'flex-start',
                  transition: 'all 0.3s'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = '#d0d0d0'
                  e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = '#e0e0e0'
                  e.currentTarget.style.boxShadow = 'none'
                }}
              >
                {/* Informações do Produto */}
                <div>
                  <h3 style={{ color: '#1a1a1a', marginBottom: '0.75rem', fontSize: '1.1rem', fontWeight: '600' }}>
                    {item.descricao}
                  </h3>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '1rem' }}>
                    <div>
                      <p style={{ color: '#999', fontSize: '0.85rem', fontWeight: '600', marginBottom: '0.25rem' }}>
                        CÓDIGO DO PRODUTO
                      </p>
                      <p style={{ color: '#1a1a1a', fontSize: '0.95rem', fontWeight: '500' }}>
                        {item.codigo_produto}
                      </p>
                    </div>
                    <div>
                      <p style={{ color: '#999', fontSize: '0.85rem', fontWeight: '600', marginBottom: '0.25rem' }}>
                        QUANTIDADE ESPERADA
                      </p>
                      <p style={{ color: '#1a1a1a', fontSize: '1.1rem', fontWeight: '700' }}>
                        {Math.round(item.quantidade_nf)} un
                      </p>
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                    <div>
                      <p style={{ color: '#999', fontSize: '0.85rem', fontWeight: '600', marginBottom: '0.25rem' }}>
                        VALOR UNITÁRIO
                      </p>
                      <p style={{ color: '#1a1a1a', fontSize: '1rem', fontWeight: '600' }}>
                        R$ {item.preco_unitario.toFixed(2)}
                      </p>
                    </div>
                    <div>
                      <p style={{ color: '#999', fontSize: '0.85rem', fontWeight: '600', marginBottom: '0.25rem' }}>
                        VALOR TOTAL
                      </p>
                      <p style={{ color: '#1a1a1a', fontSize: '1rem', fontWeight: '600' }}>
                        R$ {(item.quantidade_nf * item.preco_unitario).toFixed(2)}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Botões de Ação */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  <button
                    onClick={() => {
                      const produtoEstoque: ProdutoEstoque = {
                        id_item: item.id,
                        descricao: item.descricao,
                        codigo_produto: item.codigo_produto,
                        quantidade_total: item.quantidade_nf,
                        quantidade_nf: item.quantidade_nf,
                        quantidade_confirmada: item.quantidade_confirmada || item.quantidade_nf,
                        preco_unitario: item.preco_unitario,
                        notas_fiscais: [{
                          numero_nf: notaSelecionada.numero_nf || '',
                          serie: notaSelecionada.serie || '',
                          fornecedor: notaSelecionada.fornecedor || '',
                          quantidade: item.quantidade_nf
                        }]
                      }
                      setProdutoSelecionado(produtoEstoque)
                      setModalOpen(true)
                    }}
                    style={{
                      padding: '0.75rem 1rem',
                      background: '#007acc',
                      color: 'white',
                      border: 'none',
                      borderRadius: '6px',
                      fontWeight: '600',
                      cursor: 'pointer',
                      transition: 'all 0.3s',
                      fontSize: '0.9rem'
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = '#005a96')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = '#007acc')}
                  >
                    Conferência
                  </button>

                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    padding: '0.75rem',
                    background: '#f9f9f9',
                    borderRadius: '6px',
                    border: '1px solid #e0e0e0'
                  }}>
                    <input
                      type="checkbox"
                      id={`produto-nao-veio-${item.id}`}
                      onChange={(e) => {
                        if (e.target.checked) {
                          const produtoEstoque: ProdutoEstoque = {
                            id_item: item.id,
                            descricao: item.descricao,
                            codigo_produto: item.codigo_produto,
                            quantidade_total: item.quantidade_nf,
                            quantidade_confirmada: 0,
                            preco_unitario: item.preco_unitario,
                            notas_fiscais: [{
                              numero_nf: notaSelecionada.numero_nf || '',
                              serie: notaSelecionada.serie || '',
                              fornecedor: notaSelecionada.fornecedor || '',
                              quantidade: item.quantidade_nf
                            }]
                          }
                          setProdutoSelecionado(produtoEstoque)
                          setModalOpen(true)
                        }
                      }}
                      style={{
                        width: '16px',
                        height: '16px',
                        cursor: 'pointer'
                      }}
                    />
                    <label htmlFor={`produto-nao-veio-${item.id}`} style={{
                      cursor: 'pointer',
                      fontSize: '0.85rem',
                      color: '#666',
                      fontWeight: '500',
                      margin: 0
                    }}>
                      Não veio
                    </label>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </main>

        {produtoSelecionado && (
          <ModalDetalhesNota
            isOpen={modalOpen}
            onClose={() => setModalOpen(false)}
            produto={produtoSelecionado}
            notaNota={notaSelecionada}
            onNaoConfirmado={(qtd) => irParaOlistSubirEstoque(qtd)}
            onDivergenciaConfirmada={(qtd) => irParaOlistSubirEstoque(qtd)}
          />
        )}

        {/* MODAL ADICIONAR PRODUTO MANUALMENTE */}
        {modalAdicionarProdutoAberto && (
          <div className="modal-overlay" onClick={() => setModalAdicionarProdutoAberto(false)}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h2>Adicionar Produto Manual</h2>
                <button className="modal-close" onClick={() => setModalAdicionarProdutoAberto(false)}>
                  ×
                </button>
              </div>

              <div className="modal-body">
                <p style={{ color: '#666', marginBottom: '1.5rem', fontSize: '0.95rem' }}>
                  Use este formulário para adicionar produtos que chegaram mas não foram informados na nota fiscal.
                </p>

                <div className="form-group">
                  <label className="form-label">Código do Produto</label>
                  <input
                    type="text"
                    className="form-input"
                    value={novoProduto.codigo}
                    onChange={(e) => setNovoProduto({ ...novoProduto, codigo: e.target.value })}
                    placeholder="Ex: 001234"
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Descrição do Produto</label>
                  <input
                    type="text"
                    className="form-input"
                    value={novoProduto.descricao}
                    onChange={(e) => setNovoProduto({ ...novoProduto, descricao: e.target.value })}
                    placeholder="Ex: Produto XYZ"
                  />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="form-group">
                    <label className="form-label">Quantidade</label>
                    <input
                      type="text"
                      className="form-input"
                      value={novoProduto.quantidade}
                      onChange={(e) => {
                        const val = e.target.value
                        if (val === '' || !isNaN(parseFloat(val))) {
                          setNovoProduto({ ...novoProduto, quantidade: parseFloat(val) || 0 })
                        }
                      }}
                      placeholder="0"
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label">Preço Unitário (R$)</label>
                    <input
                      type="text"
                      className="form-input"
                      value={novoProduto.preco}
                      onChange={(e) => {
                        const val = e.target.value
                        if (val === '' || !isNaN(parseFloat(val))) {
                          setNovoProduto({ ...novoProduto, preco: parseFloat(val) || 0 })
                        }
                      }}
                      placeholder="0.00"
                    />
                  </div>
                </div>

                <div className="button-group">
                  <button
                    className="btn btn-secondary"
                    onClick={() => setModalAdicionarProdutoAberto(false)}
                  >
                    Cancelar
                  </button>
                  <button
                    className="btn btn-primary"
                    onClick={handleAdicionarProduto}
                  >
                    Adicionar Produto
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }

  // ===== PÁGINA DE CONFERÊNCIA =====
  if (pagina === 'conferencia' && notaSelecionada) {
    const totalNota = notaSelecionada.itens?.reduce(
      (sum, item) => sum + item.quantidade_nf * item.preco_unitario,
      0
    ) || 0

    return (
      <div className="app">
        <header className="header">
          <div className="container">
            <h1>CONFERÊNCIA DE NOTA FISCAL</h1>
            <p>Verifique e confirme os itens recebidos</p>
          </div>
        </header>

        <main className="container main-content">
          <button
            onClick={voltarParaInicial}
            style={{
              marginBottom: '2rem',
              padding: '0.75rem 1.5rem',
              background: '#f0f0f0',
              border: '1px solid #e0e0e0',
              color: '#1a1a1a',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: '600',
              transition: 'all 0.3s'
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = '#e8e8e8')}
            onMouseLeave={(e) => (e.currentTarget.style.background = '#f0f0f0')}
          >
            ← Voltar para notas
          </button>

          {/* CARD INFORMAÇÕES DA NOTA */}
          <div className="card" style={{ marginBottom: '2rem' }}>
            <h2>Informações da Nota Fiscal</h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
              <div>
                <div style={{ marginBottom: '1.5rem' }}>
                  <p style={{ color: '#666', fontSize: '0.85rem', marginBottom: '0.25rem' }}>FORNECEDOR</p>
                  <p style={{ color: '#1a1a1a', fontSize: '1rem', fontWeight: '600' }}>{notaSelecionada.fornecedor}</p>
                </div>
                <div style={{ marginBottom: '1.5rem' }}>
                  <p style={{ color: '#666', fontSize: '0.85rem', marginBottom: '0.25rem' }}>NÚMERO DA NF</p>
                  <p style={{ color: '#1a1a1a', fontSize: '1rem', fontWeight: '600' }}>NF #{notaSelecionada.numero_nf}</p>
                </div>
                <div>
                  <p style={{ color: '#666', fontSize: '0.85rem', marginBottom: '0.25rem' }}>SÉRIE</p>
                  <p style={{ color: '#1a1a1a', fontSize: '1rem', fontWeight: '600' }}>{notaSelecionada.serie}</p>
                </div>
              </div>
              <div>
                <div style={{ marginBottom: '1.5rem' }}>
                  <p style={{ color: '#666', fontSize: '0.85rem', marginBottom: '0.25rem' }}>DATA DE EMISSÃO</p>
                  <p style={{ color: '#1a1a1a', fontSize: '1rem', fontWeight: '600' }}>
                    {notaSelecionada.data_emissao
                      ? new Date(notaSelecionada.data_emissao).toLocaleDateString('pt-BR')
                      : '-'}
                  </p>
                </div>
                <div style={{ marginBottom: '1.5rem' }}>
                  <p style={{ color: '#666', fontSize: '0.85rem', marginBottom: '0.25rem' }}>TOTAL DA NOTA</p>
                  <p style={{ color: '#1a1a1a', fontSize: '1.2rem', fontWeight: '700' }}>R$ {totalNota.toFixed(2)}</p>
                </div>
                <div>
                  <p style={{ color: '#666', fontSize: '0.85rem', marginBottom: '0.25rem' }}>QUANTIDADE DE ITENS</p>
                  <p style={{ color: '#1a1a1a', fontSize: '1rem', fontWeight: '600' }}>
                    {notaSelecionada.itens?.length || 0} item{notaSelecionada.itens?.length !== 1 ? 'ns' : ''}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* TABELA DE ITENS */}
          <div className="card">
            <h2>Itens da Nota Fiscal</h2>
            {notaSelecionada.itens && notaSelecionada.itens.length > 0 ? (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ backgroundColor: '#f9f9f9', borderBottom: '2px solid #e0e0e0' }}>
                      <th style={{ padding: '1rem', textAlign: 'left', color: '#1a1a1a', fontWeight: '600' }}>Descrição</th>
                      <th style={{ padding: '1rem', textAlign: 'center', color: '#1a1a1a', fontWeight: '600' }}>Código</th>
                      <th style={{ padding: '1rem', textAlign: 'center', color: '#1a1a1a', fontWeight: '600' }}>Quantidade</th>
                      <th style={{ padding: '1rem', textAlign: 'right', color: '#1a1a1a', fontWeight: '600' }}>Preço Unit.</th>
                      <th style={{ padding: '1rem', textAlign: 'right', color: '#1a1a1a', fontWeight: '600' }}>Subtotal</th>
                      <th style={{ padding: '1rem', textAlign: 'center', color: '#1a1a1a', fontWeight: '600' }}>Ação</th>
                    </tr>
                  </thead>
                  <tbody>
                    {notaSelecionada.itens.map((item, idx) => (
                      <tr
                        key={item.id}
                        style={{
                          borderBottom: '1px solid #e0e0e0',
                          backgroundColor: idx % 2 === 0 ? '#f9f9f9' : '#fff'
                        }}
                      >
                        <td style={{ padding: '1rem', color: '#1a1a1a' }}>{item.descricao}</td>
                        <td style={{ padding: '1rem', textAlign: 'center', color: '#666' }}>{item.codigo_produto}</td>
                        <td style={{ padding: '1rem', textAlign: 'center', color: '#1a1a1a', fontWeight: '600' }}>
                          {Math.round(item.quantidade_nf)}
                        </td>
                        <td style={{ padding: '1rem', textAlign: 'right', color: '#666' }}>
                          R$ {item.preco_unitario.toFixed(2)}
                        </td>
                        <td style={{ padding: '1rem', textAlign: 'right', color: '#1a1a1a', fontWeight: '600' }}>
                          R$ {(item.quantidade_nf * item.preco_unitario).toFixed(2)}
                        </td>
                        <td style={{ padding: '1rem', textAlign: 'center' }}>
                          <button
                            style={{
                              padding: '0.5rem 1rem',
                              background: '#007acc',
                              color: 'white',
                              border: 'none',
                              borderRadius: '4px',
                              cursor: 'pointer',
                              fontSize: '0.85rem',
                              fontWeight: '600'
                            }}
                          >
                            Confirmar
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p style={{ color: '#666', textAlign: 'center', padding: '2rem' }}>Nenhum item nesta nota</p>
            )}
          </div>
        </main>
      </div>
    )
  }

  // ===== PÁGINA DE RELACIONAMENTO DE PRODUTO =====
  if (pagina === 'relacionamento_produto') {
    // Usar o produto que foi clicado para conferência (produtoSelecionado)
    const produtoAtual = produtoSelecionado

    return (
      <div className="app">
        <header className="header">
          <div className="container">
            <h1>INTEGRAÇÃO OLIST</h1>
            <p>Vincular produto do estoque ao anúncio da Olist</p>
          </div>
        </header>

        <main className="container main-content">
          <div className="card" style={{ maxWidth: '800px', margin: '0 auto' }}>
            <h2>Vincular ao Anúncio Olist</h2>

            {/* PRODUTO ATUAL DA NOTA */}
            {produtoAtual && (
              <div style={{ background: '#f0f9ff', border: '2px solid #007acc', padding: '1.5rem', borderRadius: '8px', marginBottom: '2rem' }}>
                <h3 style={{ color: '#007acc', marginTop: 0 }}>Produto da Nota Fiscal</h3>
                <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '2rem' }}>
                  <div>
                    <p style={{ color: '#666', fontSize: '0.85rem', fontWeight: '600', marginBottom: '0.25rem' }}>
                      PRODUTO
                    </p>
                    <p style={{ color: '#1a1a1a', fontSize: '1.1rem', fontWeight: '700', margin: 0 }}>
                      {produtoAtual.descricao}
                    </p>
                  </div>
                  <div>
                    <p style={{ color: '#666', fontSize: '0.85rem', fontWeight: '600', marginBottom: '0.25rem' }}>
                      CÓDIGO
                    </p>
                    <p style={{ color: '#1a1a1a', fontSize: '0.95rem', fontWeight: '600', margin: 0 }}>
                      {produtoAtual.codigo_produto}
                    </p>
                  </div>
                  <div>
                    <p style={{ color: '#666', fontSize: '0.85rem', fontWeight: '600', marginBottom: '0.25rem' }}>
                      QUANTIDADE
                    </p>
                    <p style={{ color: '#1a1a1a', fontSize: '0.95rem', fontWeight: '600', margin: 0 }}>
                      {Math.round(produtoAtual.quantidade_nf)} un
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* SUGESTÃO AUTOMÁTICA (memória de vínculos) */}
            {sugestaoVinculo && !sugestaoDispensada && !produtoOlistSelecionado.sku && (
              <div style={{
                background: '#fff8e1',
                border: '2px solid #ffb300',
                padding: '1.25rem 1.5rem',
                borderRadius: '8px',
                marginBottom: '1.5rem'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                  <span style={{ fontSize: '1.2rem' }}>💡</span>
                  <strong style={{ color: '#e65100' }}>Esse produto já foi vinculado antes!</strong>
                </div>
                <p style={{ color: '#5d4037', fontSize: '0.9rem', margin: '0 0 0.25rem 0' }}>
                  Anúncio Olist: <strong>{sugestaoVinculo.olist_nome}</strong>
                </p>
                <p style={{ color: '#8d6e63', fontSize: '0.8rem', margin: '0 0 1rem 0' }}>
                  SKU {sugestaoVinculo.olist_sku} · usado {sugestaoVinculo.vezes_usado}x · confirme se é o mesmo produto
                </p>
                <div style={{ display: 'flex', gap: '0.75rem' }}>
                  <button
                    onClick={usarSugestao}
                    style={{
                      padding: '0.6rem 1.25rem', background: '#2e7d32', color: 'white',
                      border: 'none', borderRadius: '6px', fontWeight: 700, cursor: 'pointer', fontSize: '0.9rem'
                    }}
                  >
                    ✓ Sim, é esse anúncio
                  </button>
                  <button
                    onClick={() => setSugestaoDispensada(true)}
                    style={{
                      padding: '0.6rem 1.25rem', background: '#f0f0f0', color: '#1a1a1a',
                      border: '1px solid #ddd', borderRadius: '6px', fontWeight: 600, cursor: 'pointer', fontSize: '0.9rem'
                    }}
                  >
                    Não, buscar outro
                  </button>
                </div>
              </div>
            )}

            {/* BUSCA DE SKU OLIST */}
            <div className="form-group" style={{ position: 'relative' }}>
              <label className="form-label">Buscar Anúncio Olist (por SKU ou Nome)</label>
              <input
                type="text"
                className="form-input"
                value={produtoOlistSKU}
                onChange={(e) => handleBuscarSKU(e.target.value)}
                placeholder="Digite SKU ou nome do produto (mínimo 2 caracteres)..."
                style={{
                  padding: '0.75rem',
                  border: produtoOlistSKU.length > 0 ? '2px solid #007acc' : '1px solid #ddd',
                  borderRadius: '4px',
                  fontSize: '0.95rem',
                  transition: 'all 0.2s'
                }}
              />

              {/* SUGESTÕES DE SKU - COM FEEDBACK */}
              {produtoOlistSKU.length > 0 && sugestoesSKU.length > 0 && (
                <div style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  right: 0,
                  background: 'white',
                  border: '1px solid #ddd',
                  borderTop: 'none',
                  borderRadius: '0 0 4px 4px',
                  boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
                  zIndex: 10,
                  maxHeight: '300px',
                  overflowY: 'auto'
                }}>
                  {sugestoesSKU.map((sugestao) => (
                    <div
                      key={sugestao.sku}
                      onClick={() => handleSelecionarSKU(sugestao)}
                      style={{
                        padding: '0.75rem 1rem',
                        borderBottom: '1px solid #f0f0f0',
                        cursor: 'pointer',
                        transition: 'all 0.2s',
                        background: 'white'
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = '#f9f9f9')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'white')}
                    >
                      <div style={{ color: '#666', fontSize: '0.8rem', fontWeight: '600' }}>
                        SKU: {sugestao.sku}
                      </div>
                      <div style={{ color: '#1a1a1a', fontSize: '0.95rem', fontWeight: '500' }}>
                        {sugestao.nome}
                      </div>
                      <div style={{ color: '#007acc', fontSize: '0.9rem', fontWeight: '600' }}>
                        R$ {sugestao.preco.toFixed(2)}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* MENSAGEM DE NENHUM RESULTADO */}
              {produtoOlistSKU.length >= 2 && sugestoesSKU.length === 0 && (
                <div style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  right: 0,
                  background: '#fff3cd',
                  border: '1px solid #ffc107',
                  borderTop: 'none',
                  borderRadius: '0 0 4px 4px',
                  padding: '1rem',
                  color: '#856404',
                  fontSize: '0.9rem',
                  zIndex: 10
                }}>
                  Nenhum produto encontrado com "{produtoOlistSKU}".
                  <br />
                  Verifique se o SKU ou nome está correto na sua conta Olist.
                </div>
              )}
            </div>

            {/* MODO MANUAL - Quando nenhum produto foi encontrado via API */}
            {produtoOlistSKU.length >= 2 && sugestoesSKU.length === 0 && !produtoOlistSelecionado.sku && (
              <div style={{
                background: '#f0f9ff',
                border: '2px solid #007acc',
                padding: '1.5rem',
                borderRadius: '8px',
                marginTop: '1.5rem',
                marginBottom: '1.5rem'
              }}>
                <h3 style={{ color: '#007acc', marginTop: 0 }}>Preencher Dados Manualmente</h3>
                <p style={{ color: '#666', fontSize: '0.9rem', marginBottom: '1.5rem' }}>
                  Preencha os dados do produto encontrado na sua Olist:
                </p>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
                  <div className="form-group">
                    <label className="form-label">Nome do Produto</label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder="Ex: Suporte Baú Bagageiro Yamaha"
                      value={produtoOlistSelecionado.nome}
                      onChange={(e) => setProdutoOlistSelecionado({
                        ...produtoOlistSelecionado,
                        nome: e.target.value
                      })}
                      style={{ padding: '0.75rem', border: '1px solid #ddd', borderRadius: '4px' }}
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label">Preço</label>
                    <input
                      type="number"
                      className="form-input"
                      placeholder="Ex: 299.90"
                      value={produtoOlistSelecionado.preco}
                      onChange={(e) => setProdutoOlistSelecionado({
                        ...produtoOlistSelecionado,
                        preco: parseFloat(e.target.value) || 0
                      })}
                      style={{ padding: '0.75rem', border: '1px solid #ddd', borderRadius: '4px' }}
                    />
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="form-group">
                    <label className="form-label">Estoque Disponível</label>
                    <input
                      type="number"
                      className="form-input"
                      placeholder="Ex: 47"
                      value={produtoOlistSelecionado.estoque}
                      onChange={(e) => setProdutoOlistSelecionado({
                        ...produtoOlistSelecionado,
                        estoque: parseInt(e.target.value) || 0
                      })}
                      style={{ padding: '0.75rem', border: '1px solid #ddd', borderRadius: '4px' }}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* PRODUTO SELECIONADO */}
            {produtoOlistSelecionado.sku && (
              <div style={{
                background: '#f0f4c3',
                border: '2px solid #cddc39',
                padding: '1.5rem',
                borderRadius: '8px',
                marginTop: '1.5rem',
                marginBottom: '1.5rem'
              }}>
                <h3 style={{ color: '#827717', marginTop: 0 }}>Anúncio Selecionado</h3>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '1.5rem' }}>
                  <div>
                    <p style={{ color: '#666', fontSize: '0.85rem', fontWeight: '600', marginBottom: '0.25rem' }}>
                      SKU
                    </p>
                    <p style={{ color: '#1a1a1a', fontSize: '0.95rem', fontWeight: '700', margin: 0 }}>
                      {produtoOlistSelecionado.sku}
                    </p>
                  </div>
                  <div>
                    <p style={{ color: '#666', fontSize: '0.85rem', fontWeight: '600', marginBottom: '0.25rem' }}>
                      NOME DO ANÚNCIO
                    </p>
                    <p style={{ color: '#1a1a1a', fontSize: '0.9rem', fontWeight: '600', margin: 0 }}>
                      {produtoOlistSelecionado.nome}
                    </p>
                  </div>
                  <div>
                    <p style={{ color: '#666', fontSize: '0.85rem', fontWeight: '600', marginBottom: '0.25rem' }}>
                      PREÇO
                    </p>
                    <p style={{ color: '#1a1a1a', fontSize: '0.95rem', fontWeight: '700', margin: 0 }}>
                      R$ {produtoOlistSelecionado.preco.toFixed(2)}
                    </p>
                  </div>
                  <div>
                    <p style={{ color: '#666', fontSize: '0.85rem', fontWeight: '600', marginBottom: '0.25rem' }}>
                      ESTOQUE OLIST
                    </p>
                    <p style={{ color: '#1a1a1a', fontSize: '0.95rem', fontWeight: '700', margin: 0 }}>
                      {produtoOlistSelecionado.estoque} un disp.
                    </p>
                    <p style={{ color: '#999', fontSize: '0.75rem', margin: '0.15rem 0 0 0' }}>
                      Saldo: {produtoOlistSelecionado.estoque_saldo} | Reserv.: {produtoOlistSelecionado.estoque_reservado}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* PREVIEW DO CÁLCULO DE ESTOQUE */}
            {produtoOlistSelecionado.sku && produtoSelecionado && (
              <div style={{
                background: '#e8f5e9',
                border: '2px solid #4caf50',
                padding: '1.5rem',
                borderRadius: '8px',
                marginBottom: '1.5rem'
              }}>
                <h3 style={{ color: '#2e7d32', marginTop: 0 }}>Atualização de Estoque</h3>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-around', textAlign: 'center', flexWrap: 'wrap', gap: '1rem' }}>
                  <div>
                    <p style={{ color: '#666', fontSize: '0.8rem', fontWeight: '600', margin: 0 }}>ESTOQUE ATUAL OLIST</p>
                    <p style={{ color: '#1a1a1a', fontSize: '1.5rem', fontWeight: '700', margin: 0 }}>
                      {produtoOlistSelecionado.estoque_saldo}
                    </p>
                  </div>
                  <div style={{ fontSize: '1.5rem', color: '#4caf50', fontWeight: '700' }}>+</div>
                  <div>
                    <p style={{ color: '#666', fontSize: '0.8rem', fontWeight: '600', margin: 0 }}>QTD RECEBIDA (A SUBIR)</p>
                    <p style={{ color: '#007acc', fontSize: '1.5rem', fontWeight: '700', margin: 0 }}>
                      {Math.round(produtoSelecionado.quantidade_nf)}
                    </p>
                  </div>
                  <div style={{ fontSize: '1.5rem', color: '#4caf50', fontWeight: '700' }}>=</div>
                  <div>
                    <p style={{ color: '#666', fontSize: '0.8rem', fontWeight: '600', margin: 0 }}>NOVO ESTOQUE TOTAL</p>
                    <p style={{ color: '#2e7d32', fontSize: '1.8rem', fontWeight: '800', margin: 0 }}>
                      {produtoOlistSelecionado.estoque_saldo + Math.round(produtoSelecionado.quantidade_nf)}
                    </p>
                  </div>
                </div>
              </div>
            )}

            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end', paddingTop: '1rem', borderTop: '1px solid #e0e0e0' }}>
              <button
                onClick={voltarParaInicial}
                style={{
                  padding: '0.75rem 1.5rem',
                  background: '#f0f0f0',
                  color: '#1a1a1a',
                  border: '1px solid #e0e0e0',
                  borderRadius: '4px',
                  fontWeight: '600',
                  cursor: 'pointer',
                  fontSize: '0.95rem',
                  transition: 'all 0.3s'
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = '#e8e8e8')}
                onMouseLeave={(e) => (e.currentTarget.style.background = '#f0f0f0')}
              >
                ← Voltar para Inicial
              </button>
              <button
                onClick={handleVincular}
                disabled={!produtoOlistSelecionado.sku}
                style={{
                  padding: '0.75rem 1.5rem',
                  background: produtoOlistSelecionado.sku ? '#007acc' : '#ccc',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  fontWeight: '600',
                  cursor: produtoOlistSelecionado.sku ? 'pointer' : 'not-allowed',
                  fontSize: '0.95rem',
                  transition: 'all 0.3s'
                }}
                onMouseEnter={(e) => {
                  if (produtoOlistSelecionado.sku) {
                    e.currentTarget.style.background = '#005a96'
                  }
                }}
                onMouseLeave={(e) => {
                  if (produtoOlistSelecionado.sku) {
                    e.currentTarget.style.background = '#007acc'
                  }
                }}
              >
                Vincular e Atualizar Estoque →
              </button>
            </div>
          </div>
        </main>
      </div>
    )
  }

  return null
}

export default App
