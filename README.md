# Sistema de Almoxarifado — Caio Pereira

Projeto simples para avaliação prática do SENAI. Desenvolvido em **Python 3**, sem Node.js, frameworks, bibliotecas externas ou banco de dados separado.

## Como executar
1. Instale/tenha o Python 3 disponível no computador.
2. Abra esta pasta no VS Code.
3. No terminal integrado, execute `python app.py` (no Windows, se necessário, use `py app.py`).
4. Abra `http://127.0.0.1:8000` no Edge, Chrome ou Firefox.

O banco `almoxarifado.db` é criado automaticamente na primeira execução.

## Acessos iniciais
- Administrador: `admin` / `admin123`
- Operador: `operador` / `operador123`

Altere as senhas após o primeiro acesso. O cadastro público cria somente contas de operador.

## Funcionalidades
- Login e identificação dos perfis administrador e operador.
- Rotas da API protegidas por sessão e perfil.
- Cadastro, consulta e atualização de produtos; exclusão somente pelo administrador.
- Paginação (10 itens), filtro por nome e data.
- Entradas e saídas com atualização automática do saldo.
- Bloqueio de saída acima do saldo, com mensagem de saldo disponível e solicitado.
- Histórico com data/hora, usuário responsável, tipo e quantidade.
- SQLite local, sem serviço externo.

## Testes
Execute `python -m unittest -v test_estoque.py`. O plano e os resultados estão documentados em `docs/plano_testes.docx` e `resultados.docx`. As evidências de execução ficam em `docs/testes/`.

## Estrutura
- `app.py`: servidor HTTP, banco, autenticação, regras e interface.
- `test_estoque.py`: testes automatizados da regra de saída.
- `docs/`: plano de testes e evidências.
- `resultados.docx`: relatório de execução dos testes.

## Observação de segurança
As credenciais iniciais são apenas para primeiro acesso/demonstração. O servidor escuta em `127.0.0.1`, apropriado para execução local durante a avaliação, não para publicação direta na internet.
