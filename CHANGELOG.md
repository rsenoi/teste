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
