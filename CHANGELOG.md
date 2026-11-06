## [2026-11-06] - Teste-5
**PR:** #6 por @rsenoi

### O que mudou
Agora, sempre que alguém abre uma nova "issue" (um pedido, dúvida ou relato de problema) no projeto, o assistente Claude lê o texto automaticamente e responde com um comentário de triagem. O comentário classifica o tipo e a gravidade do assunto, estima o esforço necessário, indica quais partes do projeto provavelmente serão afetadas, sugere uma lista de tarefas, aponta pedidos parecidos já abertos e lista dúvidas ou riscos.

### Detalhes técnicos
- Novo workflow `.github/workflows/claude-code-issues.yml` ("Triagem de Issues com Claude"), disparado em `issues: opened`.
- Permissões do job: `issues: write`, `contents: read`, `id-token: write`, `pull-requests: write`.
- Usa `actions/checkout@v4` e `anthropics/claude-code-action@v1` autenticado com `CLAUDE_CODE_OAUTH_TOKEN`.
- Prompt em português com seções fixas (classificação, arquivos afetados, subtarefas, issues relacionadas, observações).
- `claude_args`: `--max-turns 30`, `--model claude-sonnet-5-5` e `--dangerously-skip-permissions`.

---

## [2026-11-05] - Teste-4
**PR:** #5 por @rsenoi

### O que mudou
Foi adicionada uma nova mensagem de teste ao programa de exemplo, que agora também exibe o texto "Mudando o ambiente para teste-04" quando é executado. É uma alteração pequena, usada apenas para validar o fluxo de trabalho do projeto.

### Detalhes técnicos
- `teste.py`: adicionada uma linha `print ("Mudando o ambiente para teste-04")` ao final do arquivo.

---

## [2026-11-05] - teste-3
**PR:** #4 por @rsenoi

### O que mudou
A revisão automática de código ficou mais completa: agora ela só roda para pessoas da equipe do projeto, escreve os comentários em português e também cria testes automáticos para o código novo. Além disso, sempre que uma alteração é aprovada e incorporada ao projeto, o sistema escreve sozinho um resumo do que mudou (como este) neste arquivo de histórico. Também foram definidas as permissões que o assistente Claude tem para editar arquivos e salvar alterações no projeto.

### Detalhes técnicos
- Novo `.claude/settings.json` com permissões `Write`, `Edit` e `Bash(git:*)` (add, commit, push).
- `.github/workflows/claude-code-review.yml`:
  - Gatilho `pull_request` inclui o tipo `closed`.
  - Job `claude-review` só roda se o PR não foi mergeado e o autor é MEMBER, OWNER ou COLLABORATOR; permissões elevadas para `write`; `fetch-depth: 0`.
  - Autenticação trocada de `ANTHROPIC_API_KEY` para `CLAUDE_CODE_OAUTH_TOKEN`; comentário sticky, `--max-turns 20` e system prompt de revisor Python/Django em português.
  - Novo passo "Gerar testes automaticamente" (pytest, commit na branch do PR).
  - Novo job `release-notes` (PR mergeado) que gera entrada no `CHANGELOG.md` e faz push na branch base, usando `--dangerously-skip-permissions`.

---
