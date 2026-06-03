import React, { useState, useEffect } from 'react'
import { useFornecedores, type Fornecedor, type FornecedorForm } from '../hooks/useFornecedores'

export const FornecedoresManager: React.FC = () => {
  const { fornecedores, loading, error, listar, criar, editar, deletar } = useFornecedores()
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formData, setFormData] = useState<FornecedorForm>({
    nome: '',
    cnpj: '',
    contato_whatsapp: '',
    email: '',
    endereco: ''
  })
  const [localError, setLocalError] = useState<string | null>(null)
  const [localLoading, setLocalLoading] = useState(false)

  useEffect(() => {
    listar()
  }, [])

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLocalLoading(true)
    setLocalError(null)

    try {
      if (editingId) {
        await editar(editingId, formData)
      } else {
        await criar(formData)
      }

      // Reset form
      setFormData({
        nome: '',
        cnpj: '',
        contato_whatsapp: '',
        email: '',
        endereco: ''
      })
      setIsFormOpen(false)
      setEditingId(null)
    } catch (err: any) {
      setLocalError(err.response?.data?.error || 'Erro ao salvar fornecedor')
    } finally {
      setLocalLoading(false)
    }
  }

  const handleEdit = (fornecedor: Fornecedor) => {
    setFormData({
      nome: fornecedor.nome,
      cnpj: fornecedor.cnpj || '',
      contato_whatsapp: fornecedor.contato_whatsapp || '',
      email: fornecedor.email || '',
      endereco: fornecedor.endereco || ''
    })
    setEditingId(fornecedor.id)
    setIsFormOpen(true)
  }

  const handleDelete = async (id: number) => {
    if (window.confirm('Tem certeza que deseja deletar este fornecedor?')) {
      try {
        await deletar(id)
      } catch (err: any) {
        alert('Erro ao deletar fornecedor: ' + (err.response?.data?.error || 'Desconhecido'))
      }
    }
  }

  const handleCancel = () => {
    setIsFormOpen(false)
    setEditingId(null)
    setFormData({
      nome: '',
      cnpj: '',
      contato_whatsapp: '',
      email: '',
      endereco: ''
    })
    setLocalError(null)
  }

  return (
    <div style={{ padding: '20px' }}>
      <div style={{ marginBottom: '20px' }}>
        <h2>Gestão de Fornecedores</h2>
        <button
          onClick={() => {
            setIsFormOpen(!isFormOpen)
            if (isFormOpen) handleCancel()
          }}
          style={{
            padding: '10px 20px',
            backgroundColor: '#1976d2',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontSize: '14px',
            fontWeight: 'bold'
          }}
        >
          {isFormOpen ? '✕ Cancelar' : '+ Novo Fornecedor'}
        </button>
      </div>

      {error && (
        <div style={{
          padding: '12px',
          backgroundColor: '#ffebee',
          color: '#c62828',
          borderRadius: '4px',
          marginBottom: '20px'
        }}>
          {error}
        </div>
      )}

      {localError && (
        <div style={{
          padding: '12px',
          backgroundColor: '#ffebee',
          color: '#c62828',
          borderRadius: '4px',
          marginBottom: '20px'
        }}>
          {localError}
        </div>
      )}

      {isFormOpen && (
        <form onSubmit={handleSubmit} style={{
          backgroundColor: '#f5f5f5',
          padding: '20px',
          borderRadius: '8px',
          marginBottom: '20px',
          border: '1px solid #ddd'
        }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px', marginBottom: '15px' }}>
            <div>
              <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
                Nome *
              </label>
              <input
                type="text"
                name="nome"
                value={formData.nome}
                onChange={handleInputChange}
                required
                style={{
                  width: '100%',
                  padding: '8px',
                  border: '1px solid #ccc',
                  borderRadius: '4px',
                  fontSize: '14px',
                  boxSizing: 'border-box'
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
                CNPJ
              </label>
              <input
                type="text"
                name="cnpj"
                value={formData.cnpj}
                onChange={handleInputChange}
                placeholder="00.000.000/0000-00"
                style={{
                  width: '100%',
                  padding: '8px',
                  border: '1px solid #ccc',
                  borderRadius: '4px',
                  fontSize: '14px',
                  boxSizing: 'border-box'
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
                WhatsApp
              </label>
              <input
                type="tel"
                name="contato_whatsapp"
                value={formData.contato_whatsapp}
                onChange={handleInputChange}
                placeholder="5519978149245"
                style={{
                  width: '100%',
                  padding: '8px',
                  border: '1px solid #ccc',
                  borderRadius: '4px',
                  fontSize: '14px',
                  boxSizing: 'border-box'
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
                Email
              </label>
              <input
                type="email"
                name="email"
                value={formData.email}
                onChange={handleInputChange}
                style={{
                  width: '100%',
                  padding: '8px',
                  border: '1px solid #ccc',
                  borderRadius: '4px',
                  fontSize: '14px',
                  boxSizing: 'border-box'
                }}
              />
            </div>
          </div>

          <div style={{ marginBottom: '15px' }}>
            <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
              Endereço
            </label>
            <textarea
              name="endereco"
              value={formData.endereco}
              onChange={handleInputChange}
              rows={3}
              style={{
                width: '100%',
                padding: '8px',
                border: '1px solid #ccc',
                borderRadius: '4px',
                fontSize: '14px',
                boxSizing: 'border-box',
                fontFamily: 'inherit'
              }}
            />
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              type="submit"
              disabled={localLoading}
              style={{
                padding: '10px 20px',
                backgroundColor: '#4CAF50',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: localLoading ? 'not-allowed' : 'pointer',
                fontSize: '14px',
                fontWeight: 'bold',
                opacity: localLoading ? 0.6 : 1
              }}
            >
              {localLoading ? 'Salvando...' : editingId ? '💾 Atualizar' : '✓ Criar'}
            </button>
            <button
              type="button"
              onClick={handleCancel}
              style={{
                padding: '10px 20px',
                backgroundColor: '#999',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '14px',
                fontWeight: 'bold'
              }}
            >
              ✕ Cancelar
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: '#666' }}>
          Carregando fornecedores...
        </div>
      ) : fornecedores.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px', color: '#999' }}>
          Nenhum fornecedor cadastrado. Crie um novo para começar.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{
            width: '100%',
            borderCollapse: 'collapse',
            backgroundColor: 'white',
            borderRadius: '8px',
            overflow: 'hidden',
            boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
          }}>
            <thead>
              <tr style={{ backgroundColor: '#f0f0f0', borderBottom: '2px solid #ddd' }}>
                <th style={{ padding: '12px', textAlign: 'left' }}>Nome</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>CNPJ</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>WhatsApp</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Email</th>
                <th style={{ padding: '12px', textAlign: 'center' }}>Status</th>
                <th style={{ padding: '12px', textAlign: 'center' }}>Ações</th>
              </tr>
            </thead>
            <tbody>
              {fornecedores.map(f => (
                <tr key={f.id} style={{
                  borderBottom: '1px solid #eee',
                  '&:hover': { backgroundColor: '#f9f9f9' }
                }}>
                  <td style={{ padding: '12px' }}>
                    <strong>{f.nome}</strong>
                  </td>
                  <td style={{ padding: '12px' }}>
                    {f.cnpj || '-'}
                  </td>
                  <td style={{ padding: '12px' }}>
                    {f.contato_whatsapp ? (
                      <a href={`https://wa.me/${f.contato_whatsapp}`} target="_blank" rel="noreferrer">
                        {f.contato_whatsapp}
                      </a>
                    ) : '-'}
                  </td>
                  <td style={{ padding: '12px' }}>
                    {f.email || '-'}
                  </td>
                  <td style={{ padding: '12px', textAlign: 'center' }}>
                    <span style={{
                      padding: '4px 8px',
                      backgroundColor: f.ativo ? '#c8e6c9' : '#ffcccc',
                      color: f.ativo ? '#2e7d32' : '#c62828',
                      borderRadius: '4px',
                      fontSize: '12px',
                      fontWeight: 'bold'
                    }}>
                      {f.ativo ? 'Ativo' : 'Inativo'}
                    </span>
                  </td>
                  <td style={{ padding: '12px', textAlign: 'center' }}>
                    <button
                      onClick={() => handleEdit(f)}
                      style={{
                        padding: '6px 12px',
                        backgroundColor: '#1976d2',
                        color: 'white',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '12px',
                        marginRight: '5px'
                      }}
                    >
                      ✎ Editar
                    </button>
                    <button
                      onClick={() => handleDelete(f.id)}
                      style={{
                        padding: '6px 12px',
                        backgroundColor: '#f44336',
                        color: 'white',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '12px'
                      }}
                    >
                      🗑 Deletar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
