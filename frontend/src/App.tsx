import { useState } from 'react'
import UploadNFe from './components/UploadNFe'
import NotaFiscalList from './components/NotaFiscalList'
import './App.css'

function App() {
  const [refreshList, setRefreshList] = useState(0)

  const handleUploadSuccess = () => {
    setRefreshList(prev => prev + 1)
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
        <div className="grid">
          <section className="card">
            <h2>Upload de Nota Fiscal</h2>
            <UploadNFe onUploadSuccess={handleUploadSuccess} />
          </section>

          <section className="card">
            <h2>Notas Fiscais Processadas</h2>
            <NotaFiscalList refresh={refreshList} />
          </section>
        </div>
      </main>
    </div>
  )
}

export default App
