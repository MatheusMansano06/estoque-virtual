import { useState, useEffect } from 'react'
import './App.css'

interface NotaFiscal {
  id: number
  numero_nf: string
  serie: string
  fornecedor: string
  status: string
}

function App() {
  const [file, setFile] = useState<File | null>(null)
  const [notas, setNotas] = useState<NotaFiscal[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [searchCode, setSearchCode] = useState('')
  const [searchResult, setSearchResult] = useState<NotaFiscal | null>(null)

  // Carregar notas ao iniciar
  useEffect(() => {
    loadNotas()
  }, [])

  const loadNotas = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/notas-fiscais')
      const data = await res.json()
      setNotas(data.items || [])
    } catch (err) {
      console.error('Erro ao carregar:', err)
    }
  }

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!searchCode.trim()) {
      setMessage('Digite um código ou número de NF!')
      return
    }

    try {
      // Tenta buscar como número direto
      const res = await fetch(
        `http://localhost:8000/api/notas-fiscais?search=${encodeURIComponent(searchCode)}`
      )
      const data = await res.json()
      const foundNota = data.items?.find(
        (n: NotaFiscal) =>
          n.numero_nf === searchCode ||
          n.numero_nf.includes(searchCode) ||
          searchCode.includes(n.numero_nf)
      )

      if (foundNota) {
        setSearchResult(foundNota)
        setMessage(`✅ Encontrada NF #${foundNota.numero_nf}`)
      } else {
        setSearchResult(null)
        setMessage('❌ NF não encontrada')
      }
    } catch (err) {
      setMessage(`❌ Erro na busca: ${err}`)
    }
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
        setMessage(`✅ NF #${data.numero_nf} - ${data.itens_encontrados} itens`)
        setFile(null)
        loadNotas()
      } else {
        setMessage(`❌ Erro: ${data.error || 'Erro desconhecido'}`)
      }
    } catch (err) {
      setMessage(`❌ Erro: ${err}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div className="container">
          <h1>📦 Estoque Virtual - NF-e</h1>
          <p>Sistema de entrada de estoque via Nota Fiscal Eletrônica</p>
        </div>
      </header>

      <main className="container main-content">
        {/* Busca por Código de Barras */}
        <section className="card" style={{ marginBottom: '2rem' }}>
          <h2>🔍 Buscar NF por Código de Barras</h2>
          <form onSubmit={handleSearch} style={{ display: 'flex', gap: '0.5rem' }}>
            <input
              type="text"
              placeholder="Digite o código de barras ou número da NF..."
              value={searchCode}
              onChange={(e) => setSearchCode(e.target.value)}
              style={{
                flex: 1,
                padding: '0.75rem',
                border: '1px solid #d0d0d0',
                borderRadius: '4px',
                fontSize: '1rem',
              }}
            />
            <button
              type="submit"
              style={{
                padding: '0.75rem 1.5rem',
                backgroundColor: '#1e40af',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: 'bold',
              }}
            >
              Buscar
            </button>
          </form>

          {searchResult && (
            <div
              style={{
                marginTop: '1rem',
                padding: '1rem',
                backgroundColor: '#e3f2fd',
                border: '1px solid #90caf9',
                borderRadius: '4px',
              }}
            >
              <h3 style={{ color: '#1e40af', marginBottom: '0.5rem' }}>
                ✅ Resultado da Busca
              </h3>
              <p>
                <strong>NF:</strong> {searchResult.numero_nf} - Série {searchResult.serie}
              </p>
              <p>
                <strong>Fornecedor:</strong> {searchResult.fornecedor}
              </p>
              <p>
                <strong>Status:</strong> {searchResult.status}
              </p>
            </div>
          )}
        </section>

        <div className="grid">
          {/* Upload */}
          <section className="card">
            <h2>Upload de Nota Fiscal</h2>
            <form onSubmit={handleUpload}>
              <div style={{ marginBottom: '1rem' }}>
                <input
                  type="file"
                  accept=".xml,.pdf"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  disabled={loading}
                  style={{
                    padding: '0.75rem',
                    border: '1px solid #d0d0d0',
                    borderRadius: '4px',
                    width: '100%',
                  }}
                />
              </div>

              {message && (
                <div
                  style={{
                    padding: '1rem',
                    marginBottom: '1rem',
                    backgroundColor: message.includes('✅') ? '#e8f5e9' : '#ffebee',
                    color: message.includes('✅') ? '#2e7d32' : '#c62828',
                    borderLeft: '4px solid ' + (message.includes('✅') ? '#4caf50' : '#f44336'),
                    borderRadius: '4px',
                  }}
                >
                  {message}
                </div>
              )}

              <button
                type="submit"
                disabled={!file || loading}
                style={{
                  padding: '0.75rem 1.5rem',
                  backgroundColor: '#1e40af',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: file && !loading ? 'pointer' : 'not-allowed',
                  opacity: file && !loading ? 1 : 0.6,
                  width: '100%',
                  fontWeight: 'bold',
                }}
              >
                {loading ? 'Processando...' : 'Enviar NF-e'}
              </button>
            </form>
          </section>

          {/* Lista */}
          <section className="card">
            <h2>Notas Fiscais Processadas</h2>
            {notas.length === 0 ? (
              <p style={{ color: '#666', textAlign: 'center', padding: '2rem' }}>
                Nenhuma nota processada ainda
              </p>
            ) : (
              <div style={{ maxHeight: '500px', overflowY: 'auto' }}>
                {notas.map((nota) => (
                  <div
                    key={nota.id}
                    style={{
                      padding: '1rem',
                      marginBottom: '0.75rem',
                      border: '1px solid #d0d0d0',
                      borderLeft: '4px solid #1e40af',
                      borderRadius: '4px',
                      backgroundColor: '#f8f9fa',
                    }}
                  >
                    <div style={{ marginBottom: '0.5rem' }}>
                      <strong>NF #{nota.numero_nf}</strong>
                      <span
                        style={{
                          marginLeft: '1rem',
                          padding: '0.25rem 0.5rem',
                          backgroundColor: nota.status === 'processado' ? '#c8e6c9' : '#fff9c4',
                          borderRadius: '3px',
                          fontSize: '0.8rem',
                          fontWeight: 'bold',
                        }}
                      >
                        {nota.status}
                      </span>
                    </div>
                    <div style={{ fontSize: '0.9rem', color: '#666' }}>
                      <p>Fornecedor: {nota.fornecedor}</p>
                      <p>Série: {nota.serie}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  )
}

export default App
